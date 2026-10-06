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
from video_processor import EnhancedVideoFrameExtractor
from database import DatabaseManager


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

    def test_uploads_are_remembered_per_short(self):
        self.db_manager.record_upload('a.mp4', 'vid1', 'private')
        self.db_manager.record_upload('a.mp4', 'vid2', 'unlisted')  # uploaded again
        self.db_manager.record_upload('b.mp4', 'vid3', 'public')
        self.assertEqual(self.db_manager.get_uploads(), {
            'a.mp4': {'video_id': 'vid2', 'privacy': 'unlisted'},
            'b.mp4': {'video_id': 'vid3', 'privacy': 'public'},
        })

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

    def test_a_finished_request_keeps_its_title_and_reason(self):
        import database
        request_id = self.db_manager.log_video_request(url_hash='h', platform='youtube')
        self.db_manager.update_video_request(request_id, 'failed', 'Video unavailable', 12, title='My video')
        with patch.object(database, 'db_manager', self.db_manager):
            row = database.get_recent_requests(limit=1)[0]
        self.assertEqual((row['title'], row['status'], row['error']), ('My video', 'failed', 'Video unavailable'))
        self.assertRegex(row['created_at'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$', 'UTC, readable by browsers')
        self.assertNotIn('user_ip', row)

    def test_analytics_count_how_requests_ended_per_platform(self):
        import database
        for platform, status in [('youtube', 'completed'), ('youtube', 'failed'), ('youtube', 'completed'),
                                 ('tiktok', 'cancelled'), ('tiktok', None)]:
            request_id = self.db_manager.log_video_request(url_hash='h', platform=platform)
            if status:
                self.db_manager.update_video_request(request_id, status)
        with patch.object(database, 'db_manager', self.db_manager):
            outcomes = database.get_analytics()['platform_outcomes']
        self.assertEqual(outcomes['youtube'], {'completed': 2, 'failed': 1, 'cancelled': 0, 'other': 0})
        self.assertEqual(outcomes['tiktok'], {'completed': 0, 'failed': 0, 'cancelled': 1, 'other': 1},
                         'a request still pending (or cut off by a restart) is "other"')

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
