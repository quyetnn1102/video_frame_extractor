"""Tests for validators.SecurityValidator: URLs, timestamps and filenames."""
import unittest
from unittest.mock import patch

from validators import SecurityValidator


class TestUrlAcceptance(unittest.TestCase):
    """Share links users actually paste must be accepted."""

    def setUp(self):
        self.validator = SecurityValidator()

    def assert_accepted(self, url, platform):
        is_valid, detected, error = self.validator.validate_url(url)
        self.assertTrue(is_valid, f"{url} rejected: {error}")
        self.assertEqual(detected, platform, url)
        self.assertIsNone(error)

    def test_accepts_youtube_forms(self):
        for url in [
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=30s',
            'https://www.youtube.com/watch?feature=share&v=dQw4w9WgXcQ',
            'https://m.youtube.com/watch?v=dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ',
            'https://youtu.be/dQw4w9WgXcQ?t=10',
            'https://www.youtube.com/shorts/abcDEF12345',
            'https://www.youtube.com/live/abcDEF12345',
            'https://www.youtube.com/embed/abcDEF12345',
        ]:
            with self.subTest(url=url):
                self.assert_accepted(url, 'youtube')

    def test_accepts_tiktok_forms(self):
        for url in [
            'https://www.tiktok.com/@some.user/video/7234567890123456789',
            'https://vm.tiktok.com/ZMabc123/',
            'https://vt.tiktok.com/ZSabc123/',
            'https://www.tiktok.com/t/ZTabc123/',
        ]:
            with self.subTest(url=url):
                self.assert_accepted(url, 'tiktok')

    def test_accepts_instagram_forms(self):
        for url in [
            'https://www.instagram.com/p/Cabc123_x/',
            'https://www.instagram.com/reel/Cabc123_x/',
            'https://www.instagram.com/reels/Cabc123_x/',
            'https://www.instagram.com/tv/Cabc123_x/',
        ]:
            with self.subTest(url=url):
                self.assert_accepted(url, 'instagram')

    def test_accepts_facebook_forms(self):
        for url in [
            'https://www.facebook.com/someone/videos/1234567890',
            'https://m.facebook.com/someone/videos/1234567890',
            'https://www.facebook.com/watch/?v=1234567890',
            'https://www.facebook.com/reel/1234567890',
            'https://fb.watch/abc123XYZ/',
        ]:
            with self.subTest(url=url):
                self.assert_accepted(url, 'facebook')

    def test_accepts_douyin_forms(self):
        self.assert_accepted('https://www.douyin.com/video/7234567890123456789', 'douyin')

    def test_douyin_short_links_are_refused_because_they_cannot_be_downloaded(self):
        is_valid, platform, error = self.validator.validate_url('https://v.douyin.com/iabc123/')
        self.assertFalse(is_valid)
        self.assertEqual(platform, 'douyin')
        self.assertTrue(error)


class TestUrlRejection(unittest.TestCase):
    """Lookalike hosts, userinfo tricks and non-web schemes must be rejected."""

    def setUp(self):
        self.validator = SecurityValidator()

    def test_rejects_hostile_or_malformed_urls(self):
        for url in [
            '',
            'not-a-url',
            'http://example.com',
            'javascript:alert(1)',
            'file:///etc/passwd',
            'ftp://youtube.com/watch?v=abc',
            # lookalike hosts / substring matching
            'https://youtube.com.evil.com/watch?v=abc',
            'https://notyoutube.com/watch?v=abc',
            'https://evil.com/youtube.com/watch?v=abc',
            'https://attacker-fb.com/someone/videos/123',
            'http://youtu.be.localtest.me/abc',
            # userinfo tricks
            'https://youtube.com@evil.com/watch?v=abc',
            'https://user:youtube.com@169.254.169.254/watch?v=abc',
            # explicit ports and IP literals
            'https://www.youtube.com:8443/watch?v=abc',
            'https://169.254.169.254/watch?v=abc',
            'http://127.0.0.1/watch?v=abc',
        ]:
            with self.subTest(url=url):
                is_valid, _, error = self.validator.validate_url(url)
                self.assertFalse(is_valid)
                self.assertTrue(error)

    def test_rejects_non_string_input(self):
        for value in [None, 123, ['https://youtu.be/abc']]:
            with self.subTest(value=value):
                is_valid, _, error = self.validator.validate_url(value)
                self.assertFalse(is_valid)
                self.assertTrue(error)

    def test_platform_lookup_uses_exact_hosts(self):
        self.assertEqual(self.validator.get_platform_from_url('https://youtu.be/abc'), 'youtube')
        self.assertEqual(
            self.validator.get_platform_from_url('https://attacker-fb.com/x'), 'unknown')
        self.assertEqual(
            self.validator.get_platform_from_url('https://youtube.com.evil.com/x'), 'unknown')


