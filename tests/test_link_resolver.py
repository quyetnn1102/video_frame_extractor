"""Tests for link_resolver.py: safe resolution of share-link redirects."""
import unittest
from unittest.mock import Mock, patch

import requests

from link_resolver import MAX_REDIRECT_HOPS, resolve_short_url


def redirect(location, status=301):
    response = Mock()
    response.status_code = status
    response.headers = {'Location': location} if location else {}
    return response


class TestResolveShortUrl(unittest.TestCase):
    def test_regular_urls_are_returned_without_any_network_call(self):
        with patch('link_resolver.requests.get') as get:
            url, error = resolve_short_url('https://www.youtube.com/watch?v=abc')
        self.assertEqual(url, 'https://www.youtube.com/watch?v=abc')
        self.assertIsNone(error)
        get.assert_not_called()

    def test_fb_watch_resolves_to_the_facebook_video_url(self):
        target = 'https://www.facebook.com/someone/videos/1234567890/'
        with patch('link_resolver.requests.get', return_value=redirect(target)) as get:
            url, error = resolve_short_url('https://fb.watch/abc123/')
        self.assertEqual(url, target)
        self.assertIsNone(error)
        self.assertIs(get.call_args.kwargs['allow_redirects'], False)
        self.assertEqual(get.call_args.args[0], 'https://fb.watch/abc123/')

    def test_short_links_are_always_requested_over_https(self):
        target = 'https://www.facebook.com/someone/videos/1234567890/'
        with patch('link_resolver.requests.get', return_value=redirect(target)) as get:
            resolve_short_url('http://fb.watch/abc123/')
        self.assertEqual(get.call_args.args[0], 'https://fb.watch/abc123/')

    def test_a_redirect_back_to_plain_http_is_requested_over_https(self):
        responses = [redirect('http://fb.watch/next/'),
                     redirect('https://www.facebook.com/someone/videos/1234567890/')]
        with patch('link_resolver.requests.get', side_effect=responses) as get:
            resolve_short_url('https://fb.watch/abc123/')
        self.assertEqual([call.args[0] for call in get.call_args_list],
                         ['https://fb.watch/abc123/', 'https://fb.watch/next/'])

    def test_relative_redirects_are_resolved_against_the_current_url(self):
        responses = [redirect('/redirected/path'), redirect(
            'https://www.facebook.com/someone/videos/1234567890/')]
        with patch('link_resolver.requests.get', side_effect=responses):
            url, error = resolve_short_url('https://fb.watch/abc123/')
        self.assertIsNone(error)
        self.assertTrue(url.startswith('https://www.facebook.com/'))

    def test_redirect_to_an_untrusted_host_is_refused(self):
        for target in ['https://evil.example/x', 'http://169.254.169.254/latest/meta-data/',
                       'http://127.0.0.1:8080/admin', 'file:///etc/passwd']:
            with self.subTest(target=target):
                with patch('link_resolver.requests.get', return_value=redirect(target)):
                    url, error = resolve_short_url('https://fb.watch/abc123/')
                self.assertIsNone(url)
                self.assertTrue(error)

    def test_only_the_short_link_host_is_ever_fetched(self):
        target = 'https://www.facebook.com/someone/videos/1234567890/'
        with patch('link_resolver.requests.get', return_value=redirect(target)) as get:
            resolve_short_url('https://fb.watch/abc123/')
        self.assertEqual(get.call_count, 1)

    def test_redirect_loops_are_cut_off(self):
        with patch('link_resolver.requests.get',
                   return_value=redirect('https://fb.watch/again/')) as get:
            url, error = resolve_short_url('https://fb.watch/abc123/')
        self.assertIsNone(url)
        self.assertTrue(error)
        self.assertEqual(get.call_count, MAX_REDIRECT_HOPS)

    def test_non_redirect_responses_are_an_error(self):
        with patch('link_resolver.requests.get', return_value=redirect(None, status=200)):
            url, error = resolve_short_url('https://fb.watch/abc123/')
        self.assertIsNone(url)
        self.assertTrue(error)

    def test_network_errors_are_reported_not_raised(self):
        with patch('link_resolver.requests.get', side_effect=requests.ConnectionError('boom')):
            url, error = resolve_short_url('https://fb.watch/abc123/')
        self.assertIsNone(url)
        self.assertNotIn('boom', error)

    def test_a_timeout_is_always_passed(self):
        target = 'https://www.facebook.com/someone/videos/1234567890/'
        with patch('link_resolver.requests.get', return_value=redirect(target)) as get:
            resolve_short_url('https://fb.watch/abc123/')
        self.assertGreater(get.call_args.kwargs['timeout'], 0)


if __name__ == '__main__':
    unittest.main()
