"""
Suggests the moments of a YouTube video most worth turning into a Short / Reel / TikTok.

Two free signals, both read through yt-dlp without downloading the video:
- YouTube's "Most replayed" heatmap: how often each part of the video is watched again;
- the captions, so a clip starts (and where possible ends) where a line of speech does.

No AI service is involved; nothing leaves this computer except the requests to YouTube.
"""
import bisect
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import yt_dlp

from logger import app_logger
from validators import validator
from video_processor import YouTubeProcessor

MAX_SUGGESTIONS = 5
INTRO_SHARE = 0.03          # the heatmap always peaks at the start (everyone begins there)
MIN_INTRO_SECONDS = 5.0
SNAP_BACK_SECONDS = 4.0     # how far a start may move back to meet the start of a caption line
MIN_KEPT_SHARE = 0.8        # an end may move back to a line's end if this much of the clip is kept
MAX_CAPTION_BYTES = 2 * 1024 * 1024
EXCERPT_LENGTH = 200
MAX_CAPTIONS = 10000        # far more than any real video; bounds the work on odd files
CAPTION_HOSTS = ('youtube.com', 'googlevideo.com')
PREFERRED_LANGUAGES = ('en',)


class ClipFinderError(Exception):
    """A problem the user can act on; `user_message` is written here, never exception text."""

    def __init__(self, user_message: str):
        super().__init__(user_message)
        self.user_message = user_message


@dataclass(frozen=True)
class Caption:
    start: float
    end: float
    text: str


# -- reading what yt-dlp returns ----------------------------------------------------

def parse_json3(data: Any) -> List[Caption]:
    """
    Caption lines from YouTube's json3 format, sorted by start. Empty, line-break-only and
    malformed events are skipped: the captions only refine the suggestions.
    """
    events = data.get('events') if isinstance(data, dict) else None
    captions = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict):
            continue
        segs = event.get('segs') if isinstance(event.get('segs'), list) else []
        text = ''.join(str(seg.get('utf8', '')) for seg in segs if isinstance(seg, dict))
        text = text.replace('\n', ' ').strip()
        try:
            start = float(event['tStartMs']) / 1000
            end = start + float(event.get('dDurationMs') or 0) / 1000
        except (KeyError, TypeError, ValueError):
            continue
        if text and start >= 0:
            captions.append(Caption(start, max(end, start), text))
    captions.sort(key=lambda caption: caption.start)
    return captions[:MAX_CAPTIONS]


def choose_caption_url(info: Dict[str, Any]) -> Optional[str]:
    """
    A json3 caption track: uploaded captions first (any language), then automatic captions in
    the spoken language only. Automatic captions also list machine translations into ~150
    languages, which would put words in the wrong places.
    """
    language = (info.get('language') or '').split('-')[0]
    wanted = [code for code in (language, *PREFERRED_LANGUAGES) if code]

    def rank(code: str) -> int:
        if code.endswith('-orig'):  # yt-dlp's name for automatic captions in the spoken language
            return -1
        base = code.split('-')[0]
        return wanted.index(base) if base in wanted else len(wanted)

    for tracks, any_language in ((info.get('subtitles') or {}, True),
                                 (info.get('automatic_captions') or {}, False)):
        for code in sorted(tracks, key=rank):
            if not any_language and rank(code) == len(wanted):
                break  # only translations are left
            for track in tracks[code] or []:
                if track.get('ext') == 'json3' and _is_caption_host(track.get('url', '')):
                    return track['url']
    return None


