"""
Enhanced video processing module with improved error handling and performance
"""
import importlib.util
import os
import cv2
import yt_dlp
import uuid
from pathlib import Path
from typing import Optional, Tuple, Dict, List, Any
from datetime import datetime, timedelta

from config import get_config
from link_resolver import resolve_short_url
from logger import video_logger, LogContext
from validators import validator, ValidationError

# Extensions the frame extractor accepts for downloaded videos.
ALLOWED_VIDEO_EXTENSIONS = ('.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.m4v')

# Leftovers of unfinished downloads; never treat these as the finished video.
PARTIAL_DOWNLOAD_SUFFIXES = ('.part', '.ytdl', '.temp', '.tmp')

# yt-dlp extractors (lower-cased IE_NAME) the app may use. The generic
# extractor is deliberately absent, so URLs no platform extractor claims are
# refused instead of being fetched.
YTDLP_ALLOWED_EXTRACTORS = (
    'youtube', 'tiktok', 'vm.tiktok', 'instagram',
    'facebook', 'facebook:reel', 'douyin',
)

MAX_DESCRIPTION_LENGTH = 500
BYTES_PER_MB = 1024 * 1024
# yt-dlp's wording (lower case) when TikTok serves its bot-check page instead of the video page
TIKTOK_BLOCKED_MARKER = 'unexpected response from webpage request'

# Modern sites (YouTube first) serve video and audio as separate streams, with no single
# "best" file, so a selector like best[height<=720] finds nothing. Take video+audio and let
# the sort prefer 720p or below and mp4/m4a (which merge without re-encoding); fall back to a
# single combined file where that is all a site offers.
DOWNLOAD_FORMAT = 'bv*+ba/b'
DOWNLOAD_FORMAT_SORT = ['res:720', 'ext:mp4:m4a']
MERGE_FORMAT = 'mp4'


def bundled_ffmpeg_path() -> Optional[str]:
    """Path of the FFmpeg that ships with MoviePy (imageio-ffmpeg), used to merge streams."""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as error:  # missing package or binary: fall back to ffmpeg on PATH
        video_logger.warning(f"Bundled FFmpeg not available ({type(error).__name__})")
        return None


