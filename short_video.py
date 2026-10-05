"""
Short-video rendering with MoviePy.

Extracted from the /api/create-short route so request parsing and rendering
can be tested separately. All user-controlled values (start time, duration,
quality and the text overlay) are validated here before MoviePy sees them.
"""
import math
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import get_config
from logger import app_logger
from validators import validator

QUALITY_BITRATES = {'low': '1000k', 'medium': '2000k', 'high': '5000k'}
DEFAULT_QUALITY = 'medium'

SHORT_SIZE = (1080, 1920)  # width, height of the vertical output
VERTICAL_ASPECT = 9 / 16
MIN_SHORT_DURATION = 1
MAX_SHORT_DURATION = 300  # seconds

MAX_OVERLAY_LENGTH = 100
FONT_SIZE_LIMITS = (8, 200)
STROKE_WIDTH_LIMITS = (0, 10)
OVERLAY_POSITIONS = ('top', 'center', 'bottom')
DEFAULT_OVERLAY_POSITION = 'bottom'
OVERLAY_MARGIN = 50

COLOR_PATTERN = re.compile(r'#[0-9a-fA-F]{6}|[a-zA-Z]{3,20}')
CONTROL_CHARACTERS = re.compile(r'[\x00-\x1f\x7f]')


class ShortVideoError(ValueError):
    """A problem with the request; the message is safe to show to the user."""


def _as_number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ShortVideoError(f"{name} must be a number")
    try:
        number = float(value)
    except ValueError:
        raise ShortVideoError(f"{name} must be a number") from None
    if not math.isfinite(number):
        raise ShortVideoError(f"{name} must be a number")
    return number


