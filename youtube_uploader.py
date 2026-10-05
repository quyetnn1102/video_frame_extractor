"""
YouTube Video Upload Module
Uploads short videos to the user's own channel with the YouTube Data API v3.

Sign-in uses the OAuth 2.0 authorization-code flow: begin_auth() returns the
Google consent URL, and complete_auth() is called from the /oauth2callback
route with the returned code and state. Credentials are stored as JSON (never
pickled) next to the project with owner-only permissions.
"""
import hmac
import json
import os
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config import get_config
from logger import app_logger

PRIVACY_STATUSES = ('private', 'unlisted', 'public')
TITLE_LIMIT = 100
DESCRIPTION_LIMIT = 5000
TAGS_CHARACTER_LIMIT = 500
SHORTS_TAG = "#Shorts"
DEFAULT_TITLE = "Short video"
DEFAULT_TAGS = ["Shorts"]
AUTH_TIMEOUT_SECONDS = 600
UPLOAD_RETRYABLE_STATUSES = (500, 502, 503, 504)
UPLOAD_MAX_RETRIES = 3
QUOTA_DOCS_URL = "https://developers.google.com/youtube/v3/determine_quota_cost"


class YouTubeUploaderError(Exception):
    """An error whose message is safe to show to the user."""


@dataclass
class _PendingAuth:
    flow: Any
    state: str
    expires_at: float


def _flow_class():
    """Import lazily so the app still starts when google-auth-oauthlib is missing."""
    try:
        from google_auth_oauthlib.flow import Flow
    except ImportError as error:
        raise YouTubeUploaderError(
            "google-auth-oauthlib is not installed. Run: uv sync"
        ) from error
    return Flow


def normalize_tags(tags: Any) -> List[str]:
    """Keep string tags only, without angle brackets, within YouTube's 500-character limit."""
    if not isinstance(tags, (list, tuple)):
        return list(DEFAULT_TAGS)

    cleaned: List[str] = []
    total = 0
    for tag in tags:
        if not isinstance(tag, str):
            continue
        tag = tag.replace('<', '').replace('>', '').strip()
        if not tag or total + len(tag) > TAGS_CHARACTER_LIMIT:
            continue
        cleaned.append(tag)
        total += len(tag)
    return cleaned or list(DEFAULT_TAGS)