def _is_caption_host(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    return parts.scheme == 'https' and any(host == name or host.endswith('.' + name) for name in CAPTION_HOSTS)


# -- scoring ------------------------------------------------------------------------

def _average_heat(heatmap: Sequence[Dict[str, float]], start: float, end: float) -> float:
    """Replay intensity over [start, end], weighted by how much of each heatmap step it covers."""
    total = covered = 0.0
    for point in heatmap:
        overlap = min(end, point['end_time']) - max(start, point['start_time'])
        if overlap > 0:
            total += overlap * point['value']
            covered += overlap
    return total / covered if covered else 0.0


class _CaptionIndex:
    """Caption lines in sorted arrays, so each lookup is a binary search, not a pass over all lines."""

    def __init__(self, captions: Sequence[Caption]):
        self.captions = sorted(captions, key=lambda caption: caption.start)
        self.starts = [caption.start for caption in self.captions]
        self.ends = sorted(caption.end for caption in self.captions)
        self.words = [0]  # words[i] = words in the first i lines
        for caption in self.captions:
            self.words.append(self.words[-1] + len(caption.text.split()))

    def latest_start_in(self, low: float, high: float) -> Optional[float]:
        index = bisect.bisect_right(self.starts, high) - 1
        return self.starts[index] if index >= 0 and self.starts[index] >= low else None

    def latest_end_in(self, low: float, high: float) -> Optional[float]:
        index = bisect.bisect_right(self.ends, high) - 1
        return self.ends[index] if index >= 0 and self.ends[index] > low else None

    def speech_density(self, start: float, end: float) -> float:
        """Words per second spoken in [start, end]: the fallback when a video has no heatmap."""
        first, last = bisect.bisect_left(self.starts, start), bisect.bisect_left(self.starts, end)
        return (self.words[last] - self.words[first]) / max(end - start, 1)

    def excerpt(self, start: float, end: float) -> str:
        first, last = bisect.bisect_left(self.starts, start), bisect.bisect_left(self.starts, end)
        text = ' '.join(caption.text for caption in self.captions[first:last])
        return text if len(text) <= EXCERPT_LENGTH else text[:EXCERPT_LENGTH].rsplit(' ', 1)[0] + '...'


def _without_intro(heatmap: Sequence[Dict[str, float]], video_duration: float) -> List[Dict[str, float]]:
    intro = max(MIN_INTRO_SECONDS, video_duration * INTRO_SHARE)
    floor = min((point['value'] for point in heatmap), default=0.0)
    return [dict(point, value=floor) if point['start_time'] < intro else dict(point) for point in heatmap]


def _snap(start: float, duration: float, captions: Any, video_duration: float) -> Tuple[float, float]:
    """Start on a caption line (moving back a little) and end on one when little is lost."""
    index = captions if isinstance(captions, _CaptionIndex) else _CaptionIndex(captions)
    line_start = index.latest_start_in(start - SNAP_BACK_SECONDS, start)
    if line_start is not None:
        start = line_start
    start = max(0.0, min(start, max(0.0, video_duration - duration)))
    end = min(start + duration, video_duration)
    line_end = index.latest_end_in(start, end)
    if line_end is not None and line_end - start >= MIN_KEPT_SHARE * (end - start):
        end = line_end
    return round(start, 1), round(end - start, 1)


def suggest_windows(heatmap: Sequence[Dict[str, float]], captions: Sequence[Caption],
                    video_duration: float, duration: float,
                    count: int = MAX_SUGGESTIONS) -> List[Dict[str, Any]]:
    """The best non-overlapping clips of at most `duration` seconds, best first."""
    if video_duration <= 0:
        return []
    duration = min(duration, video_duration)
    index = _CaptionIndex(captions)
    heatmap = _without_intro(heatmap, video_duration) if heatmap else []
    if heatmap:
        starts = {point['start_time'] for point in heatmap} | set(index.starts)
        measure, overall = 'replay', _average_heat(heatmap, 0, video_duration) or 1.0
    elif captions:
        starts = set(index.starts)
        measure, overall = 'speech', index.speech_density(0, video_duration) or 1.0
    else:
        return []

    scored = []
    seen = set()
    for raw_start in sorted(starts):
        start, length = _snap(raw_start, duration, index, video_duration)
        if length <= 0 or start in seen:
            continue
        seen.add(start)
        end = start + length
        value = _average_heat(heatmap, start, end) if measure == 'replay' else index.speech_density(start, end)
        scored.append((value, start, length))
    scored.sort(key=lambda item: (-item[0], item[1]))

    chosen: List[Tuple[float, float, float]] = []
    for value, start, length in scored:
        if all(start + length <= other_start or start >= other_start + other_length
               for _, other_start, other_length in chosen):
            chosen.append((value, start, length))
        if len(chosen) == count:
            break

    best = chosen[0][0] if chosen and chosen[0][0] > 0 else 1.0
    return [{
        'start': start,
        'duration': length,
        'score': round(value / best, 2),
        'ratio': round(value / overall, 1),
        'reason': _reason(measure, value / overall, rank),
        'excerpt': index.excerpt(start, start + length),
    } for rank, (value, start, length) in enumerate(chosen)]


def _reason(measure: str, ratio: float, rank: int) -> str:
    if measure == 'speech':
        return 'Dense talking (this video has no replay data yet)'
    if rank == 0:
        return f'Most replayed part of the video ({ratio:.1f}x the average)'
    if ratio < 1.1:
        return 'Watched about as often as the rest of the video'
    return f'Replayed {ratio:.1f}x as often as the average'


# -- fetching -----------------------------------------------------------------------

def _fetch_captions(ydl: 'yt_dlp.YoutubeDL', info: Dict[str, Any]) -> Tuple[List[Caption], bool]:
    """(captions, available): available is True when the video has a usable track, read or not."""
    url = choose_caption_url(info)
    if not url:
        return [], False
    try:
        # yt-dlp's session: its proxy, cookies, headers and timeout (but not the extractor's
        # browser impersonation, so YouTube sometimes refuses; the heatmap still works then)
        with ydl.urlopen(url) as response:
            # Redirects are followed: drop anything that did not end on YouTube
            if not _is_caption_host(getattr(response, 'url', url)):
                app_logger.warning("Captions redirected away from YouTube; ignored")
                return [], True
            body = response.read(MAX_CAPTION_BYTES + 1)
        if len(body) > MAX_CAPTION_BYTES:
            return [], True
        return parse_json3(json.loads(body)), True
    except (yt_dlp.utils.YoutubeDLError, OSError, ValueError, TypeError) as error:
        app_logger.warning(f"Could not read the captions ({type(error).__name__})")
        return [], True


def suggest_clips(url: str, duration: float, max_video_seconds: int) -> Dict[str, Any]:
    """Reads the video's replay heatmap and captions (no download) and returns ranked clips."""
    url = validator.canonicalize_url(url)
    options = YouTubeProcessor().get_download_options(url)
    options.update({'skip_download': True, 'quiet': True, 'no_warnings': True})
    options.pop('progress_hooks', None)  # nothing is downloaded
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict):
                raise ClipFinderError('YouTube did not describe this video.')
            video_duration = float(info.get('duration') or 0)
            if video_duration <= 0:
                raise ClipFinderError('This video has no fixed length (a live stream?), so there is nothing to suggest.')
            if video_duration > max_video_seconds:
                raise ClipFinderError('This video is longer than the app accepts.')
            captions, captions_available = _fetch_captions(ydl, info)
    except yt_dlp.utils.YoutubeDLError as error:
        app_logger.warning(f"Clip suggestions: YouTube could not be read ({type(error).__name__})")
        raise ClipFinderError('YouTube could not be read for this video. Check the link, or try again later.') from error

    heatmap = info.get('heatmap') or []
    try:
        clips = suggest_windows(heatmap, captions, video_duration, duration)
    except (KeyError, TypeError, ValueError) as error:  # YouTube changed the heatmap's shape
        app_logger.warning(f"Clip suggestions: unexpected replay data ({type(error).__name__})")
        raise ClipFinderError("YouTube's replay data for this video could not be read.") from error
    if not clips:
        raise ClipFinderError('This video has no replay data and no captions yet, so there is nothing to '
                              'suggest. Pick the moment yourself.')
    return {
        'clips': clips,
        'video_duration': video_duration,
        # captions_unreadable: the video has captions, but YouTube did not let the app read them
        'signals': {'heatmap': bool(heatmap), 'captions': bool(captions),
                    'captions_unreadable': captions_available and not captions},
    }