class TestTimestamps(unittest.TestCase):
    def setUp(self):
        self.validator = SecurityValidator()
        patcher = patch.object(self.validator.config, 'MAX_VIDEO_DURATION', 3600)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_valid_formats_convert_to_seconds(self):
        is_valid, errors, seconds = self.validator.validate_timestamps(
            ['30', '1:23', '1:00:00', '0:05', '12:59'])
        self.assertTrue(is_valid, errors)
        self.assertEqual(seconds, [30, 83, 3600, 5, 779])

    def test_rejects_out_of_range_minutes_and_seconds(self):
        for value in ['1:60', '0:60', '1:99:00', '1:00:60', '1:60:00']:
            with self.subTest(value=value):
                is_valid, error, _ = self.validator.validate_timestamp(value)
                self.assertFalse(is_valid)
                self.assertTrue(error)

    def test_rejects_malformed_values(self):
        for value in ['', ' ', 'abc', '-5', '1:2', '1:2:3', '1::30', '1:00:00:00', None, 30]:
            with self.subTest(value=value):
                is_valid, _, _ = self.validator.validate_timestamp(value)
                self.assertFalse(is_valid)

    def test_enforces_maximum_duration_boundary(self):
        self.assertTrue(self.validator.validate_timestamp('1:00:00')[0])
        is_valid, error, _ = self.validator.validate_timestamp('1:00:01')
        self.assertFalse(is_valid)
        self.assertIn('maximum', error)

    def test_limits_number_of_timestamps(self):
        is_valid, errors, _ = self.validator.validate_timestamps(['1'] * 51)
        self.assertFalse(is_valid)
        self.assertTrue(errors)
        self.assertTrue(self.validator.validate_timestamps(['1'] * 50)[0])

    def test_requires_at_least_one_timestamp(self):
        self.assertFalse(self.validator.validate_timestamps([])[0])


class TestSanitizeFilename(unittest.TestCase):
    def setUp(self):
        self.validator = SecurityValidator()

    def test_strips_path_separators_and_reserved_characters(self):
        cleaned = self.validator.sanitize_filename('a<b>c:d"e/f\\g|h?i*j')
        for char in '<>:"/\\|?*':
            self.assertNotIn(char, cleaned)

    def test_collapses_dot_runs_so_traversal_cannot_survive(self):
        self.assertNotIn('..', self.validator.sanitize_filename('../../etc/passwd'))

    def test_strips_control_characters(self):
        cleaned = self.validator.sanitize_filename('bad\x00name\r\n\x1f.mp4')
        self.assertFalse(any(ord(c) < 32 for c in cleaned))

    def test_prefixes_windows_reserved_names(self):
        for name in ['CON', 'nul', 'COM1', 'lpt9']:
            with self.subTest(name=name):
                self.assertNotEqual(self.validator.sanitize_filename(name).upper(), name.upper())

    def test_limits_length_and_never_returns_empty(self):
        self.assertLessEqual(len(self.validator.sanitize_filename('x' * 500)), 100)
        self.assertTrue(self.validator.sanitize_filename('...'))
        self.assertTrue(self.validator.sanitize_filename(''))


if __name__ == '__main__':
    unittest.main()
