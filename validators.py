"""
Input validation and security utilities for Video Frame Extractor
Provides comprehensive input validation, sanitization, and security checks
"""
import re
import urllib.parse as urlparse
from typing import List, Tuple, Optional
import hashlib
from pathlib import Path

from config import get_config
from logger import app_logger

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

# Hosts owned by each platform. A URL host must equal one of these or be a
# subdomain of it; substring matching would accept "youtube.com.evil.com".
PLATFORM_HOSTS = {
    'youtube': ('youtube.com', 'youtu.be'),
    'tiktok': ('tiktok.com',),
    'instagram': ('instagram.com',),
    'facebook': ('facebook.com', 'fb.com', 'fb.watch'),
    'douyin': ('douyin.com',),
}

# Windows device names cannot be used as file names.
WINDOWS_RESERVED_NAMES = frozenset(
    ['CON', 'PRN', 'AUX', 'NUL']
    + [f'COM{i}' for i in range(1, 10)]
    + [f'LPT{i}' for i in range(1, 10)]
)

MAX_TIMESTAMPS = 50
MAX_FILENAME_LENGTH = 100
# Real share links are far shorter; the cap keeps regex work on user input bounded.
MAX_URL_LENGTH = 2048
VIDEO_ID_PATTERN = re.compile(r'[\w-]{1,64}')
DOUYIN_ID_PATTERN = re.compile(r'\d{6,25}')
DOUYIN_VIDEO_PATH = re.compile(r'/video/(\d+)')
DOUYIN_SHARE_PATH = re.compile(r'/share/video/(\d+)')

# Seconds/minutes are bounded to 00-59 so "1:60" is rejected, not read as 120s.
TIMESTAMP_PATTERNS = (
    (re.compile(r'\d{1,6}'), lambda m: int(m.group(0))),
    (re.compile(r'(\d{1,3}):([0-5]\d)'),
     lambda m: int(m.group(1)) * 60 + int(m.group(2))),
    (re.compile(r'(\d{1,2}):([0-5]\d):([0-5]\d)'),
     lambda m: int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))),
)


def _host_matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith('.' + domain)


# Characters that make a "file name" something else: path separators, drive or
# stream markers (C:, name.mp4:stream) and control characters.
_UNSAFE_FILENAME_CHARS = re.compile(r'[/\\:\x00-\x1f\x7f]')


def resolve_in_folder(folder: Path, filename: str, extensions: Tuple[str, ...]) -> Optional[Path]:
    """
    Resolve a client-supplied file name to an existing file directly inside
    `folder`, or return None. Rejects separators, traversal, drive/stream
    markers, other extensions, directories and symlinks that leave the folder.
    """
    if not isinstance(filename, str) or filename in ('', '.', '..'):
        return None
    if _UNSAFE_FILENAME_CHARS.search(filename):
        return None

    base = Path(folder).resolve()
    candidate = (base / filename).resolve()
    if candidate.parent != base:
        return None
    if candidate.suffix.lower() not in extensions or not candidate.is_file():
        return None
    return candidate