def find_downloaded_file(folder: Path, unique_id: str) -> Optional[Path]:
    """Return the newest finished download whose name carries `unique_id`."""
    candidates = [
        path for path in Path(folder).iterdir()
        if path.is_file()
        and unique_id in path.name
        and not path.name.endswith(PARTIAL_DOWNLOAD_SUFFIXES)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


EXTRACT_FAILED_MESSAGE = (
    "Could not extract video information "
    "(the video may be unavailable, live, or longer than the configured limit)")
NOT_DOWNLOADED_MESSAGE = "The video was not downloaded (it may exceed the size or duration limit)"


def remove_partial_downloads(folder: Path, unique_id: str) -> None:
    """Delete everything a (failed) download left behind under its random id."""
    for path in Path(folder).glob(f'*{unique_id}*'):
        try:
            path.unlink(missing_ok=True)
        except OSError as error:
            video_logger.warning(f"Could not remove partial download ({type(error).__name__})")


def download_with_ytdlp(url: str, opts: Dict[str, Any],
                        folder: Path) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Download `url` into `folder` with yt-dlp in a single pass.

    The file is named after a random id only. yt-dlp expands $VAR and
    %(field)s inside the output template, so remote text (the video title)
    must never be part of it; the title is returned separately for display.

    Returns:
        (file_path, sanitized_title, error_message)
    """
    folder = Path(folder)
    unique_id = uuid.uuid4().hex[:8]
    options = dict(opts)
    options['paths'] = {'home': str(folder)}
    options['outtmpl'] = {'default': f'{unique_id}.%(ext)s'}

    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=True)
    except BaseException:
        remove_partial_downloads(folder, unique_id)
        raise

    if not isinstance(info, dict) or not info:
        remove_partial_downloads(folder, unique_id)
        return None, None, EXTRACT_FAILED_MESSAGE

    finished = find_downloaded_file(folder, unique_id)
    if finished is None:  # skipped by the duration/size filter, or only partial files exist
        remove_partial_downloads(folder, unique_id)
        return None, None, NOT_DOWNLOADED_MESSAGE
    return str(finished), validator.sanitize_filename(info.get('title') or 'unknown'), None


def make_size_limit_hook(limit_bytes: int):
    """
    yt-dlp progress hook that aborts a download once it passes `limit_bytes`.

    The max_filesize option only applies when the server announces a size in
    advance; HLS/DASH streams and chunked responses report none, so they need this.
    """
    def hook(status: Dict[str, Any]) -> None:
        downloaded = status.get('downloaded_bytes') or 0
        if downloaded > limit_bytes:
            raise yt_dlp.utils.DownloadError(
                f"The download is larger than the {limit_bytes // BYTES_PER_MB} MB limit")
    return hook


def browser_impersonation_available() -> bool:
    """
    True when yt-dlp can imitate a real browser's connection, which needs the curl_cffi
    package (the "curl-cffi" extra in pyproject.toml). TikTok answers plain Python clients
    with a bot-check page, so without it every TikTok download fails.
    """
    return importlib.util.find_spec('curl_cffi') is not None


class PlatformProcessor:
    """Base class for platform-specific video processing"""

    def __init__(self, platform: str):
        self.platform = platform
        self.config = get_config()
        self.base_opts = self._get_base_options()

    def _get_base_options(self) -> Dict[str, Any]:
        """Get base yt-dlp options, including the safety limits for untrusted input"""
        max_duration = self.config.MAX_VIDEO_DURATION
        options = {
            'format': DOWNLOAD_FORMAT,
            'format_sort': list(DOWNLOAD_FORMAT_SORT),
            'merge_output_format': MERGE_FORMAT,
            'outtmpl': {'default': f'{self.config.DOWNLOAD_FOLDER}/%(title)s_%(id)s.%(ext)s'},
            'noplaylist': True,
            'ignoreerrors': False,
            'no_warnings': False,
            'extractaudio': False,
            'writeinfojson': False,
            'writedescription': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
            'writethumbnail': False,
            # Limits for untrusted URLs
            'max_filesize': self.config.MAX_DOWNLOAD_MB * BYTES_PER_MB,
            'progress_hooks': [make_size_limit_hook(self.config.MAX_DOWNLOAD_MB * BYTES_PER_MB)],
            'socket_timeout': self.config.SOCKET_TIMEOUT,
            'retries': self.config.DOWNLOAD_RETRIES,
            'match_filter': yt_dlp.utils.match_filter_func(
                f'duration <=? {max_duration} & !is_live'),
            'cachedir': False,
            'allowed_extractors': list(YTDLP_ALLOWED_EXTRACTORS),
        }
        ffmpeg = bundled_ffmpeg_path()
        if ffmpeg:
            options['ffmpeg_location'] = ffmpeg
        return options

    def get_download_options(self, url: str) -> Dict[str, Any]:
        """Get platform-specific download options - override in subclasses"""
        return self.base_opts.copy()
    
    def process_download_error(self, error: str) -> str:
        """Process platform-specific errors - override in subclasses"""
        return f"{self.platform.title()} Error: {error}"

class YouTubeProcessor(PlatformProcessor):
    """YouTube-specific processing"""
    
    def __init__(self):
        super().__init__('youtube')

class TikTokProcessor(PlatformProcessor):
    """TikTok-specific processing"""
    
    def __init__(self):
        super().__init__('tiktok')

    def process_download_error(self, error: str) -> str:
        if TIKTOK_BLOCKED_MARKER in error.lower():
            if not browser_impersonation_available():
                return ("TikTok Error: TikTok did not send the video page because it refuses plain "
                        "Python requests. Run `uv sync` to install the browser-impersonation "
                        "package (curl-cffi), then restart the app.")
            return ("TikTok Error: TikTok did not send the video page. It sometimes blocks "
                    "automated requests for a while. Try again in a few minutes, or use the "
                    "vm.tiktok.com share link.")
        if 'format' in error.lower():
            return (
                f"TikTok Error: {error}\n\n"
                "🎵 TikTok Troubleshooting:\n"
                "• This TikTok video may be region-blocked\n"
                "• Try using the vm.tiktok.com share link instead\n"
                "• Some TikTok videos have download restrictions"
            )
        return super().process_download_error(error)

class InstagramProcessor(PlatformProcessor):
    """Instagram-specific processing with cookie support"""
    
    def __init__(self):
        super().__init__('instagram')
        self.cookie_sources = self.config.COOKIE_BROWSERS

    def try_with_cookies(self, url: str, base_opts: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Try download with various cookie sources"""
        # Try manual cookie file first
        if self.config.COOKIE_FILE_PATH.exists():
            video_logger.info("Trying manual cookie file", platform=self.platform)
            try:
                opts = base_opts.copy()
                opts['cookiefile'] = str(self.config.COOKIE_FILE_PATH)
                result = self._attempt_download(url, opts)
                if result[0]:
                    video_logger.info("Success with manual cookie file!", platform=self.platform)
                    return result
            except Exception as e:
                video_logger.warning(f"Manual cookie failed: {str(e)}", platform=self.platform)
        
        # Browser cookies expose the whole local profile, so they are opt-in
        if self.config.USE_BROWSER_COOKIES:
            for browser in self.cookie_sources:
                video_logger.info(f"Trying {browser} cookies", platform=self.platform)
                try:
                    opts = base_opts.copy()
                    opts['cookiesfrombrowser'] = (browser,)
                    result = self._attempt_download(url, opts)
                    if result[0]:
                        video_logger.info(f"Success with {browser} cookies!", platform=self.platform)
                        return result
                except Exception as e:
                    video_logger.warning(f"{browser} cookies failed: {str(e)}", platform=self.platform)

        # Try without cookies
        video_logger.info("Trying without cookies", platform=self.platform)
        return self._attempt_download(url, base_opts)

    def _attempt_download(self, url: str, opts: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        """Attempt download with given options; returns (path, title) or (None, error)"""
        path, title, error = download_with_ytdlp(url, opts, self.config.DOWNLOAD_FOLDER)
        if path:
            return path, title
        return None, error
    
    def process_download_error(self, error: str) -> str:
        if 'Restricted Video' in error or 'cookies' in error:
            return (
                f"Instagram Error: {error}\n\n"
                "📸 Instagram Troubleshooting:\n"
                "• This video may be age-restricted or private\n"
                "• Try logging into Instagram in your browser first\n"
                "• Public posts usually work better than private/restricted content\n"
                "• Consider using the Instagram mobile app link instead\n\n"
                "💡 Cookie Authentication Failed:\n"
                "• Export Instagram cookies from your browser\n"
                "• Save as 'instagram_cookies.txt' in the app directory\n"
                "• Use browser extensions like 'Export Cookies'"
            )
        return super().process_download_error(error)

class FacebookProcessor(PlatformProcessor):
    """Facebook-specific processing"""
    
    def __init__(self):
        super().__init__('facebook')

    def process_download_error(self, error: str) -> str:
        if 'login' in error.lower() or 'private' in error.lower():
            return (
                f"Facebook Error: {error}\n\n"
                "📘 Facebook Troubleshooting:\n"
                "• This video may be private or require login\n"
                "• Only public Facebook videos can be downloaded\n"
                "• Make sure the video is accessible without logging in"
            )
        return super().process_download_error(error)

class DouyinProcessor(PlatformProcessor):
    """Douyin-specific processing"""
    
    def __init__(self):
        super().__init__('douyin')

class EnhancedVideoFrameExtractor:
    """Enhanced video processing with improved error handling and modular design"""
    
    def __init__(self):
        self.config = get_config()
        self.processors = {
            'youtube': YouTubeProcessor(),
            'tiktok': TikTokProcessor(),
            'instagram': InstagramProcessor(),
            'facebook': FacebookProcessor(),
            'douyin': DouyinProcessor()
        }
    
    def validate_and_process_url(self, url: str) -> Tuple[bool, str, Optional[str]]:
        """Validate URL and detect platform"""
        with LogContext(video_logger, "URL validation", url=validator.hash_sensitive_data(url)):
            try:
                is_valid, platform, error = validator.validate_url(url)
                if not is_valid:
                    raise ValidationError(error)
                
                return True, platform, None
                
            except ValidationError as e:
                video_logger.warning(f"URL validation failed: {str(e)}", url=validator.hash_sensitive_data(url))
                return False, 'unknown', str(e)
    
    def download_video(self, url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """
        Download video and return path, title, and any error
        
        Returns:
            (file_path, title, error_message)
        """
        start_time = datetime.now()
        
        with LogContext(video_logger, "Video download", url=validator.hash_sensitive_data(url)):
            try:
                # Validate URL first
                is_valid, platform, error = self.validate_and_process_url(url)
                if not is_valid:
                    return None, None, error

                url, link_error = resolve_short_url(url)
                if link_error:
                    return None, None, link_error
                url = validator.canonicalize_url(url)

                processor = self.processors.get(platform)
                if not processor:
                    error = f"No processor available for platform: {platform}"
                    video_logger.error(error, platform=platform)
                    return None, None, error
                
                # Special handling for Instagram
                if platform == 'instagram':
                    return self._download_instagram_video(url, processor)
                
                # Standard download process
                return self._download_standard_video(url, processor)
                
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                platform = self.get_platform_from_url(url)
                processor = self.processors.get(platform)
                
                if processor:
                    enhanced_error = processor.process_download_error(error_msg)
                else:
                    enhanced_error = error_msg
                
                duration = (datetime.now() - start_time).total_seconds() * 1000
                video_logger.log_video_processing(
                    platform, url, 'download', 'failed', 
                    duration_ms=duration, error=enhanced_error
                )
                return None, None, enhanced_error
                
            except Exception as e:
                # The details (paths, OS errors) go to the log, not to the browser
                video_logger.exception("Video download failed",
                                     url=validator.hash_sensitive_data(url),
                                     error=str(e))
                return None, None, "Unexpected error during download. See the application log."
    
    def _download_standard_video(self, url: str, processor: PlatformProcessor) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Download video using standard process"""
        opts = processor.get_download_options(url)
        file_path, title, error = download_with_ytdlp(url, opts, self.config.DOWNLOAD_FOLDER)
        if file_path:
            video_logger.log_video_processing(processor.platform, url, 'download', 'success')
        return file_path, title, error
    
    def _download_instagram_video(self, url: str, processor: InstagramProcessor) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Download Instagram video with cookie fallback"""
        base_opts = processor.get_download_options(url)
        
        try:
            file_path, title = processor.try_with_cookies(url, base_opts)
            if file_path:
                return file_path, title, None
            else:
                return None, None, title or "Instagram download failed with all methods"
        except yt_dlp.utils.DownloadError as e:
            return None, None, processor.process_download_error(str(e))
        except Exception as e:
            video_logger.exception("Instagram download failed", error=str(e))
            return None, None, "Unexpected error during download. See the application log."
    
    def get_platform_from_url(self, url: str) -> str:
        """Get platform from URL"""
        _, platform, _ = validator.validate_url(url)
        return platform
    
    def extract_frame_at_timestamp(self, video_path: str, timestamp: int, output_path: str) -> Tuple[bool, Optional[str]]:
        """
        Extract frame at specific timestamp
        
        Returns:
            (success, error_message)
        """
        with LogContext(video_logger, "Frame extraction", 
                       video_path=os.path.basename(video_path), 
                       timestamp=timestamp):
            try:
                # Validate inputs
                is_valid_path, path_error = validator.validate_file_path(
                    video_path, list(ALLOWED_VIDEO_EXTENSIONS))
                if not is_valid_path:
                    return False, path_error
                
                # Messages reach the browser, so they never include server paths
                if not os.path.exists(video_path):
                    return False, "Video file not found"

                # Use OpenCV for frame extraction (more reliable than moviepy for single frames)
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    return False, "Could not open the video file"
                
                # Set video position to timestamp (in milliseconds)
                cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
                
                # Read frame
                ret, frame = cap.read()
                cap.release()
                
                if not ret:
                    return False, f"Could not extract frame at timestamp {timestamp}s"
                
                # Save frame
                success = cv2.imwrite(output_path, frame)
                if not success:
                    return False, "Could not save the extracted frame"
                
                video_logger.info("Frame extracted successfully", 
                                timestamp=timestamp, 
                                output_path=os.path.basename(output_path))
                return True, None
                
            except (cv2.error, OSError, ValueError) as e:
                video_logger.exception("Frame extraction failed",
                                     timestamp=timestamp,
                                     error=str(e))
                return False, "Frame extraction failed"
    
    def get_video_info(self, url: str) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Get video information without downloading
        
        Returns:
            (success, video_info, error_message)
        """
        with LogContext(video_logger, "Video info extraction", url=validator.hash_sensitive_data(url)):
            try:
                # Validate URL
                is_valid, platform, error = self.validate_and_process_url(url)
                if not is_valid:
                    return False, None, error

                url, link_error = resolve_short_url(url)
                if link_error:
                    return False, None, link_error
                url = validator.canonicalize_url(url)

                processor = self.processors.get(platform)
                if not processor:
                    return False, None, f"No processor available for platform: {platform}"

                opts = processor.get_download_options(url)
                opts['quiet'] = True
                # Showing details of a long video is harmless; only downloads are limited,
                # and a title does not depend on which formats are available
                opts.pop('match_filter', None)
                opts['ignore_no_formats_error'] = True

                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)

                    if not isinstance(info, dict) or not info:
                        return False, None, EXTRACT_FAILED_MESSAGE
                    
                    # Extract relevant information
                    video_info = {
                        'title': info.get('title', 'Unknown'),
                        'duration': info.get('duration'),
                        'view_count': info.get('view_count'),
                        'uploader': info.get('uploader'),
                        'upload_date': info.get('upload_date'),
                        # description is often present but None (TikTok, Instagram, Facebook)
                        'description': (info.get('description') or '')[:MAX_DESCRIPTION_LENGTH],
                        'thumbnail': info.get('thumbnail'),
                        'platform': platform
                    }
                    
                    video_logger.info("Video info extracted successfully", 
                                    platform=platform, 
                                    title=video_info['title'])
                    return True, video_info, None
                    
            except yt_dlp.utils.DownloadError as e:
                error_msg = str(e)
                processor = self.processors.get(platform)
                if processor:
                    error_msg = processor.process_download_error(error_msg)
                return False, None, error_msg
                
            except Exception as e:
                video_logger.exception("Video info extraction failed", 
                                     url=validator.hash_sensitive_data(url), 
                                     error=str(e))
                return False, None, "Could not read the video information. See the application log."
    
    def cleanup_old_files(self, max_age_hours: int = None) -> Tuple[int, int, List[str]]:
        """
        Clean up old downloaded files and frames
        
        Returns:
            (files_deleted, space_freed_mb, errors)
        """
        if max_age_hours is None:
            max_age_hours = self.config.AUTO_CLEANUP_HOURS
        
        with LogContext(video_logger, "File cleanup", max_age_hours=max_age_hours):
            files_deleted = 0
            space_freed = 0
            errors = []
            
            cutoff_time = datetime.now() - timedelta(hours=max_age_hours)
            
            # Clean download and frame folders
            folders_to_clean = [
                self.config.DOWNLOAD_FOLDER,
                self.config.FRAMES_FOLDER,
                self.config.SHORTS_FOLDER
            ]
            
            for folder in folders_to_clean:
                try:
                    if not folder.exists():
                        continue

                    for file_path in folder.iterdir():
                        # stat() and unlink() share one try: another request may
                        # delete the file between listing and here
                        try:
                            if not file_path.is_file():
                                continue
                            file_stat = file_path.stat()
                            if datetime.fromtimestamp(file_stat.st_mtime) >= cutoff_time:
                                continue
                            file_path.unlink()
                            files_deleted += 1
                            space_freed += file_stat.st_size
                            video_logger.debug(f"Deleted old file: {file_path.name}")
                        except FileNotFoundError:
                            continue  # already gone
                        except OSError as e:
                            # Messages reach the browser: file name only, details go to the log
                            errors.append(f"Could not delete {file_path.name}")
                            video_logger.warning(f"Could not delete {file_path.name} ({type(e).__name__})")

                except OSError as e:
                    errors.append(f"Could not clean the {folder.name} folder")
                    video_logger.warning(f"Could not clean {folder.name} ({type(e).__name__})")
            
            space_freed_mb = space_freed / (1024 * 1024)  # Convert to MB
            video_logger.info("Cleanup completed", 
                            files_deleted=files_deleted, 
                            space_freed_mb=round(space_freed_mb, 2))
            
            return files_deleted, int(space_freed_mb), errors

# Global extractor instance
extractor = EnhancedVideoFrameExtractor()
