"""Lists the shorts already made, so the Create short page can show them again later."""
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from validators import resolve_in_folder

DEFAULT_LIMIT = 24
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
    } for modified, path, size in found[:limit]]
