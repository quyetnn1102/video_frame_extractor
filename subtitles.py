"""
Vietnamese subtitles for a short, made on this computer:

1. faster-whisper turns the speech into timed lines and detects its language;
2. translation.py translates the lines into Vietnamese;
3. subtitles already burned into the picture (white text with a dark outline, as on Douyin and
   TikTok) are found by sampling frames, and that band is blurred for the whole video;
4. the Vietnamese lines are drawn into the band with Be Vietnam Pro (assets/fonts, a font with
   every Vietnamese accent) and the result is rendered as a new short.

The speech model is downloaded on first use into MODELS_FOLDER/whisper (about 500 MB for
'small'); later runs need no network.
"""
import bisect
import functools
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import get_config
from logger import app_logger
from short_video import close_clips, write_video
from translation import TranslationError, translation_route

FONT_PATH = Path(__file__).parent / 'assets' / 'fonts' / 'BeVietnamPro-Bold.ttf'

# -- burned-in subtitle detection: rows of bright pixels next to dark ones (outlined text) ----
TEXT_BRIGHTNESS = 200
OUTLINE_DARKNESS = 60
OUTLINE_REACH = 5             # px: how close a dark pixel must be to count as the outline
ROW_TEXT_SHARE = 0.02         # a row "has text" when this share of its pixels is outlined text
BAND_MIN_FRAME_SHARE = 0.1    # ... in at least this share of the sampled frames
BAND_SEARCH_FROM = 0.5        # subtitles sit in the lower half; titles at the top are left alone
BAND_GAP_SHARE = 0.02         # rows of a two-line subtitle are joined across a gap this high
BAND_PADDING_SHARE = 0.012
MAX_BAND_SHARE = 0.25         # a taller "band" is the picture itself, not subtitles
SAMPLE_FRAMES = 24
FRAME_TEXT_ROWS_SHARE = 0.01  # a frame shows a subtitle when this share of the band's rows has text
COVER_HOLD_SECONDS = 0.4      # the blur stays this long after the text was last seen

# -- the blur and the new text -----------------------------------------------------------
BLUR_SIGMA_SHARE = 0.2        # of the band height: strong enough to make the old text unreadable
BAND_DIMMING = 0.8            # the blurred band is darkened a little so white text stands out
FEATHER_ROWS = 12             # the blur fades in over this many rows at the band's edges
FONT_SHARE = 0.032            # of the frame height: 61 px on a 1080 x 1920 short
MIN_FONT_SHARE = 0.022
FONT_STEP = 2
SIDE_MARGIN_SHARE = 0.06
MAX_LINES = 2
LINE_SPACING = 1.25
STROKE_SHARE = 0.09           # outline width, of the font size
DEFAULT_TEXT_CENTER = 0.86    # where the text goes when no burned-in subtitles were found
OUTPUT_QUALITY = 'high'       # a re-encode: keep as much of the original as possible
OVERLAP_LOOKBACK = 4          # captions checked back from the latest start (speech rarely overlaps)
WHISPER_MODELS = ('tiny', 'base', 'small', 'medium', 'large-v3')  # the Systran faster-whisper builds

WHITESPACE = re.compile(r'\s+')
CONTROL_CHARACTERS = re.compile(r'[\x00-\x1f\x7f]')

ProgressCallback = Callable[[Optional[float]], None]


