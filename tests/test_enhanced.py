"""
Tests for rate limiting, platform detection, video info extraction, the
database layer and configuration. URL, timestamp and filename validation
live in test_validators.py.
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from config import DevelopmentConfig, ProductionConfig
from validators import SecurityValidator
from video_processor import EnhancedVideoFrameExtractor
from database import DatabaseManager


class TestRateLimiting(unittest.TestCase):
    def test_denies_requests_over_the_limit(self):
        validator = SecurityValidator()
        identifier = 'test_user'
        max_requests = 3

        for _ in range(max_requests):
            is_allowed, remaining = validator.check_rate_limit(identifier, max_requests)
            self.assertTrue(is_allowed)
            self.assertGreaterEqual(remaining, 0)

        is_allowed, remaining = validator.check_rate_limit(identifier, max_requests)
        self.assertFalse(is_allowed)
        self.assertEqual(remaining, 0)


class TestVideoProcessor(unittest.TestCase):
    def setUp(self):
        self.extractor = EnhancedVideoFrameExtractor()

    def test_platform_detection(self):
        test_cases = [
            ('https://www.youtube.com/watch?v=test', 'youtube'),
            ('https://www.tiktok.com/@user/video/123', 'tiktok'),
            ('https://www.instagram.com/p/test/', 'instagram'),
            ('https://www.facebook.com/user/videos/123', 'facebook'),
            ('https://www.douyin.com/video/123', 'douyin'),
        ]
        for url, expected_platform in test_cases:
            with self.subTest(url=url):
                self.assertEqual(self.extractor.get_platform_from_url(url), expected_platform)

    @patch('video_processor.yt_dlp.YoutubeDL')
    def test_get_video_info_success(self, mock_ytdl):
        mock_info = {
            'title': 'Test Video',
            'duration': 120,
            'view_count': 1000,
            'uploader': 'Test User',
            'upload_date': '20231201',
            'description': 'Test description',
            'thumbnail': 'http://example.com/thumb.jpg',
        }
        mock_instance = Mock()
        mock_instance.extract_info.return_value = mock_info
        mock_ytdl.return_value.__enter__.return_value = mock_instance

        success, video_info, error = self.extractor.get_video_info(
            'https://www.youtube.com/watch?v=test')

        self.assertTrue(success)
        self.assertEqual(video_info['title'], 'Test Video')
        self.assertEqual(video_info['duration'], 120)
        self.assertIsNone(error)


class TestDatabaseManager(unittest.TestCase):
    """Uses a throwaway database file, never the real app_data.db."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db_manager = DatabaseManager(db_path=Path(tmp.name) / 'test.db')

    def test_log_video_request(self):
        request_id = self.db_manager.log_video_request(
            url_hash='test_hash',
            platform='youtube',
            title='Test Video',
            duration=120,
            user_ip='127.0.0.1',
            user_agent='Test Agent',
        )
        self.assertGreater(request_id, 0)

    def test_get_platform_statistics(self):
        stats = self.db_manager.get_platform_statistics(days=7)
        self.assertIn('period_days', stats)
        self.assertIn('platform_stats', stats)
        self.assertIn('total_frames_extracted', stats)


class TestConfiguration(unittest.TestCase):
    def test_development_config(self):
        config = DevelopmentConfig()
        self.assertEqual(config.FLASK_ENV, 'development')

    def test_production_config(self):
        config = ProductionConfig()
        self.assertFalse(config.DEBUG)
        self.assertEqual(config.FLASK_ENV, 'production')


if __name__ == '__main__':
    unittest.main()
