"""
Enhanced video processing module with improved error handling and performance
"""
import os
import cv2
import yt_dlp
import uuid
from typing import Optional, Tuple, Dict, List, Any
from datetime import datetime, timedelta

from config import get_config
from logger import video_logger, LogContext
from validators import validator, ValidationError

class VideoProcessingError(Exception):
    """Custom exception for video processing errors"""
    pass

class PlatformProcessor:
    """Base class for platform-specific video processing"""
    
    def __init__(self, platform: str):
        self.platform = platform
        self.config = get_config()
        self.base_opts = self._get_base_options()
    
    def _get_base_options(self) -> Dict[str, Any]:
        """Get base yt-dlp options"""
        return {
            'format': f'best[height<={self.config.DEFAULT_VIDEO_QUALITY}]',
            'outtmpl': {'default': f'{self.config.DOWNLOAD_FOLDER}/%(title)s_%(id)s.%(ext)s'},
            'noplaylist': True,
            'ignoreerrors': False,
            'no_warnings': False,
            'extractaudio': False,
            'writeinfojson': False,
            'writedescription': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }
    
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
    
    def get_download_options(self, url: str) -> Dict[str, Any]:
        opts = self.base_opts.copy()
        opts['format'] = 'best[height<=720]/best'
        return opts

class TikTokProcessor(PlatformProcessor):
    """TikTok-specific processing"""
    
    def __init__(self):
        super().__init__('tiktok')
    
    def get_download_options(self, url: str) -> Dict[str, Any]:
        opts = self.base_opts.copy()
        opts['format'] = 'best/h264_540p_468478/h264_540p_287260/bytevc1_540p_248040/download'
        return opts
    
    def process_download_error(self, error: str) -> str:
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
    
    def get_download_options(self, url: str) -> Dict[str, Any]:
        opts = self.base_opts.copy()
        opts['format'] = 'best[height<=720]/mp4/best'
        return opts
    
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
        
        # Try browser cookies
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
        """Attempt download with given options"""
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict) or not info:
                return None, "Could not extract video information"
            
            title = validator.sanitize_filename(info.get('title', 'unknown'))
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{title}_{unique_id}.%(ext)s"
            opts['outtmpl'] = {'default': f'{self.config.DOWNLOAD_FOLDER}/{filename}'}
            
            ydl.download([url])
            
            # Find downloaded file
            for file in os.listdir(self.config.DOWNLOAD_FOLDER):
                if unique_id in file:
                    return os.path.join(self.config.DOWNLOAD_FOLDER, file), title
            
            return None, "Downloaded file not found"
    
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
    
    def get_download_options(self, url: str) -> Dict[str, Any]:
        opts = self.base_opts.copy()
        opts['format'] = 'best[height<=720]/best'
        return opts
    
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
    
    def get_download_options(self, url: str) -> Dict[str, Any]:
        opts = self.base_opts.copy()
        opts['format'] = 'best/mp4'
        return opts

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
                error_msg = f"Unexpected error during download: {str(e)}"
                video_logger.exception("Video download failed", 
                                     url=validator.hash_sensitive_data(url), 
                                     error=str(e))
                return None, None, error_msg
    
    def _download_standard_video(self, url: str, processor: PlatformProcessor) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Download video using standard process"""
        opts = processor.get_download_options(url)
        
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Extract info
            info = ydl.extract_info(url, download=False)
            if not isinstance(info, dict) or not info:
                return None, None, "Could not extract video information"
            
            title = validator.sanitize_filename(info.get('title', 'unknown'))
            unique_id = str(uuid.uuid4())[:8]
            filename = f"{title}_{unique_id}.%(ext)s"
            opts['outtmpl'] = {'default': f'{self.config.DOWNLOAD_FOLDER}/{filename}'}
            
            # Download
            ydl.download([url])
            
            # Find downloaded file
            for file in os.listdir(self.config.DOWNLOAD_FOLDER):
                if unique_id in file:
                    file_path = os.path.join(self.config.DOWNLOAD_FOLDER, file)
                    video_logger.log_video_processing(
                        processor.platform, url, 'download', 'success'
                    )
                    return file_path, title, None
            
            return None, None, "Downloaded file not found"
    
    def _download_instagram_video(self, url: str, processor: InstagramProcessor) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        """Download Instagram video with cookie fallback"""
        base_opts = processor.get_download_options(url)
        
        try:
            file_path, title = processor.try_with_cookies(url, base_opts)
            if file_path:
                return file_path, title, None
            else:
                return None, None, title or "Instagram download failed with all methods"
        except Exception as e:
            enhanced_error = processor.process_download_error(str(e))
            return None, None, enhanced_error
    
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
                is_valid_path, path_error = validator.validate_file_path(video_path, ['.mp4', '.avi', '.mov', '.mkv'])
                if not is_valid_path:
                    return False, path_error
                
                if not os.path.exists(video_path):
                    return False, f"Video file not found: {video_path}"
                
                # Use OpenCV for frame extraction (more reliable than moviepy for single frames)
                cap = cv2.VideoCapture(video_path)
                if not cap.isOpened():
                    return False, f"Could not open video file: {video_path}"
                
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
                    return False, f"Could not save frame to {output_path}"
                
                video_logger.info("Frame extracted successfully", 
                                timestamp=timestamp, 
                                output_path=os.path.basename(output_path))
                return True, None
                
            except Exception as e:
                video_logger.exception("Frame extraction failed", 
                                     timestamp=timestamp, 
                                     error=str(e))
                return False, f"Frame extraction error: {str(e)}"
    
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
                
                processor = self.processors.get(platform)
                if not processor:
                    return False, None, f"No processor available for platform: {platform}"
                
                opts = processor.get_download_options(url)
                opts['quiet'] = True
                
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    
                    if not isinstance(info, dict) or not info:
                        return False, None, "Could not extract video information"
                    
                    # Extract relevant information
                    video_info = {
                        'title': info.get('title', 'Unknown'),
                        'duration': info.get('duration'),
                        'view_count': info.get('view_count'),
                        'uploader': info.get('uploader'),
                        'upload_date': info.get('upload_date'),
                        'description': info.get('description', '')[:500],  # Truncate long descriptions
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
                return False, None, f"Error extracting video info: {str(e)}"
    
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
                        if file_path.is_file():
                            file_stat = file_path.stat()
                            file_time = datetime.fromtimestamp(file_stat.st_mtime)
                            
                            if file_time < cutoff_time:
                                try:
                                    file_size = file_stat.st_size
                                    file_path.unlink()
                                    files_deleted += 1
                                    space_freed += file_size
                                    video_logger.debug(f"Deleted old file: {file_path.name}")
                                except Exception as e:
                                    error_msg = f"Could not delete {file_path.name}: {str(e)}"
                                    errors.append(error_msg)
                                    video_logger.warning(error_msg)
                                    
                except Exception as e:
                    error_msg = f"Could not clean folder {folder}: {str(e)}"
                    errors.append(error_msg)
                    video_logger.warning(error_msg)
            
            space_freed_mb = space_freed / (1024 * 1024)  # Convert to MB
            video_logger.info("Cleanup completed", 
                            files_deleted=files_deleted, 
                            space_freed_mb=round(space_freed_mb, 2))
            
            return files_deleted, int(space_freed_mb), errors

# Global extractor instance
extractor = EnhancedVideoFrameExtractor()
