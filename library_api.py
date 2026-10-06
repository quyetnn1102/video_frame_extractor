"""
What the library page needs about each short beyond what is on disk: whether a job or an upload
is using it, whether YouTube would take it, and where it was uploaded.
"""
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Set

from database import db_manager
from library import VIETSUB_SUFFIX, count_shorts, list_shorts
from youtube_uploader import shorts_problem

BUSY_SHORT_MESSAGE = 'This short is in use (subtitles or an upload are in progress). Try again when it finishes.'

# Shorts being uploaded to YouTube right now (uploads run inside their request, not as jobs)
_uploading: Set[str] = set()
_uploading_lock = threading.Lock()


@contextmanager
def uploading(filename: str):
    """Marks a short as in use while it is uploaded, so it cannot be deleted meanwhile."""
    with _uploading_lock:
        _uploading.add(filename)
    try:
        yield
    finally:
        with _uploading_lock:
            _uploading.discard(filename)


def shorts_in_use(job_registry) -> Set[str]:
    """Names of the shorts a job or an upload is working on."""
    with _uploading_lock:
        uploads = set(_uploading)
    return job_registry.active_subjects() | uploads


def library_page(folder: Path, offset: int, limit: int, job_registry) -> Dict[str, Any]:
    """A page of the library, newest first, with what each short can do right now."""
    busy = shorts_in_use(job_registry)
    uploads = db_manager.get_uploads()
    shorts = list_shorts(folder, limit=limit, offset=offset)
    for item in shorts:
        item['busy'] = item['filename'] in busy
        item['subtitled'] = item['title'].endswith(VIETSUB_SUFFIX)
        item['upload_problem'] = shorts_problem(item['duration'], item['width'], item['height'])
        upload = uploads.get(item['filename'])
        item['youtube_url'] = f"https://www.youtube.com/watch?v={upload['video_id']}" if upload else None
    return {'shorts': shorts, 'offset': offset, 'limit': limit, 'total': count_shorts(folder)}