def parse_start_time(value: Any) -> float:
    """Seconds, 'MM:SS' or 'HH:MM:SS' (blank or None means the beginning)."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return 0.0

    if isinstance(value, str) and ':' in value:
        is_valid, error, seconds = validator.validate_timestamp(value)
        if not is_valid:
            raise ShortVideoError(f"Invalid start time: {error}")
        return float(seconds)

    seconds = _as_number(value, "Start time")
    if seconds < 0:
        raise ShortVideoError("Start time cannot be negative")
    if seconds > get_config().MAX_VIDEO_DURATION:
        raise ShortVideoError("Start time exceeds the maximum video duration")
    return seconds


def parse_duration(value: Any) -> float:
    seconds = _as_number(value, "Duration")
    if not MIN_SHORT_DURATION <= seconds <= MAX_SHORT_DURATION:
        raise ShortVideoError(
            f"Duration must be between {MIN_SHORT_DURATION} and {MAX_SHORT_DURATION} seconds")
    return seconds


def normalize_quality(value: Any) -> str:
    if value is None or value == '':
        return DEFAULT_QUALITY
    quality = str(value).strip().lower()
    if quality not in QUALITY_BITRATES:
        raise ShortVideoError(f"Quality must be one of: {', '.join(QUALITY_BITRATES)}")
    return quality


def _bounded_int(value: Any, name: str, limits: Tuple[int, int]) -> int:
    number = _as_number(value, name)
    if not limits[0] <= number <= limits[1] or number != int(number):
        raise ShortVideoError(f"{name} must be a whole number from {limits[0]} to {limits[1]}")
    return int(number)


def _color(value: Any, name: str, default: str) -> str:
    if value is None:
        return default
    if not isinstance(value, str) or not COLOR_PATTERN.fullmatch(value):
        raise ShortVideoError(f"{name} must be a color name or #RRGGBB")
    return value


def normalize_text_overlay(value: Any) -> Optional[Dict[str, Any]]:
    """
    Validate an overlay request (a plain string or a dict) into a clean dict.
    Returns None when there is no text to draw.
    """
    if value is None or value == '':
        return None
    if isinstance(value, str):
        value = {'text': value}
    if not isinstance(value, dict):
        raise ShortVideoError("Text overlay must be text or an object")

    text = value.get('text')
    if text is None:
        return None
    if not isinstance(text, str):
        raise ShortVideoError("Overlay text must be a string")
    text = CONTROL_CHARACTERS.sub('', text).strip()
    if not text:
        return None
    if len(text) > MAX_OVERLAY_LENGTH:
        raise ShortVideoError(f"Overlay text is limited to {MAX_OVERLAY_LENGTH} characters")

    position = value.get('position') or DEFAULT_OVERLAY_POSITION
    if position not in OVERLAY_POSITIONS:
        raise ShortVideoError(f"Overlay position must be one of: {', '.join(OVERLAY_POSITIONS)}")

    return {
        # ImageMagick expands %-escapes in labels, so a literal % is doubled.
        'text': text.replace('%', '%%'),
        'fontsize': _bounded_int(value.get('fontsize', 50), "Font size", FONT_SIZE_LIMITS),
        'color': _color(value.get('color'), "Color", 'white'),
        'stroke_color': _color(value.get('stroke_color'), "Stroke color", 'black'),
        'stroke_width': _bounded_int(value.get('stroke_width', 2), "Stroke width", STROKE_WIDTH_LIMITS),
        'position': position,
    }


def compute_vertical_crop(width: int, height: int) -> Optional[Tuple[int, int, int, int]]:
    """
    Centered crop box (x1, y1, x2, y2) that turns a frame into 9:16, or None
    when it already is. Handles both too-wide and too-tall sources.
    """
    if width <= 0 or height <= 0:
        raise ValueError("Frame size must be positive")

    ratio = width / height
    if ratio > VERTICAL_ASPECT:
        new_width = int(height * VERTICAL_ASPECT)
        x1 = (width - new_width) // 2
        return x1, 0, x1 + new_width, height
    if ratio < VERTICAL_ASPECT:
        new_height = int(width / VERTICAL_ASPECT)
        y1 = (height - new_height) // 2
        return 0, y1, width, y1 + new_height
    return None


def _build_text_clip(text_clip_class, overlay: Dict[str, Any], duration: float):
    clip = text_clip_class(
        overlay['text'],
        fontsize=overlay['fontsize'],
        color=overlay['color'],
        stroke_color=overlay['stroke_color'],
        stroke_width=overlay['stroke_width'],
    )
    if overlay['position'] == 'center':
        clip = clip.set_position('center')
    else:
        clip = clip.set_position(('center', overlay['position'])).set_margin(OVERLAY_MARGIN)
    return clip.set_duration(duration)


def _close_all(clips) -> None:
    for clip in clips:
        if clip is not None:
            try:
                clip.close()
            except Exception as error:  # closing must never mask the real result
                app_logger.warning(f"Could not close clip ({type(error).__name__})")


def create_short(source_path: Path, output_path: Path, *, start: float, duration: float,
                 vertical: bool = False, quality: str = DEFAULT_QUALITY,
                 text_overlay: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Cut `duration` seconds from `source_path` starting at `start` into `output_path`.

    Returns:
        {'start_time', 'duration', 'warnings'} describing what was rendered.
    Raises:
        ShortVideoError if the start time is past the end of the video.
    """
    from moviepy.editor import CompositeVideoClip, TextClip, VideoFileClip

    output_path = Path(output_path)
    warnings: List[str] = []
    video = clip = text_clip = final = None
    try:
        video = VideoFileClip(str(source_path))
        if start >= video.duration:
            raise ShortVideoError(
                f"Start time ({start:g}s) exceeds video duration ({video.duration:.1f}s)")

        actual_duration = min(duration, video.duration - start)
        clip = video.subclip(start, start + actual_duration)

        if vertical:
            box = compute_vertical_crop(*clip.size)
            if box:
                clip = clip.crop(x1=box[0], y1=box[1], x2=box[2], y2=box[3])
            clip = clip.resize(SHORT_SIZE)

        final = clip
        if text_overlay:
            try:
                text_clip = _build_text_clip(TextClip, text_overlay, clip.duration)
                final = CompositeVideoClip([clip, text_clip])
            except (OSError, ValueError) as error:
                # Usually ImageMagick is not installed; the video itself is still fine.
                app_logger.warning(f"Text overlay skipped ({type(error).__name__})")
                warnings.append("Text overlay was skipped (ImageMagick is required for text)")

        final.write_videofile(
            str(output_path),
            codec='libx264',
            audio_codec='aac',
            bitrate=QUALITY_BITRATES[quality],
            temp_audiofile=str(output_path.with_suffix('.tmp-audio.m4a')),
            remove_temp=True,
            verbose=False,
            logger=None,
        )
    except Exception:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        _close_all((final if final is not clip else None, text_clip, clip, video))

    return {'start_time': start, 'duration': round(actual_duration, 2), 'warnings': warnings}