class SubtitleError(Exception):
    """A problem the user can act on; the message is safe to show."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def clean_text(text: str) -> str:
    return WHITESPACE.sub(' ', CONTROL_CHARACTERS.sub(' ', text)).strip()


# -- speech to text ---------------------------------------------------------------------------

def load_speech_model():
    """
    Loads (the first time: downloads) the speech model. It is loaded for each job and freed
    after it: kept loaded, it would hold hundreds of MB while the app waits.
    """
    from faster_whisper import WhisperModel

    name = get_config().WHISPER_MODEL
    if name not in WHISPER_MODELS:  # a path or any Hugging Face repository would also be loaded
        raise SubtitleError(f"WHISPER_MODEL must be one of: {', '.join(WHISPER_MODELS)}.")
    folder = get_config().MODELS_FOLDER / 'whisper'
    try:
        return WhisperModel(name, device='cpu', compute_type='int8', download_root=str(folder))
    except Exception as error:  # download or load failure: a network problem or a bad WHISPER_MODEL
        app_logger.error(f"Speech model {name!r} could not be loaded ({type(error).__name__})")
        raise SubtitleError('Could not load the speech model. Check the internet connection '
                            '(it is downloaded once) and the WHISPER_MODEL setting.') from error


def transcribe(video_path: Path, on_progress: ProgressCallback) -> Tuple[str, List[Cue]]:
    """(language code, timed lines) of the speech in a video."""
    model = load_speech_model()
    try:  # decodes the sound and detects the language at once; no progress (or cancel) in here
        segments, info = model.transcribe(str(video_path), vad_filter=True)
    except Exception as error:  # no audio track, or sound that cannot be decoded
        app_logger.error(f"Speech could not be read ({type(error).__name__})")
        raise SubtitleError('Could not read the sound of this short. It may have no audio.') from error
    if not info.duration_after_vad:  # nothing but silence or music: the language is a guess
        return info.language, []
    try:
        translation_route(info.language)  # say so now, before minutes of listening
    except TranslationError as error:
        raise SubtitleError(error.message) from None
    cues = []
    for segment in segments:  # a generator: the speech is decoded while it is read
        text = clean_text(segment.text)
        if text and segment.end > segment.start:
            cues.append(Cue(float(segment.start), float(segment.end), text))
        on_progress(min(1.0, segment.end / info.duration) if info.duration else None)
    return info.language, cues


# -- finding the burned-in subtitles -----------------------------------------------------------

def _text_rows(frame: np.ndarray) -> np.ndarray:
    """For each row of an RGB frame: does it look like outlined text?"""
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    near_dark = cv2.dilate((gray < OUTLINE_DARKNESS).astype(np.uint8),
                           np.ones((OUTLINE_REACH, OUTLINE_REACH), np.uint8)) > 0
    return ((gray > TEXT_BRIGHTNESS) & near_dark).mean(axis=1) > ROW_TEXT_SHARE


def find_subtitle_band(frames: Sequence[np.ndarray]) -> Optional[Tuple[int, int]]:
    """
    The rows (top, bottom) where burned-in subtitles appear across `frames` (RGB, one size),
    or None when there are none. Subtitles change, but they keep to the same rows.
    """
    if not frames:
        return None
    height = frames[0].shape[0]
    rows = np.mean([_text_rows(frame) for frame in frames], axis=0) >= BAND_MIN_FRAME_SHARE
    rows[:int(height * BAND_SEARCH_FROM)] = False
    found = np.flatnonzero(rows)
    if not found.size:
        return None
    # Group the rows into runs, joining small gaps (between two lines of one subtitle)
    breaks = np.flatnonzero(np.diff(found) > height * BAND_GAP_SHARE)
    run = max(np.split(found, breaks + 1), key=len)
    padding = round(height * BAND_PADDING_SHARE)
    top, bottom = max(0, int(run[0]) - padding), min(height, int(run[-1]) + 1 + padding)
    if bottom - top > height * MAX_BAND_SHARE:
        return None
    return top, bottom


def sample_frames(clip, count: int = SAMPLE_FRAMES) -> List[np.ndarray]:
    times = (np.arange(count) + 0.5) * clip.duration / count
    return [clip.get_frame(float(t)) for t in times]


def blur_band(frame: np.ndarray, band: Tuple[int, int]) -> np.ndarray:
    """A copy of `frame` with the rows of `band` blurred, darkened and faded in at the edges."""
    top, bottom = band
    result = frame.copy()
    region = frame[top:bottom].astype(np.float32)
    sigma = max(1.0, (bottom - top) * BLUR_SIGMA_SHARE)
    blurred = cv2.GaussianBlur(region, (0, 0), sigma) * BAND_DIMMING
    # Faded in from the edges inside the picture only: at the frame's edge the text must go too
    rows = np.arange(bottom - top, dtype=np.float32)
    from_top = rows + 1 if top > 0 else np.inf
    from_bottom = rows[::-1] + 1 if bottom < frame.shape[0] else np.inf
    weight = np.clip(np.minimum(from_top, from_bottom) / FEATHER_ROWS, 0, 1)[:, None, None]
    result[top:bottom] = (blurred * weight + region * (1 - weight)).astype(np.uint8)
    return result


# -- drawing the new subtitles -----------------------------------------------------------------

@dataclass(frozen=True)
class Caption:
    """A rendered subtitle: an RGBA image to place with its top-left corner at (left, top)."""
    start: float
    end: float
    left: int
    top: int
    image: np.ndarray


@functools.lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_PATH), size)


def wrap_words(text: str, font: ImageFont.FreeTypeFont, max_width: float) -> List[str]:
    lines: List[str] = []
    for word in text.split(' '):
        if lines and font.getlength(f'{lines[-1]} {word}') <= max_width:
            lines[-1] = f'{lines[-1]} {word}'
        else:
            lines.append(word)
    return lines


def fit_text(text: str, width: int, height: int) -> Tuple[ImageFont.FreeTypeFont, List[str]]:
    """The largest font (down to a minimum) that fits `text` in MAX_LINES across the frame."""
    max_width = width * (1 - 2 * SIDE_MARGIN_SHARE)
    size = round(height * FONT_SHARE)
    smallest = round(height * MIN_FONT_SHARE)
    while True:
        font = _font(size)
        lines = wrap_words(text, font, max_width)
        if len(lines) <= MAX_LINES or size - FONT_STEP < smallest:
            return font, lines
        size -= FONT_STEP


def split_long_cue(cue: Cue, frame_size: Tuple[int, int]) -> List[Cue]:
    """
    A cue that needs more than MAX_LINES even at the smallest size, as several cues of at most
    MAX_LINES each, sharing its time by their length (a long text would cover the picture).
    """
    width, height = frame_size
    font = _font(round(height * MIN_FONT_SHARE))
    lines = wrap_words(cue.text, font, width * (1 - 2 * SIDE_MARGIN_SHARE))
    if len(lines) <= MAX_LINES:
        return [cue]
    chunks = [' '.join(lines[index:index + MAX_LINES]) for index in range(0, len(lines), MAX_LINES)]
    total = sum(len(chunk) for chunk in chunks)
    parts, start = [], cue.start
    for chunk in chunks:
        end = start + (cue.end - cue.start) * len(chunk) / total
        parts.append(Cue(start, end, chunk))
        start = end
    return parts[:-1] + [Cue(parts[-1].start, cue.end, parts[-1].text)]  # no rounding gap at the end


def render_caption(cue: Cue, frame_size: Tuple[int, int], center_y: int) -> Optional[Caption]:
    width, height = frame_size
    font, lines = fit_text(cue.text, width, height)
    stroke = max(2, round(font.size * STROKE_SHARE))
    line_height = round(font.size * LINE_SPACING)
    canvas = Image.new('RGBA', (width, line_height * len(lines) + 2 * stroke), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for number, line in enumerate(lines):
        draw.text((width / 2, stroke + number * line_height), line, font=font, anchor='ma',
                  fill=(255, 255, 255, 255), stroke_width=stroke, stroke_fill=(0, 0, 0, 255))
    box = canvas.getbbox()
    if box is None:
        return None
    image = canvas.crop(box)
    top = int(np.clip(center_y - canvas.height / 2 + box[1], 0, height - image.height))
    return Caption(cue.start, cue.end, box[0], top, np.asarray(image))


def draw_caption(frame: np.ndarray, caption: Caption) -> np.ndarray:
    """A copy of `frame` with the caption blended in."""
    result = frame.copy()
    image = caption.image
    rows = slice(caption.top, caption.top + image.shape[0])
    columns = slice(caption.left, caption.left + image.shape[1])
    alpha = image[:, :, 3:4].astype(np.float32) / 255
    region = result[rows, columns].astype(np.float32)
    result[rows, columns] = (image[:, :, :3] * alpha + region * (1 - alpha)).astype(np.uint8)
    return result


class CaptionTrack:
    """Finds the caption showing at a time."""

    def __init__(self, captions: Sequence[Caption]):
        self.captions = sorted(captions, key=lambda caption: caption.start)
        self.starts = [caption.start for caption in self.captions]

    def at(self, t: float) -> Optional[Caption]:
        """The latest-starting caption showing at `t` (an earlier, longer one may still show)."""
        index = bisect.bisect_right(self.starts, t)
        for caption in reversed(self.captions[max(0, index - OVERLAP_LOOKBACK):index]):
            if t < caption.end:
                return caption
        return None


class SubtitleCover:
    """
    Blurs the band in the frames that show burned-in text, and for a moment after, so a subtitle
    that fades out does not flicker. Between lines the picture is left sharp.
    """

    def __init__(self, band: Tuple[int, int]):
        self.band = band
        self.covered_until = -math.inf
        self.last_t = -math.inf

    def shows_text(self, frame: np.ndarray) -> bool:
        top, bottom = self.band
        return _text_rows(frame[top:bottom]).mean() >= FRAME_TEXT_ROWS_SHARE

    def apply(self, frame: np.ndarray, t: float) -> np.ndarray:
        if t < self.last_t:  # MoviePy went back (it renders in order, but a seek is possible)
            self.covered_until = -math.inf
        self.last_t = t
        if self.shows_text(frame):
            self.covered_until = t + COVER_HOLD_SECONDS
        return blur_band(frame, self.band) if t <= self.covered_until else frame


def subtitle_frame(frame: np.ndarray, t: float, cover: Optional[SubtitleCover],
                   track: CaptionTrack) -> np.ndarray:
    result = cover.apply(frame, t) if cover else frame
    caption = track.at(t)
    return draw_caption(result, caption) if caption else result


def render_subtitled(source_path: Path, output_path: Path, cues: Sequence[Cue],
                     on_progress: Optional[ProgressCallback] = None) -> bool:
    """
    Renders `source_path` with its burned-in subtitles blurred and `cues` drawn in their place.
    Returns whether burned-in subtitles were found (and blurred).
    """
    from moviepy.editor import VideoFileClip

    video = subtitled = None
    try:
        video = VideoFileClip(str(source_path))
        band = find_subtitle_band(sample_frames(video))
        width, height = video.size
        center_y = (band[0] + band[1]) // 2 if band else round(height * DEFAULT_TEXT_CENTER)
        parts = [part for cue in cues for part in split_long_cue(cue, (width, height))]
        captions = (render_caption(part, (width, height), center_y) for part in parts)
        track = CaptionTrack([caption for caption in captions if caption])
        cover = SubtitleCover(band) if band else None
        subtitled = video.fl(lambda get_frame, t: subtitle_frame(get_frame(t), t, cover, track))
        write_video(subtitled, output_path, OUTPUT_QUALITY, on_progress)
    finally:
        close_clips((subtitled, video))
    return band is not None
