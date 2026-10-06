"""Douyin: the link forms people copy, share-link resolution, optional cookies, honest errors."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import link_resolver
import video_processor
from config import get_config
from validators import validator

VIDEO_ID = '7680376708905651465'
CANONICAL = f'https://www.douyin.com/video/{VIDEO_ID}'


class TestDouyinLinks(unittest.TestCase):
    def test_links_copied_from_douyin_pages_are_accepted_and_made_canonical(self):
        for url in [CANONICAL, f'https://douyin.com/video/{VIDEO_ID}?previous_page=app',
                    f'https://www.douyin.com/jingxuan?modal_id={VIDEO_ID}',
                    f'https://www.douyin.com/user/MS4wLjABAAAA?from_tab_name=main&modal_id={VIDEO_ID}',
                    f'https://www.douyin.com/search/cats?aid=1&modal_id={VIDEO_ID}&type=general']:
            with self.subTest(url=url):
                self.assertEqual(validator.validate_url(url)[:2], (True, 'douyin'))
                self.assertEqual(validator.canonicalize_url(url), CANONICAL)

    def test_share_links_are_accepted_for_resolution(self):
        self.assertEqual(validator.validate_url('https://v.douyin.com/iRNBho6u/')[:2], (True, 'douyin'))

    def test_other_douyin_pages_are_still_rejected(self):
        for url in ['https://www.douyin.com/jingxuan', 'https://www.douyin.com/?modal_id=abc',
                    'https://www.douyin.com.evil.example/video/123456789']:
            with self.subTest(url=url):
                self.assertFalse(validator.validate_url(url)[0])

    def test_share_pages_are_rewritten_without_being_requested(self):
        share = f'https://www.iesdouyin.com/share/video/{VIDEO_ID}/?region=VN&mid=1'
        self.assertEqual(validator.canonicalize_douyin_url(share), CANONICAL)
        self.assertEqual(validator.canonicalize_douyin_url('https://example.com/?modal_id=123456789'),
                         'https://example.com/?modal_id=123456789')


class TestShareLinkResolution(unittest.TestCase):
    def test_v_douyin_com_leads_to_the_canonical_video(self):
        redirect = Mock(status_code=302, headers={'Location': f'https://www.iesdouyin.com/share/video/{VIDEO_ID}/?x=1'})
        with patch.object(link_resolver.requests, 'get', return_value=redirect) as get:
            url, error = link_resolver.resolve_short_url('http://v.douyin.com/iRNBho6u/')
        self.assertEqual((url, error), (CANONICAL, None))
        self.assertEqual(get.call_count, 1, 'only the short-link host is requested')
        self.assertTrue(get.call_args.args[0].startswith('https://v.douyin.com/'))

    def test_a_redirect_somewhere_else_is_refused(self):
        redirect = Mock(status_code=302, headers={'Location': 'https://evil.example/'})
        with patch.object(link_resolver.requests, 'get', return_value=redirect):
            url, error = link_resolver.resolve_short_url('https://v.douyin.com/iRNBho6u/')
        self.assertIsNone(url)
        self.assertIn('unsupported', error)


class TestDouyinDownloads(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.cookie_file = Path(tmp.name) / 'douyin_cookies.txt'
        patcher = patch.object(get_config(), 'DOUYIN_COOKIE_FILE_PATH', self.cookie_file)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.processor = video_processor.DouyinProcessor()

    def test_the_users_cookie_file_is_used_only_when_it_exists(self):
        self.assertNotIn('cookiefile', self.processor.get_download_options(CANONICAL))
        self.cookie_file.write_text('# Netscape HTTP Cookie File\n')
        self.assertEqual(self.processor.get_download_options(CANONICAL)['cookiefile'], str(self.cookie_file))

    def test_the_cookie_error_says_what_to_do(self):
        error = 'ERROR: [Douyin] 7680376708905651465: Fresh cookies (not necessarily logged in) are needed'
        self.assertIn('douyin_cookies.txt in the app folder', self.processor.process_download_error(error))
        self.cookie_file.write_text('# Netscape HTTP Cookie File\n')
        self.assertIn('even with douyin_cookies.txt', self.processor.process_download_error(error))
        self.assertTrue(self.processor.process_download_error('Video unavailable').startswith('Douyin Error'))


if __name__ == '__main__':
    unittest.main()
