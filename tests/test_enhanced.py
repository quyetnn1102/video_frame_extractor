"""
Comprehensive test suite for Video Frame Extractor
Tests all major functionality with proper mocking
"""
import unittest
import tempfile
from unittest.mock import Mock, patch

# Import our modules
from config import Config, DevelopmentConfig, ProductionConfig
from validators import SecurityValidator
from video_processor import EnhancedVideoFrameExtractor
from database import DatabaseManager

class TestConfig(Config):
    """Test configuration"""
    TESTING = True
    DEBUG = True
    DOWNLOAD_FOLDER = tempfile.mkdtemp()
    FRAMES_FOLDER = tempfile.mkdtemp()
    SHORTS_FOLDER = tempfile.mkdtemp()
    LOGS_FOLDER = tempfile.mkdtemp()

class TestSecurityValidator(unittest.TestCase):
    """Test security validator functionality"""
    
    def setUp(self):
        self.validator = SecurityValidator()
    
    def test_validate_youtube_url(self):
        """Test YouTube URL validation"""
        valid_urls = [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ',
            'https://m.youtube.com/watch?v=dQw4w9WgXcQ'
        ]
        
        for url in valid_urls:
            is_valid, platform, error = self.validator.validate_url(url)
            self.assertTrue(is_valid)
            self.assertEqual(platform, 'youtube')
            self.assertIsNone(error)
    
    def test_validate_invalid_url(self):
        """Test invalid URL handling"""
        invalid_urls = [
            'not-a-url',
            'http://example.com',
            'https://unsupported-site.com/video/123',
            'javascript:alert(1)',
            'file:///etc/passwd'
        ]
        
        for url in invalid_urls:
            is_valid, platform, error = self.validator.validate_url(url)
            self.assertFalse(is_valid)
            self.assertIsNotNone(error)
    
    def test_validate_timestamps(self):
        """Test timestamp validation"""
        valid_timestamps = ['30', '1:23', '1:23:45']
        is_valid, errors, seconds = self.validator.validate_timestamps(valid_timestamps)
        
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)
        self.assertEqual(seconds, [30, 83, 5025])
    
    def test_validate_invalid_timestamps(self):
        """Test invalid timestamp handling"""
        invalid_timestamps = ['abc', '1:60', '-5']
        is_valid, errors, seconds = self.validator.validate_timestamps(invalid_timestamps)
        
        self.assertFalse(is_valid)
        self.assertGreater(len(errors), 0)
    
    def test_sanitize_filename(self):
        """Test filename sanitization"""
        dangerous_filename = 'test<>:"/\\|?*.txt'
        safe_filename = self.validator.sanitize_filename(dangerous_filename)
        
        self.assertNotIn('<', safe_filename)
        self.assertNotIn('>', safe_filename)
        self.assertNotIn(':', safe_filename)
    
    def test_rate_limiting(self):
        """Test rate limiting functionality"""
        identifier = 'test_user'
        max_requests = 3
        
        # First 3 requests should be allowed
        for i in range(max_requests):
            is_allowed, remaining = self.validator.check_rate_limit(identifier, max_requests)
            self.assertTrue(is_allowed)
            self.assertGreaterEqual(remaining, 0)
        
        # 4th request should be denied
        is_allowed, remaining = self.validator.check_rate_limit(identifier, max_requests)
        self.assertFalse(is_allowed)
        self.assertEqual(remaining, 0)

class TestVideoProcessor(unittest.TestCase):
    """Test video processing functionality"""
    
    def setUp(self):
        self.extractor = EnhancedVideoFrameExtractor()
    
    def test_platform_detection(self):
        """Test platform detection"""
        test_cases = [
            ('https://www.youtube.com/watch?v=test', 'youtube'),
            ('https://www.tiktok.com/@user/video/123', 'tiktok'),
            ('https://www.instagram.com/p/test/', 'instagram'),
            ('https://www.facebook.com/user/videos/123', 'facebook'),
            ('https://www.douyin.com/video/123', 'douyin')
        ]
        
        for url, expected_platform in test_cases:
            platform = self.extractor.get_platform_from_url(url)
            self.assertEqual(platform, expected_platform)
    
    @patch('video_processor.yt_dlp.YoutubeDL')
    def test_get_video_info_success(self, mock_ytdl):
        """Test successful video info extraction"""
        # Mock yt-dlp response
        mock_info = {
            'title': 'Test Video',
            'duration': 120,
            'view_count': 1000,
            'uploader': 'Test User',
            'upload_date': '20231201',
            'description': 'Test description',
            'thumbnail': 'http://example.com/thumb.jpg'
        }
        
        mock_instance = Mock()
        mock_instance.extract_info.return_value = mock_info
        mock_ytdl.return_value.__enter__.return_value = mock_instance
        
        url = 'https://www.youtube.com/watch?v=test'
        success, video_info, error = self.extractor.get_video_info(url)
        
        self.assertTrue(success)
        self.assertEqual(video_info['title'], 'Test Video')
        self.assertEqual(video_info['duration'], 120)
        self.assertIsNone(error)

class TestDatabaseManager(unittest.TestCase):
    """Test database functionality"""
    
    def setUp(self):
        self.db_manager = DatabaseManager()
    
    def test_log_video_request(self):
        """Test video request logging"""
        request_id = self.db_manager.log_video_request(
            url_hash='test_hash',
            platform='youtube',
            title='Test Video',
            duration=120,
            user_ip='127.0.0.1',
            user_agent='Test Agent'
        )
        
        self.assertGreater(request_id, 0)
    
    def test_get_platform_statistics(self):
        """Test platform statistics generation"""
        stats = self.db_manager.get_platform_statistics(days=7)
        
        self.assertIn('period_days', stats)
        self.assertIn('platform_stats', stats)
        self.assertIn('total_frames_extracted', stats)

class TestConfiguration(unittest.TestCase):
    """Test configuration management"""
    
    def test_development_config(self):
        """Test development configuration"""
        config = DevelopmentConfig()
        self.assertTrue(config.DEBUG)
        self.assertEqual(config.FLASK_ENV, 'development')
    
    def test_production_config(self):
        """Test production configuration"""
        config = ProductionConfig()
        self.assertFalse(config.DEBUG)
        self.assertEqual(config.FLASK_ENV, 'production')
        self.assertEqual(config.RATE_LIMIT_PER_MINUTE, 10)

if __name__ == '__main__':
    unittest.main()
