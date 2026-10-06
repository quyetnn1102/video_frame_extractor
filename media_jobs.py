"""
The work behind /api/extract and /api/create-short: check the request, download the video,
then extract frames or render a short.

The original routes run it while the browser waits; the /api/jobs routes run the same code as a
background job (jobs.py), reporting each stage and stopping when the user cancels. Adding
Vietnamese subtitles to a short in the library is a job only (/api/jobs/subtitles).
"""
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from config import get_config
from database import db_manager
from jobs import JobCancelled, JobFailed
from library import VIETSUB_SUFFIX, make_poster, short_title
from logger import app_logger
from short_video import (DEFAULT_CROP_POSITION, ShortVideoError, create_short, normalize_quality,
                         normalize_text_overlay, parse_crop_position, parse_duration, parse_start_time)
from subtitles import Cue, SubtitleError, render_subtitled, transcribe
from translation import TranslationError, language_name, translate_to_vietnamese
from validators import format_clock, validator
from video_processor import extractor

MAX_FRAME_FILENAME_TITLE = 50
DEFAULT_SHORT_DURATION = 30
MAX_ERRORS_LISTED = 3  # a job that fails on every timecode names this many
FRAME_FORMATS = ('jpg', 'png')  # JPEG is smaller; PNG keeps every pixel

EXTRACT_STAGES = ('download', 'extract')
SHORT_STAGES = ('download', 'render')
SUBTITLE_STAGES = ('listen', 'translate', 'render')


@dataclass(frozen=True)
class ExtractRequest:
    url: str
    platform: str
    seconds: Tuple[int, ...]
    image_format: str = 'jpg'


@dataclass(frozen=True)
class ShortRequest:
    url: str
    platform: str
    start: float
    duration: float
    quality: str
    vertical: bool
    text_overlay: Optional[Dict[str, Any]]
    crop_position: float = DEFAULT_CROP_POSITION


# -- small file helpers -------------------------------------------------------------

def remove_quietly(path) -> None:
    """Delete a temporary file; a failure is logged, never raised."""
    try:
        Path(path).unlink(missing_ok=True)
    except OSError as error:
        app_logger.warning(f"Could not remove temporary file ({type(error).__name__})")


def file_size_or_none(path) -> Optional[int]:
    try:
        return os.path.getsize(path)
    except OSError:
        return None


# -- requests: everything is checked before anything is downloaded --------------------

def _checked_url(data: Dict[str, Any], invalid_prefix: str = '') -> Tuple[Optional[Tuple[str, str]], Optional[str]]:
    url = data.get('url')
    if not isinstance(url, str) or not url.strip():
        return None, 'URL is required'
    url = url.strip()
    is_valid, platform, url_error = validator.validate_url(url)
    if not is_valid:
        return None, invalid_prefix + url_error
    return (url, platform), None


def parse_extract_request(data: Optional[Dict[str, Any]]) -> Tuple[Optional[ExtractRequest], Optional[str]]:
    """(request, None) or (None, a message for a 400 response)."""
    if data is None:
        return None, 'No data provided'
    checked, error = _checked_url(data)
    if error:
        return None, error
    timestamps = data.get('timestamps', [])
    if not isinstance(timestamps, list):
        return None, 'timestamps must be a list'
    timestamps_valid, timestamp_errors, seconds_list = validator.validate_timestamps(timestamps)
    if not timestamps_valid:
        return None, '; '.join(timestamp_errors)
    image_format = data.get('format') or 'jpg'
    if image_format not in FRAME_FORMATS:
        return None, f"format must be one of: {', '.join(FRAME_FORMATS)}"
    # 90 and 1:30 are the same moment: one frame each, in the order typed
    return ExtractRequest(*checked, seconds=tuple(dict.fromkeys(seconds_list)), image_format=image_format), None


def parse_short_request(data: Optional[Dict[str, Any]]) -> Tuple[Optional[ShortRequest], Optional[str]]:
    """(request, None) or (None, a message for a 400 response)."""
    if data is None:
        return None, 'JSON body required'
    checked, error = _checked_url(data, invalid_prefix='Invalid URL: ')
    if error:
        return None, error

    overlay_request = data.get('text_overlay')
    if overlay_request is None:
        overlay_request = data.get('overlay_text')  # field name of the older page
    try:
        start = parse_start_time(data.get('start_time'))
        duration = parse_duration(data.get('duration', DEFAULT_SHORT_DURATION))
        quality = normalize_quality(data.get('quality'))
        text_overlay = normalize_text_overlay(overlay_request)
        crop_position = parse_crop_position(data.get('crop_position'))
    except ShortVideoError as error:
        return None, str(error)
    vertical = data.get('vertical_format', False)
    if not isinstance(vertical, bool):
        return None, 'vertical_format must be true or false'
    return ShortRequest(*checked, start=start, duration=duration, quality=quality, vertical=vertical,
                        text_overlay=text_overlay, crop_position=crop_position), None


# -- the work -----------------------------------------------------------------------

def finish_request_record(request_id: int, status: str, started: float,
                          error: Optional[str] = None, title: Optional[str] = None) -> None:
    if request_id:
        db_manager.update_video_request(
            request_id, status, error, int((time.time() - started) * 1000), title=title)


def run_recorded(record_id: int, crash_message: str, work: Callable[[], Dict[str, Any]]) -> Dict[str, Any]:
    """Runs `work` and records how it ended on the dashboard's request log."""
    started = time.time()
    try:
        result = work()
    except JobFailed as failure:
        finish_request_record(record_id, 'failed', started, failure.message)
        raise
    except JobCancelled:
        finish_request_record(record_id, 'cancelled', started, 'Cancelled by the user')
        raise
    except Exception:
        finish_request_record(record_id, 'failed', started, crash_message)
        raise
    finish_request_record(record_id, 'completed', started, title=result.get('title'))
    return result


