"""Tests for video_processor.py: yt-dlp hardening, cookies and frame extraction."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np
import yt_dlp

from config import get_config
from video_processor import (ALLOWED_VIDEO_EXTENSIONS, EnhancedVideoFrameExtractor,
                             InstagramProcessor, escape_template_text, find_downloaded_file)


class TestYtdlpOptions(unittest.TestCase):
    """Every platform processor must hand yt-dlp the same safety limits."""

    def setUp(self):
        self.config = get_config()
        extractor = EnhancedVideoFrameExtractor()
        self.options = {name: proc.get_download_options('https://example.invalid/x')
                        for name, proc in extractor.processors.items()}

    def test_download_limits_are_set_for_every_platform(self):
        for name, opts in self.options.items():
            with self.subTest(platform=name):
                self.assertEqual(opts['max_filesize'], self.config.MAX_DOWNLOAD_MB * 1024 * 1024)
                self.assertEqual(opts['socket_timeout'], self.config.SOCKET_TIMEOUT)
                self.assertEqual(opts['retries'], self.config.DOWNLOAD_RETRIES)
                self.assertTrue(opts['noplaylist'])
                self.assertIs(opts['cachedir'], False)
                self.assertFalse(opts.get('enable_file_urls', False))

    def test_only_platform_extractors_are_allowed(self):
        for name, opts in self.options.items():
            with self.subTest(platform=name):
                allowed = opts['allowed_extractors']
                self.assertTrue(allowed)
                self.assertNotIn('generic', allowed)
                self.assertNotIn('all', allowed)
                self.assertNotIn('default', allowed)

    def test_urls_no_platform_extractor_claims_fail_without_network(self):
        """With the generic extractor off, arbitrary URLs are refused up front."""
        opts = dict(self.options['youtube'], quiet=True, no_warnings=True)
        for url in ['http://example.invalid/video.mp4', 'http://127.0.0.1:9/x',
                    'http://169.254.169.254/latest/meta-data/']:
            with self.subTest(url=url):
                with yt_dlp.YoutubeDL(opts) as ydl:
                    with self.assertRaises(yt_dlp.utils.DownloadError) as caught:
                        ydl.extract_info(url, download=False)
                self.assertIn('No suitable extractor', str(caught.exception))

    def test_duration_filter_rejects_long_videos_and_live_streams(self):
        match = self.options['youtube']['match_filter']
        self.assertIsNone(match({'duration': 60}, incomplete=False))
        self.assertIsNone(match({}, incomplete=False))  # unknown duration is allowed
        self.assertTrue(match({'duration': self.config.MAX_VIDEO_DURATION + 1}, incomplete=False))
        self.assertTrue(match({'duration': 10, 'is_live': True}, incomplete=False))

    def test_option_dicts_are_independent_copies(self):
        extractor = EnhancedVideoFrameExtractor()
        first = extractor.processors['youtube'].get_download_options('u')
        first['max_filesize'] = 1
        second = extractor.processors['youtube'].get_download_options('u')
        self.assertNotEqual(second['max_filesize'], 1)


class TestInstagramCookies(unittest.TestCase):
    def setUp(self):
        self.processor = InstagramProcessor()
        self.base_opts = {'format': 'best'}

    def run_fallback(self, use_browser_cookies, cookie_file=None):
        missing = Path(tempfile.gettempdir()) / 'definitely-missing-cookies.txt'
        with patch.object(self.processor.config, 'USE_BROWSER_COOKIES', use_browser_cookies), \
                patch.object(self.processor.config, 'COOKIE_FILE_PATH', cookie_file or missing), \
                patch.object(self.processor, '_attempt_download',
                             return_value=(None, 'failed')) as attempt:
            self.processor.try_with_cookies('https://www.instagram.com/p/x/', self.base_opts)
        return [call.args[1] for call in attempt.call_args_list]

    def test_browser_cookies_are_not_read_by_default(self):
        attempts = self.run_fallback(use_browser_cookies=False)
        self.assertEqual(len(attempts), 1)
        self.assertNotIn('cookiesfrombrowser', attempts[0])
        self.assertNotIn('cookiefile', attempts[0])

    def test_browser_cookies_are_tried_when_enabled(self):
        attempts = self.run_fallback(use_browser_cookies=True)
        browsers = [opts['cookiesfrombrowser'][0] for opts in attempts
                    if 'cookiesfrombrowser' in opts]
        self.assertEqual(browsers, list(self.processor.cookie_sources))
        self.assertNotIn('cookiesfrombrowser', attempts[-1])  # final plain attempt

    def test_manual_cookie_file_is_used_first(self):
        with tempfile.NamedTemporaryFile(suffix='.txt', delete=False) as handle:
            cookie_path = Path(handle.name)
        self.addCleanup(cookie_path.unlink)
        attempts = self.run_fallback(use_browser_cookies=False, cookie_file=cookie_path)
        self.assertEqual(attempts[0]['cookiefile'], str(cookie_path))
        self.assertEqual(len(attempts), 2)  # cookie file, then plain


class TestVideoInfo(unittest.TestCase):
    @patch('video_processor.yt_dlp.YoutubeDL')
    def test_missing_description_does_not_break_info_extraction(self, mock_ytdl):
        """TikTok/Instagram often return description=None."""
        instance = Mock()
        instance.extract_info.return_value = {'title': 'T', 'description': None, 'duration': 5}
        mock_ytdl.return_value.__enter__.return_value = instance

        success, info, error = EnhancedVideoFrameExtractor().get_video_info(
            'https://www.youtube.com/watch?v=abc')

        self.assertTrue(success, error)
        self.assertEqual(info['description'], '')

    @patch('video_processor.yt_dlp.YoutubeDL')
    def test_long_descriptions_are_truncated(self, mock_ytdl):
        instance = Mock()
        instance.extract_info.return_value = {'title': 'T', 'description': 'x' * 900}
        mock_ytdl.return_value.__enter__.return_value = instance

        _, info, _ = EnhancedVideoFrameExtractor().get_video_info(
            'https://www.youtube.com/watch?v=abc')

        self.assertEqual(len(info['description']), 500)


class TestHelpers(unittest.TestCase):
    def test_template_text_escapes_percent(self):
        self.assertEqual(escape_template_text('100% %(id)s'), '100%% %%(id)s')
        self.assertEqual(escape_template_text('plain'), 'plain')

    def test_find_downloaded_file_ignores_partial_downloads(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'clip_abc12345.mp4.part').write_bytes(b'x')
            (folder / 'clip_abc12345.f137.mp4.ytdl').write_bytes(b'x')
            (folder / 'other_zzzzzzzz.mp4').write_bytes(b'x')
            self.assertIsNone(find_downloaded_file(folder, 'abc12345'))

            finished = folder / 'clip_abc12345.mp4'
            finished.write_bytes(b'x')
            self.assertEqual(find_downloaded_file(folder, 'abc12345'), finished)

    def test_webm_and_flv_downloads_are_supported(self):
        for extension in ['.mp4', '.webm', '.mkv', '.mov', '.flv', '.avi']:
            self.assertIn(extension, ALLOWED_VIDEO_EXTENSIONS)


class TestFrameExtraction(unittest.TestCase):
    def setUp(self):
        self.config = get_config()
        tmp = tempfile.TemporaryDirectory(dir=self.config.DOWNLOAD_FOLDER)
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.extractor = EnhancedVideoFrameExtractor()

    def make_video(self, name='clip.avi', seconds=3, fps=10):
        path = self.folder / name
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, (64, 48))
        for index in range(seconds * fps):
            writer.write(np.full((48, 64, 3), index % 255, dtype=np.uint8))
        writer.release()
        return path

    def test_extracts_a_frame_at_a_timestamp(self):
        video = self.make_video()
        output = self.folder / 'frame.jpg'

        success, error = self.extractor.extract_frame_at_timestamp(str(video), 1, str(output))

        self.assertTrue(success, error)
        self.assertGreater(output.stat().st_size, 0)

    def test_timestamp_past_the_end_fails_cleanly(self):
        video = self.make_video(seconds=1)
        success, error = self.extractor.extract_frame_at_timestamp(
            str(video), 120, str(self.folder / 'late.jpg'))
        self.assertFalse(success)
        self.assertTrue(error)

    def test_rejects_paths_outside_the_project(self):
        outside = Path(tempfile.gettempdir()) / 'outside.avi'
        success, error = self.extractor.extract_frame_at_timestamp(
            str(outside), 1, str(self.folder / 'x.jpg'))
        self.assertFalse(success)
        self.assertIn('outside', error)

    def test_webm_is_not_rejected_by_extension(self):
        success, error = self.extractor.extract_frame_at_timestamp(
            str(self.folder / 'missing.webm'), 1, str(self.folder / 'x.jpg'))
        self.assertFalse(success)
        self.assertNotIn('extension', error.lower())


if __name__ == '__main__':
    unittest.main()
