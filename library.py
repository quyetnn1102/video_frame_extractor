"""Lists the shorts already made, so the Create short page can show them again later."""
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

from logger import app_logger
from validators import resolve_in_folder

DEFAULT_LIMIT = 24
POSTER_FOLDER = '.posters'   # inside the shorts folder: one small JPEG per short
POSTER_WIDTH = 360           # pixels; enough for a list card at 2x
POSTER_QUALITY = 80
POSTER_AT_SECONDS = 1.0
STALE_PARTIAL_SECONDS = 3600  # a poster write takes milliseconds
FALLBACK_TITLE = 'Short video'
# create_short_video names files "<title>_<8 hex characters>_short.mp4"
_GENERATED_SUFFIX = re.compile(r'_[0-9a-f]{8}_short$')


def short_title(stem: str) -> str:
    """The title a short was made with, recovered from its file name."""
    return _GENERATED_SUFFIX.sub('', stem).strip() or FALLBACK_TITLE


def video_duration(path: Path) -> Optional[float]:
    """Length in seconds read from the file header, or None when it cannot be read."""
    import cv2  # imported here: it is slow to load and only needed for this

    capture = cv2.VideoCapture(str(path))
    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if fps and fps > 0 and frames and frames > 0:
            return round(frames / fps, 1)
        return None
    finally:
        capture.release()


def folder_size_bytes(folder: Path) -> int:
    """Total size of the files directly in `folder` (0 when it does not exist)."""
    total = 0
    try:
        entries = list(Path(folder).iterdir())
    except OSError:
        return 0
    for entry in entries:
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue  # removed while counting
    return total


def poster_path(video_path: Path) -> Path:
    """Where the poster (thumbnail) of a short lives: generated_shorts/.posters/<stem>.jpg."""
    video_path = Path(video_path)
    return video_path.parent / POSTER_FOLDER / (video_path.stem + '.jpg')


def make_poster(video_path: Path) -> bool:
    """
    Writes a small JPEG of an early frame of the short (the very first is often black).
    Returns False when the video cannot be read; a short without a poster still works.
    """
    import cv2

    video_path = Path(video_path)
    try:
        capture = cv2.VideoCapture(str(video_path))
        try:
            fps = capture.get(cv2.CAP_PROP_FPS) or 0
            frames = capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0
            duration = frames / fps if fps > 0 else 0
            capture.set(cv2.CAP_PROP_POS_MSEC, min(POSTER_AT_SECONDS, duration / 2) * 1000)
            ok, frame = capture.read()
        finally:
            capture.release()
        if not ok or frame is None:
            return False

        height, width = frame.shape[:2]
        if width > POSTER_WIDTH:
            frame = cv2.resize(frame, (POSTER_WIDTH, round(height * POSTER_WIDTH / width)),
                               interpolation=cv2.INTER_AREA)
        # Encoded in memory: cv2.imwrite cannot write to non-ASCII paths on Windows
        ok, encoded = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, POSTER_QUALITY])
        if not ok:
            return False
        target = poster_path(video_path)
        target.parent.mkdir(exist_ok=True)
        # A name of its own: a render and a cleanup's sync can make the same poster at once
        partial = target.with_name(f'.{uuid.uuid4().hex}.partial')
        try:
            partial.write_bytes(encoded.tobytes())
            os.replace(partial, target)
        finally:
            partial.unlink(missing_ok=True)
        return True
    except Exception as error:  # a poster is optional: never fail the short because of it
        app_logger.warning(f"Could not make a poster for a short ({type(error).__name__})")
        return False


def remove_poster(video_path: Path) -> None:
    try:
        poster_path(video_path).unlink(missing_ok=True)
    except OSError as error:
        app_logger.warning(f"Could not remove a poster ({type(error).__name__})")


def sync_posters(folder: Path) -> Tuple[int, int]:
    """
    Makes the posters that are missing (shorts from before posters existed) and removes those
    whose short is gone (deleted by the cleanup). Returns (made, removed).
    """
    folder = Path(folder)
    if not folder.is_dir():
        return 0, 0
    shorts = {path.stem: path for path in folder.glob('*.mp4') if path.is_file()}
    made = sum(1 for video in shorts.values() if not poster_path(video).exists() and make_poster(video))
    removed = 0
    for poster in (folder / POSTER_FOLDER).glob('*.jpg'):
        # Re-checked on disk: a short rendered after the list above was made is not an orphan
        if poster.stem in shorts or (folder / (poster.stem + '.mp4')).exists():
            continue
        try:
            poster.unlink()
            removed += 1
        except OSError:
            continue  # in use; the next sync removes it
    # Temporary files left by a crash mid-write (recent ones may still be in use)
    for partial in (folder / POSTER_FOLDER).glob('*.partial'):
        try:
            if time.time() - partial.stat().st_mtime > STALE_PARTIAL_SECONDS:
                partial.unlink()
        except OSError:
            continue
    return made, removed


def list_shorts(folder: Path, limit: int = DEFAULT_LIMIT) -> List[Dict[str, Any]]:
    """The newest shorts in `folder`, newest first."""
    folder = Path(folder)
    if not folder.is_dir():
        return []

    found = []
    for entry in folder.glob('*.mp4'):
        path = resolve_in_folder(folder, entry.name, ('.mp4',))
        if path is None:
            continue
        try:
            stat = path.stat()
        except OSError:
            continue  # removed while listing
        found.append((stat.st_mtime, path, stat.st_size))
    found.sort(key=lambda item: item[0], reverse=True)

    return [{
        'filename': path.name,
        'title': short_title(path.stem),
        'size': size,
        'created': datetime.fromtimestamp(modified, tz=timezone.utc).isoformat(),
        'duration': video_duration(path),
        'url': '/shorts/' + quote(path.name),
        # A still image for lists, so a page need not load every video to show it
        'poster': '/shorts/posters/' + quote(poster_path(path).name) if poster_path(path).is_file() else None,
    } for modified, path, size in found[:limit]]
