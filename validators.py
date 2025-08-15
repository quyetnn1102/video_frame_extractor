"""
Input validation and security utilities for Video Frame Extractor
Provides comprehensive input validation, sanitization, and security checks
"""
import re
import urllib.parse as urlparse
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
import hashlib
from pathlib import Path

from config import get_config
from logger import app_logger

class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass

class SecurityValidator:
    """Comprehensive input validation and security checks"""
    
    def __init__(self):
        self.config = get_config()
        
        # URL validation patterns
        self.url_patterns = {
            'youtube': [
                r'https?://(www\.)?youtube\.com/watch\?v=[\w-]+',
                r'https?://youtu\.be/[\w-]+',
                r'https?://m\.youtube\.com/watch\?v=[\w-]+'
            ],
            'tiktok': [
                r'https?://(www\.)?tiktok\.com/@[\w.-]+/video/\d+',
                r'https?://vm\.tiktok\.com/[\w-]+',
                r'https?://m\.tiktok\.com/v/\d+'
            ],
            'instagram': [
                r'https?://(www\.)?instagram\.com/p/[\w-]+',
                r'https?://(www\.)?instagram\.com/reel/[\w-]+',
                r'https?://(www\.)?instagram\.com/tv/[\w-]+'
            ],
            'facebook': [
                r'https?://(www\.)?facebook\.com/\w+/videos/\d+',
                r'https?://fb\.com/\w+/videos/\d+',
                r'https?://m\.facebook\.com/\w+/videos/\d+'
            ],
            'douyin': [
                r'https?://(www\.)?douyin\.com/video/\d+',
                r'https?://v\.douyin\.com/[\w-]+'
            ]
        }
        
        # Rate limiting storage (in production, use Redis/database)
        self._rate_limit_cache = {}
        
    def validate_url(self, url: str) -> Tuple[bool, str, Optional[str]]:
        """
        Validate URL format and detect platform
        
        Returns:
            (is_valid, platform, error_message)
        """
        if not url or not isinstance(url, str):
            return False, 'unknown', "URL is required and must be a string"
        
        url = url.strip()
        
        # Basic URL format validation
        try:
            parsed = urlparse.urlparse(url)
            if not all([parsed.scheme, parsed.netloc]):
                return False, 'unknown', "Invalid URL format"
            
            if parsed.scheme not in ['http', 'https']:
                return False, 'unknown', "URL must use HTTP or HTTPS"
        except Exception as e:
            app_logger.warning(f"URL parsing failed: {str(e)}", url=url)
            return False, 'unknown', f"URL parsing error: {str(e)}"
        
        # Check if URL is from supported platforms
        domain = parsed.netloc.lower()
        platform = self._detect_platform(domain)
        
        if platform == 'unknown':
            supported = ', '.join(self.config.SUPPORTED_PLATFORMS)
            return False, 'unknown', f"Unsupported platform. Supported: {supported}"
        
        # Platform-specific validation
        is_valid, error = self._validate_platform_url(url, platform)
        if not is_valid:
            return False, platform, error
        
        # Security checks
        if self._is_suspicious_url(url):
            app_logger.warning("Suspicious URL detected", url=url)
            return False, platform, "URL appears suspicious"
        
        return True, platform, None
    
    def _detect_platform(self, domain: str) -> str:
        """Detect platform from domain"""
        platform_domains = {
            'youtube': ['youtube.com', 'youtu.be', 'm.youtube.com'],
            'tiktok': ['tiktok.com', 'vm.tiktok.com', 'm.tiktok.com'],
            'instagram': ['instagram.com', 'www.instagram.com'],
            'facebook': ['facebook.com', 'fb.com', 'm.facebook.com', 'www.facebook.com'],
            'douyin': ['douyin.com', 'v.douyin.com']
        }
        
        for platform, domains in platform_domains.items():
            if any(d in domain for d in domains):
                return platform
        return 'unknown'
    
    def _validate_platform_url(self, url: str, platform: str) -> Tuple[bool, Optional[str]]:
        """Validate URL against platform-specific patterns"""
        patterns = self.url_patterns.get(platform, [])
        
        for pattern in patterns:
            if re.match(pattern, url, re.IGNORECASE):
                return True, None
        
        return False, f"Invalid {platform} URL format"
    
    def _is_suspicious_url(self, url: str) -> bool:
        """Check for suspicious URL patterns"""
        suspicious_patterns = [
            r'bit\.ly',  # URL shorteners (could hide malicious content)
            r'tinyurl',
            r'[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+',  # IP addresses
            r'localhost',
            r'127\.0\.0\.1',
            r'\.\./\.\.',  # Path traversal
            r'javascript:',
            r'data:',
            r'file:'
        ]
        
        for pattern in suspicious_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False
    
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
        
        # Pattern for different timestamp formats
        patterns = [
            (r'^(\d+)$', lambda m: int(m.group(1))),  # seconds only
            (r'^(\d+):(\d{2})$', lambda m: int(m.group(1)) * 60 + int(m.group(2))),  # MM:SS
            (r'^(\d+):(\d{2}):(\d{2})$', 
             lambda m: int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3)))  # HH:MM:SS
        ]
        
        for pattern, converter in patterns:
            match = re.match(pattern, timestamp)
            if match:
                try:
                    seconds = converter(match)
                    if seconds < 0:
                        return False, "Timestamp cannot be negative", None
                    if seconds > self.config.MAX_VIDEO_DURATION:
                        return False, f"Timestamp exceeds maximum duration ({self.config.MAX_VIDEO_DURATION}s)", None
                    return True, None, seconds
                except ValueError as e:
                    return False, f"Invalid timestamp format: {str(e)}", None
        
        return False, "Invalid timestamp format. Use: 30, 1:23, or 1:23:45", None
    
    def validate_timestamps(self, timestamps: List[str]) -> Tuple[bool, List[str], List[int]]:
        """
        Validate multiple timestamps
        
        Returns:
            (all_valid, error_messages, valid_seconds)
        """
        if not timestamps:
            return False, ["At least one timestamp is required"], []
        
        if len(timestamps) > 50:  # Reasonable limit
            return False, ["Too many timestamps (max 50)"], []
        
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
        
        # Remove/replace dangerous characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = re.sub(r'\.\.+', '.', filename)  # Remove multiple dots
        filename = filename.strip('. ')  # Remove leading/trailing dots and spaces
        
        # Limit length
        if len(filename) > 100:
            filename = filename[:100]
        
        # Ensure it's not empty after sanitization
        if not filename:
            filename = "sanitized_file"
        
        return filename
    
    def check_rate_limit(self, identifier: str, max_requests: int = None, 
                        window_minutes: int = 1) -> Tuple[bool, int]:
        """
        Check rate limit for an identifier (IP, user, etc.)
        
        Returns:
            (is_allowed, requests_remaining)
        """
        if max_requests is None:
            max_requests = self.config.RATE_LIMIT_PER_MINUTE
        
        now = datetime.now()
        window_start = now - timedelta(minutes=window_minutes)
        
        # Clean old entries
        if identifier in self._rate_limit_cache:
            self._rate_limit_cache[identifier] = [
                req_time for req_time in self._rate_limit_cache[identifier]
                if req_time > window_start
            ]
        else:
            self._rate_limit_cache[identifier] = []
        
        current_requests = len(self._rate_limit_cache[identifier])
        
        if current_requests >= max_requests:
            return False, 0
        
        # Add current request
        self._rate_limit_cache[identifier].append(now)
        return True, max_requests - current_requests - 1
    
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
            
        except Exception as e:
            return False, f"Invalid file path: {str(e)}"
    
    def hash_sensitive_data(self, data: str) -> str:
        """Hash sensitive data for logging"""
        return hashlib.sha256(data.encode()).hexdigest()[:8]
    
    def sanitize_user_input(self, text: str, max_length: int = 1000) -> str:
        """Sanitize user input text"""
        if not text:
            return ""
        
        # Basic HTML tag removal and character filtering
        clean_text = re.sub(r'<[^>]+>', '', text)  # Remove HTML tags
        clean_text = re.sub(r'[<>"\'&]', '', clean_text)  # Remove dangerous characters
        
        if len(clean_text) > max_length:
            clean_text = clean_text[:max_length]
        
        return clean_text.strip()
    
    def get_platform_from_url(self, url: str) -> str:
        """Detect platform from URL"""
        try:
            from urllib.parse import urlparse
            parsed = urlparse(url)
            domain = parsed.netloc.lower()
            
            if 'tiktok.com' in domain or 'vm.tiktok.com' in domain:
                return 'tiktok'
            elif 'youtube.com' in domain or 'youtu.be' in domain:
                return 'youtube'
            elif 'facebook.com' in domain or 'fb.com' in domain:
                return 'facebook'
            elif 'douyin.com' in domain:
                return 'douyin'
            elif 'instagram.com' in domain:
                return 'instagram'
            else:
                return 'unknown'
        except Exception:
            return 'unknown'

# Global validator instance
validator = SecurityValidator()