class YouTubeUploader:
    """Handles YouTube video uploads with OAuth2 authentication"""

    # Upload-only scope: the app cannot read or manage the channel.
    YOUTUBE_UPLOAD_SCOPE = ["https://www.googleapis.com/auth/youtube.upload"]
    YOUTUBE_API_SERVICE_NAME = "youtube"
    YOUTUBE_API_VERSION = "v3"

    # YouTube Shorts requirements
    SHORTS_MAX_DURATION = 60  # seconds
    SHORTS_MAX_FILE_BYTES = 2 * 1024 * 1024 * 1024

    def __init__(self, client_secrets_file: Optional[Path] = None,
                 credentials_file: Optional[Path] = None,
                 redirect_uri: Optional[str] = None):
        config = get_config()
        self.client_secrets_file = Path(client_secrets_file or config.YOUTUBE_CLIENT_SECRETS_FILE)
        self.credentials_file = Path(credentials_file or config.YOUTUBE_CREDENTIALS_FILE)
        self.redirect_uri = redirect_uri or config.YOUTUBE_REDIRECT_URI
        self.youtube_service = None
        self._pending: Optional[_PendingAuth] = None
        self._lock = threading.Lock()
        self._sleep = time.sleep

    # -- authentication -----------------------------------------------------

    def is_authenticated(self) -> bool:
        """True when saved credentials are valid (refreshing them when needed)."""
        credentials = self._load_credentials()
        if credentials is None:
            return False

        if not credentials.valid:
            if not (credentials.expired and credentials.refresh_token):
                return False
            try:
                credentials.refresh(Request())
                self._save_credentials(credentials)
            except Exception as error:  # network, revoked token, bad JSON...
                app_logger.warning(f"YouTube token refresh failed ({type(error).__name__})")
                return False

        self.youtube_service = self._build_service(credentials)
        return True

    def begin_auth(self, redirect_uri: Optional[str] = None) -> str:
        """Start the OAuth flow and return the Google consent URL."""
        if not self.client_secrets_file.exists():
            raise YouTubeUploaderError(
                f"{self.client_secrets_file.name} not found. "
                "Create OAuth credentials in Google Cloud Console (see the README).")

        flow = _flow_class().from_client_secrets_file(
            str(self.client_secrets_file),
            scopes=self.YOUTUBE_UPLOAD_SCOPE,
            redirect_uri=redirect_uri or self.redirect_uri,
            # PKCE is off unless requested here: the factory passes None to Flow, not its True default
            autogenerate_code_verifier=True,
        )
        auth_url, state = flow.authorization_url(access_type='offline', prompt='consent')

        with self._lock:
            self._pending = _PendingAuth(flow, state, time.monotonic() + AUTH_TIMEOUT_SECONDS)
        return auth_url

    def complete_auth(self, authorization_code: str, state: str) -> Tuple[bool, str]:
        """Finish sign-in with the code and state Google sent back to the callback."""
        # Check and consume under one lock: only a callback carrying the right state can end
        # the sign-in (a forged one must not cancel the user's), and when several arrive at
        # once exactly one wins.
        with self._lock:
            pending = self._pending
            if pending is None:
                return False, "No sign-in is in progress. Please start again."
            if time.monotonic() > pending.expires_at:
                self._pending = None
                return False, "The sign-in has expired. Please start again."
            if not self._state_matches(state, pending.state):
                return False, "Sign-in state did not match. Please start again."
            if not authorization_code:
                return False, "Authorization code is missing."
            self._pending = None  # a sign-in attempt is single-use

        try:
            pending.flow.fetch_token(code=authorization_code)
            credentials = pending.flow.credentials
            self._save_credentials(credentials)
            self.youtube_service = self._build_service(credentials)
        except Exception as error:  # oauthlib raises many types; none are user-actionable
            app_logger.error(f"Failed to complete YouTube authentication ({type(error).__name__})")
            return False, "Authentication failed. Please try again."

        return True, "Authentication completed successfully"

    @staticmethod
    def _state_matches(candidate, expected: str) -> bool:
        """Constant-time comparison; bytes, because compare_digest rejects non-ASCII str."""
        if not isinstance(candidate, str):
            return False
        return hmac.compare_digest(candidate.encode('utf-8'), expected.encode('utf-8'))

    def _build_service(self, credentials):
        return build(self.YOUTUBE_API_SERVICE_NAME, self.YOUTUBE_API_VERSION,
                     credentials=credentials, cache_discovery=False)

    # -- credential storage -------------------------------------------------

    def _load_credentials(self) -> Optional[Credentials]:
        legacy_pickle = self.credentials_file.with_suffix('.pickle')
        if legacy_pickle.exists():
            # Unpickling can execute code, so old pickle files are never loaded.
            app_logger.warning(
                f"Ignoring legacy {legacy_pickle.name}; please sign in to YouTube again")

        if not self.credentials_file.exists():
            return None
        try:
            info = json.loads(self.credentials_file.read_text(encoding='utf-8'))
            return Credentials.from_authorized_user_info(info, self.YOUTUBE_UPLOAD_SCOPE)
        except (OSError, ValueError) as error:
            app_logger.warning(f"Could not load saved YouTube credentials ({type(error).__name__})")
            return None

    def _save_credentials(self, credentials: Credentials) -> None:
        """
        Write credentials as JSON, atomically: to a temporary file that replaces the old one,
        so a crash half-way cannot leave a corrupt file. On Linux/macOS the file is created
        owner-only (0600); on Windows it inherits the folder's permissions.
        """
        payload = credentials.to_json()
        temp_path = self.credentials_file.with_name(self.credentials_file.name + '.tmp')
        try:
            descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
                handle.write(payload)
            os.replace(temp_path, self.credentials_file)
        except OSError as error:
            temp_path.unlink(missing_ok=True)
            app_logger.error(f"Could not save YouTube credentials ({type(error).__name__})")
            raise YouTubeUploaderError("Could not save YouTube credentials") from error
        except BaseException:
            temp_path.unlink(missing_ok=True)
            raise

    # -- upload -------------------------------------------------------------

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str = "",
        tags: Optional[list] = None,
        category_id: str = "22",  # People & Blogs
        privacy_status: str = "private",
        is_short: bool = True,
    ) -> Tuple[bool, str, Optional[str]]:
        """
        Upload a video to the authenticated channel.

        Returns:
            (success, message, video_id)
        """
        if privacy_status not in PRIVACY_STATUSES:
            return False, f"Privacy must be one of: {', '.join(PRIVACY_STATUSES)}", None

        if not self.youtube_service and not self.is_authenticated():
            return False, "Authentication required. Please sign in to YouTube first.", None

        if not os.path.exists(video_path):
            return False, "Video file not found", None

        title = (title or '').strip()[:TITLE_LIMIT] or DEFAULT_TITLE
        description = description or ''
        if is_short and SHORTS_TAG not in description:
            # Truncate the text, not the tag: the tag is what marks the video as a Short
            suffix = f"\n\n{SHORTS_TAG}"
            description = (description[:DESCRIPTION_LIMIT - len(suffix)] + suffix).strip()

        body = {
            "snippet": {
                "title": title,
                "description": description[:DESCRIPTION_LIMIT],
                "tags": normalize_tags(tags),
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = None
        try:
            media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/*")
            insert_request = self.youtube_service.videos().insert(
                part=",".join(body.keys()), body=body, media_body=media)
            video_id = self._resumable_upload(insert_request)
        except HttpError as error:
            message = self._describe_http_error(error)
            app_logger.error(message)
            return False, message, None
        except Exception as error:  # the upload library raises many types
            app_logger.error(f"Upload failed ({type(error).__name__})")
            return False, "Upload failed. See the application log for details.", None
        finally:
            # MediaFileUpload only closes its file in __del__; on Windows an open
            # handle blocks deleting the video afterwards.
            if media is not None:
                media.stream().close()

        if not video_id:
            return False, "Upload failed - no video ID returned", None

        app_logger.info(f"Video uploaded successfully: https://www.youtube.com/watch?v={video_id}")
        return True, "Video uploaded successfully", video_id

    @staticmethod
    def _describe_http_error(error: HttpError) -> str:
        status = getattr(error.resp, 'status', 'unknown')
        try:
            detail = json.loads(error.content.decode('utf-8'))['error']['message']
        except (ValueError, KeyError, TypeError, AttributeError):
            detail = "request failed"
        return f"YouTube API error ({status}): {detail}"

    def _resumable_upload(self, insert_request) -> Optional[str]:
        """Run a resumable upload, retrying server errors with jittered backoff."""
        retry = 0
        while True:
            try:
                _, response = insert_request.next_chunk()
            except HttpError as error:
                if error.resp.status not in UPLOAD_RETRYABLE_STATUSES:
                    raise
                retry += 1
                if retry > UPLOAD_MAX_RETRIES:
                    app_logger.error("Upload failed after the maximum number of retries")
                    return None
                self._sleep(random.uniform(0, 2 ** retry))
                continue

            if response is None:
                continue
            if 'id' in response:
                return response['id']
            app_logger.error("Upload failed: the API response had no video id")
            return None

    def get_upload_quota_info(self) -> Dict[str, Any]:
        """Quota rules differ per project, so point to the official page instead of guessing."""
        return {
            "note": ("Daily quota and upload limits depend on your Google Cloud project. "
                     "Uploads from API projects that have not passed YouTube's audit are "
                     "locked to private."),
            "docs_url": QUOTA_DOCS_URL,
        }

    def validate_short_video(self, video_path: str) -> Tuple[bool, str]:
        """Check the file against YouTube Shorts requirements (<=60s, vertical or square)."""
        import cv2

        capture = cv2.VideoCapture(str(video_path))
        try:
            if not capture.isOpened():
                return False, "Cannot open video file"
            fps = capture.get(cv2.CAP_PROP_FPS)
            frame_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
            width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        finally:
            capture.release()

        duration = frame_count / fps if fps > 0 else 0
        if duration > self.SHORTS_MAX_DURATION:
            return False, f"Video too long: {duration:.1f}s (max {self.SHORTS_MAX_DURATION}s)"

        aspect_ratio = width / height if height > 0 else 0
        is_vertical = height > width
        is_square = abs(aspect_ratio - 1.0) < 0.1
        if not (is_vertical or is_square):
            return False, f"Invalid aspect ratio: {aspect_ratio:.2f} (should be vertical or square)"

        file_size = os.path.getsize(video_path)
        if file_size > self.SHORTS_MAX_FILE_BYTES:
            return False, f"File too large: {file_size / (1024 * 1024):.1f}MB (max 2GB)"

        return True, f"Valid YouTube Short: {duration:.1f}s, {width}x{height}"


# Global uploader instance
youtube_uploader = YouTubeUploader()