class SecurityValidator:
    """Comprehensive input validation and security checks"""

    def __init__(self):
        self.config = get_config()

        # URL path shapes per platform. The host is checked separately and
        # exactly (see PLATFORM_HOSTS); these only confirm a video link shape.
        self.url_patterns = {
            'youtube': [
                r'https?://(www\.|m\.)?youtube\.com/watch\?(?:[^#\s]*&)?v=[\w-]+',
                r'https?://(www\.|m\.)?youtube\.com/(?:shorts|live|embed)/[\w-]+',
                r'https?://youtu\.be/[\w-]+',
            ],
            'tiktok': [
                r'https?://(www\.)?tiktok\.com/@[\w.-]+/video/\d+',
                r'https?://(www\.)?tiktok\.com/t/[\w-]+',
                r'https?://v[mt]\.tiktok\.com/[\w-]+',
                r'https?://m\.tiktok\.com/v/\d+',
            ],
            'instagram': [
                r'https?://(www\.)?instagram\.com/(?:p|reels?|tv)/[\w-]+',
            ],
            'facebook': [
                r'https?://(www\.|m\.|web\.)?facebook\.com/[\w.-]+/videos/\d+',
                r'https?://(www\.|m\.|web\.)?facebook\.com/watch/?\?(?:[^#\s]*&)?v=\d+',
                r'https?://(www\.|m\.|web\.)?facebook\.com/reel/\d+',
                r'https?://(www\.)?fb\.com/[\w.-]+/videos/\d+',
                r'https?://fb\.watch/[\w-]+',
            ],
            'douyin': [
                r'https?://(www\.)?douyin\.com/video/\d+',
                # A video opened from a feed, search or profile page: ...?modal_id=<id>
                r'https?://(www\.)?douyin\.com/[^?#]*\?([^#]*&)?modal_id=\d+',
                # Share links; resolved by link_resolver to douyin.com/video/<id>
                r'https?://v\.douyin\.com/[\w-]+/?',
            ],
        }
        
    def validate_url(self, url: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate URL format and detect platform
        
        Returns:
            (is_valid, platform, error_message)
        """
        if not url or not isinstance(url, str):
            return False, 'unknown', "URL is required and must be a string"
        
        url = url.strip()
        if len(url) > MAX_URL_LENGTH:
            return False, 'unknown', "URL is too long"

        # Basic URL format validation
        try:
            parsed = urlparse.urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                return False, 'unknown', "Invalid URL format"

            if parsed.scheme not in ['http', 'https']:
                return False, 'unknown', "URL must use HTTP or HTTPS"

            # Credentials or an explicit port have no place in a share link and
            # are used to disguise the real host ("youtube.com@evil.com").
            if parsed.username is not None or parsed.password is not None:
                return False, 'unknown', "URLs containing credentials are not allowed"
            if parsed.port is not None:
                return False, 'unknown', "URLs with an explicit port are not allowed"
            domain = (parsed.hostname or '').lower()
        except ValueError:
            return False, 'unknown', "Invalid URL format"

        # Check if URL is from supported platforms
        platform = self._detect_platform(domain)
        
        if platform == 'unknown':
            supported = ', '.join(self.config.SUPPORTED_PLATFORMS)
            return False, 'unknown', f"Unsupported platform. Supported: {supported}"
        
        # Platform-specific validation
        is_valid, error = self._validate_platform_url(url, platform)
        if not is_valid:
            return False, platform, error
        
        return True, platform, None
    
    def _detect_platform(self, host: str) -> str:
        """Detect platform from a bare hostname (exact or subdomain match)"""
        host = (host or '').lower().rstrip('.')
        for platform, domains in PLATFORM_HOSTS.items():
            if any(_host_matches(host, d) for d in domains):
                return platform
        return 'unknown'
    
    def _validate_platform_url(self, url: str, platform: str) -> Tuple[bool, Optional[str]]:
        """Validate URL against platform-specific patterns"""
        patterns = self.url_patterns.get(platform, [])
        
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True, None
        
        return False, f"Invalid {platform} URL format"
    
    def canonicalize_url(self, url: str) -> str:
        """
        Reduce a YouTube link to its single-video form, https://www.youtube.com/watch?v=<id>.

        Links copied from a playlist or mix carry list= / index= / start_radio=;
        yt-dlp routes those to its playlist extractor, which is not allowed here,
        so they would fail with a misleading "No suitable extractor". Other links
        are returned unchanged.
        """
        douyin = self.canonicalize_douyin_url(url)
        if douyin != url:
            return douyin
        try:
            parsed = urlparse.urlparse(url)
            host = (parsed.hostname or '').lower()
            if host == 'youtu.be':
                video_id = parsed.path.strip('/')
            elif _host_matches(host, 'youtube.com') and parsed.path == '/watch':
                video_id = (urlparse.parse_qs(parsed.query).get('v') or [''])[0]
            else:
                return url
        except ValueError:
            return url

        if not VIDEO_ID_PATTERN.fullmatch(video_id):
            return url
        return f'https://www.youtube.com/watch?v={video_id}'

    @staticmethod
    def canonicalize_douyin_url(url: str) -> str:
        """
        A Douyin video as https://www.douyin.com/video/<id>, the only form yt-dlp reads.
        Covers ...?modal_id=<id> on any douyin.com page and the iesdouyin.com share pages that
        v.douyin.com links redirect to (rewritten here, never requested). Other links unchanged.
        """
        try:
            parsed = urlparse.urlparse(url)
        except ValueError:
            return url
        host = (parsed.hostname or '').lower()
        if _host_matches(host, 'douyin.com'):
            video_id = (urlparse.parse_qs(parsed.query).get('modal_id') or [''])[0]
            match = DOUYIN_VIDEO_PATH.fullmatch(parsed.path.rstrip('/'))
            video_id = video_id or (match.group(1) if match else '')
        elif _host_matches(host, 'iesdouyin.com'):
            match = DOUYIN_SHARE_PATH.match(parsed.path)
            video_id = match.group(1) if match else ''
        else:
            return url
        return f'https://www.douyin.com/video/{video_id}' if DOUYIN_ID_PATTERN.fullmatch(video_id) else url

    def validate_timestamp(self, timestamp: str) -> Tuple[bool, Optional[str], Optional[int]]:
        """
        Validate timestamp format and convert to seconds
        
        Supported formats: 30, 1:23, 1:23:45
        
        Returns:
            (is_valid, error_message, seconds)
        """
        if not timestamp or not isinstance(timestamp, str):
            return False, "Timestamp is required and must be a string", None
        
        timestamp = timestamp.strip()

        for pattern, converter in TIMESTAMP_PATTERNS:
            match = pattern.fullmatch(timestamp)
            if match:
                seconds = converter(match)
                if seconds > self.config.MAX_VIDEO_DURATION:
                    return False, f"Timestamp exceeds maximum duration ({self.config.MAX_VIDEO_DURATION}s)", None
                return True, None, seconds

        return False, "Invalid timestamp format. Use: 30, 1:23, or 1:23:45", None
    
    def validate_timestamps(self, timestamps: List[str]) -> Tuple[bool, List[str], List[int]]:
        """
        Validate multiple timestamps
        
        Returns:
            (all_valid, error_messages, valid_seconds)
        """
        if not timestamps:
            return False, ["At least one timestamp is required"], []
        
        if len(timestamps) > MAX_TIMESTAMPS:
            return False, [f"Too many timestamps (max {MAX_TIMESTAMPS})"], []
        
        errors = []
        valid_seconds = []
        
        for i, timestamp in enumerate(timestamps):
            is_valid, error, seconds = self.validate_timestamp(timestamp)
            if not is_valid:
                errors.append(f"Timestamp {i+1}: {error}")
            else:
                valid_seconds.append(seconds)
        
        return len(errors) == 0, errors, valid_seconds
    
    def sanitize_filename(self, filename: str) -> str:
        """Sanitize filename to prevent path traversal and invalid characters"""
        if not filename:
            return "unknown"
        
        # Remove control characters, then replace dangerous ones
        filename = re.sub(r'[\x00-\x1f\x7f]', '', filename)
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'\.\.+', '.', filename)  # Remove multiple dots
        filename = filename.strip('. ')  # Remove leading/trailing dots and spaces

        # Limit length
        if len(filename) > MAX_FILENAME_LENGTH:
            filename = filename[:MAX_FILENAME_LENGTH]

        # Ensure it's not empty after sanitization
        if not filename:
            filename = "sanitized_file"

        # Windows device names (CON, NUL, COM1...) are unusable, even with an extension
        if filename.split('.')[0].upper() in WINDOWS_RESERVED_NAMES:
            filename = f"_{filename}"

        return filename

    def validate_file_path(self, file_path: str, allowed_extensions: List[str] = None) -> Tuple[bool, str]:
        """
        Validate file path for security
        
        Returns:
            (is_valid, error_message)
        """
        if not file_path:
            return False, "File path is required"
        
        try:
            path = Path(file_path)
            
            # Check for path traversal
            if '..' in str(path):
                return False, "Path traversal not allowed"
            
            # Check if path is within allowed directories
            base_dir = self.config.BASE_DIR
            try:
                path.resolve().relative_to(base_dir.resolve())
            except ValueError:
                return False, "File path outside allowed directory"
            
            # Check file extension
            if allowed_extensions and path.suffix.lower() not in allowed_extensions:
                return False, f"File extension not allowed. Allowed: {allowed_extensions}"
            
            return True, ""
            
        except (OSError, ValueError):
            return False, "Invalid file path"

    def hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data for logging"""
        return hashlib.sha256(data.encode()).hexdigest()[:8]

    def get_platform_from_url(self, url: str) -> str:
        """Detect platform from URL"""
        try:
            return self._detect_platform(urlparse.urlparse(url).hostname or '')
        except (ValueError, AttributeError):
            return 'unknown'

# Global validator instance
validator = SecurityValidator()
