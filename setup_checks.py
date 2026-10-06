"""
What this computer has for the optional parts of the app, shown on the Dashboard's Setup card.
Pages then leave out what cannot work (a caption field without ImageMagick) instead of
explaining installation steps in the middle of a task.
"""
import os
from typing import Dict, List

from config import get_config
from short_video import text_overlay_available
from translation import ARGOS_MODELS, model_folder
from video_processor import javascript_runtime_available
from youtube_uploader import youtube_uploader

READY, MISSING, OPTIONAL = 'ready', 'missing', 'optional'


def _subtitle_models_ready() -> bool:
    config = get_config()
    speech = config.MODELS_FOLDER / 'whisper'
    has_speech = speech.is_dir() and any(speech.iterdir())
    return has_speech and all((model_folder(pair) / 'model' / 'model.bin').is_file() for pair in ARGOS_MODELS)


def setup_checks() -> List[Dict[str, str]]:
    """[{name, status, detail}]: status is READY, MISSING (a feature will not work) or OPTIONAL."""
    config = get_config()
    checks = [
        ('YouTube downloads', javascript_runtime_available(), MISSING,
         'Node.js, Deno or Bun is installed.',
         'Install Node.js (or Deno): without one, YouTube often stops downloads part-way.'),
        ('Captions on shorts', text_overlay_available(), OPTIONAL,
         'ImageMagick is installed.',
         'Captions need ImageMagick; without it the caption field is hidden. Install it and restart the app.'),
        ('YouTube upload', youtube_uploader.is_configured(), OPTIONAL,
         'client_secrets.json is in place.',
         'Add client_secrets.json from Google Cloud to upload to your channel (see "YouTube upload" in the README).'),
        ('Trending page', bool(os.getenv('YOUTUBE_API_KEY')), OPTIONAL,
         'A YouTube Data API key is set.',
         'Add YOUTUBE_API_KEY to the .env file for live results; without it the page shows sample videos.'),
        ('Douyin', config.DOUYIN_COOKIE_FILE_PATH.is_file(), OPTIONAL,
         'douyin_cookies.txt is in place.',
         'Douyin often refuses downloads without your browser cookies in douyin_cookies.txt.'),
        ('Vietnamese subtitles', _subtitle_models_ready(), OPTIONAL,
         'The speech and translation models are downloaded.',
         'The models (about 640 MB) are downloaded the first time you add subtitles.'),
    ]
    return [{'name': name, 'status': READY if ready else when_missing, 'detail': ready_text if ready else missing_text}
            for name, ready, when_missing, ready_text, missing_text in checks]