def download_source(url: str, reporter, start: float = 0.0) -> Tuple[str, Optional[str]]:
    """
    (path, title) of the downloaded video; raises JobFailed with the reason. With `start`, a
    video that ends before it is refused before it is downloaded.
    """
    reporter.stage('download', 'Downloading the video')
    video_path, title, error = extractor.download_video(url, on_progress=reporter.progress, start=start)
    if not video_path:
        raise JobFailed(error or 'Download failed')
    return video_path, title


def extract_frames(request: ExtractRequest, record_id: int, reporter) -> Dict[str, Any]:
    folder = get_config().FRAMES_FOLDER
    video_path, title = download_source(request.url, reporter)
    frames: List[Dict[str, Any]] = []
    errors: List[str] = []
    try:
        reporter.stage('extract', 'Extracting frames')
        for done, seconds in enumerate(request.seconds):
            reporter.progress(done / len(request.seconds))
            frame_filename = f"frame_{seconds}s_{uuid.uuid4().hex[:8]}.{request.image_format}"
            frame_path = folder / frame_filename
            success, frame_error = extractor.extract_frame_at_timestamp(video_path, seconds, str(frame_path))
            if success:
                frames.append({'timestamp': seconds, 'filename': frame_filename,
                               'url': f'/frames/{frame_filename}'})
                db_manager.log_extracted_frame(record_id, seconds, frame_filename, file_size_or_none(frame_path))
            else:
                errors.append(f"{format_clock(seconds)}: {frame_error}")
        reporter.progress(1)
    except JobCancelled:
        # "Cancelled, nothing was extracted": the frames written so far go too
        for frame in frames:
            remove_quietly(folder / frame['filename'])
        raise
    finally:
        remove_quietly(video_path)

    if not frames:
        listed = '; '.join(errors[:MAX_ERRORS_LISTED])
        more = len(errors) - MAX_ERRORS_LISTED
        raise JobFailed('No frames could be extracted. ' + listed + (f'; and {more} more' if more > 0 else ''))
    # 'url' lets a page that picks up a finished job remember which link the frames came from
    result = {'success': True, 'title': title, 'frames': frames, 'platform': request.platform,
              'url': request.url}
    if errors:
        result['warnings'] = errors
    return result


def short_file_name(video_title: Optional[str]) -> str:
    safe_title = "".join(
        c for c in (video_title or "short")[:MAX_FRAME_FILENAME_TITLE]
        if c.isalnum() or c in ' -_').strip() or 'short'
    return f"{safe_title}_{uuid.uuid4().hex[:8]}_short.mp4"


def render_short(request: ShortRequest, reporter) -> Dict[str, Any]:
    video_path, video_title = download_source(request.url, reporter, start=request.start)
    output_name = short_file_name(video_title)
    output_path = get_config().SHORTS_FOLDER / output_name
    try:
        reporter.stage('render', 'Rendering the short')
        result = create_short(Path(video_path), output_path, start=request.start,
                              duration=request.duration, vertical=request.vertical,
                              quality=request.quality, text_overlay=request.text_overlay,
                              on_progress=reporter.progress, crop_position=request.crop_position)
    except ShortVideoError as error:
        raise JobFailed(str(error)) from error
    finally:
        remove_quietly(video_path)

    make_poster(output_path)  # the thumbnail lists show; without one they fall back to the video
    response = {
        'success': True,
        'message': 'Short video created successfully',
        'filename': output_name,
        'title': video_title,
        'duration': result['duration'],
        'start_time': result['start_time'],
        'quality': request.quality,
        'file_size': file_size_or_none(output_path),
        'download_url': f'/shorts/{quote(output_name)}',
    }
    if result['warnings']:
        response['warnings'] = result['warnings']
    return response


def add_vietnamese_subtitles(source_path: Path, reporter) -> Dict[str, Any]:
    """
    Makes a copy of a short in the library with its speech subtitled in Vietnamese, and any
    subtitles burned into the picture blurred (subtitles.py). The original is left as it is.
    """
    try:
        reporter.stage('listen', 'Listening to the speech (the first time also downloads the speech model)')
        language, cues = transcribe(source_path, reporter.progress)
        if not cues:
            raise JobFailed('No speech was found in this short, so there is nothing to subtitle.')
        reporter.stage('translate', f'Translating from {language_name(language)}')
        texts = translate_to_vietnamese([cue.text for cue in cues], language, on_download=reporter.progress)
    except (SubtitleError, TranslationError) as error:
        raise JobFailed(error.message) from error
    cues = [Cue(cue.start, cue.end, text) for cue, text in zip(cues, texts) if text]
    if not cues:
        raise JobFailed('The speech could not be translated, so no subtitles were made.')

    title = short_title(source_path.stem)[:MAX_FRAME_FILENAME_TITLE - len(VIETSUB_SUFFIX)].strip()
    output_name = short_file_name(title + VIETSUB_SUFFIX)
    output_path = source_path.parent / output_name
    reporter.stage('render', 'Blurring the old subtitles and adding the Vietnamese ones')
    blurred = render_subtitled(source_path, output_path, cues, reporter.progress)
    make_poster(output_path)

    response = {
        'success': True,
        'message': 'Vietnamese subtitles added',
        'filename': output_name,
        'title': title + VIETSUB_SUFFIX,
        'language': language_name(language),
        'subtitle_count': len(cues),
        'file_size': file_size_or_none(output_path),
        'download_url': f'/shorts/{quote(output_name)}',
    }
    if not blurred:
        response['warnings'] = ['No subtitles were found in the picture, so nothing was blurred. '
                                'The Vietnamese subtitles are near the bottom.']
    return response
