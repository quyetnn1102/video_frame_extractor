"""Contract tests for the Flask app: routes, security headers and error handling."""
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import quote

import app_enhanced
import media_jobs
from app_enhanced import create_app
from config import get_config
from jobs import JobRegistry
from short_video import ShortVideoError
from youtube_uploader import YouTubeUploaderError

VALID_URL = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'


class RouteTestCase(unittest.TestCase):
    rate_limit_enabled = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.frames = root / 'frames'
        self.shorts = root / 'shorts'
        self.downloads = root / 'downloads'
        for folder in (self.frames, self.shorts, self.downloads):
            folder.mkdir()

        config = get_config()
        # ALLOWED_HOSTS and HOST are pinned so a developer's .env cannot change the results
        for name, value in [('FRAMES_FOLDER', self.frames), ('SHORTS_FOLDER', self.shorts),
                            ('DOWNLOAD_FOLDER', self.downloads),
                            ('RATELIMIT_ENABLED', self.rate_limit_enabled),
                            ('ALLOWED_HOSTS', ('localhost', '127.0.0.1', '[::1]')),
                            ('HOST', '127.0.0.1')]:
            patcher = patch.object(config, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.extractor = self.patch_module('extractor')
        self.extractor.cleanup_old_files.return_value = (0, 0, [])
        self.uploader = self.patch_module('youtube_uploader')
        self.db = self.patch_module('db_manager')
        self.db.log_video_request.return_value = 7
        # A fresh job registry per test, so jobs from other tests are not listed
        registry = JobRegistry(max_workers=2)
        patcher = patch.object(app_enhanced, 'job_registry', registry)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(registry.shutdown)

        self.app = create_app()
        self.client = self.app.test_client()

    def patch_module(self, name):
        """One mock for the name in app_enhanced and in media_jobs (which does the downloads)."""
        mocked = Mock()
        for module in (app_enhanced, media_jobs):
            if hasattr(module, name):
                patcher = patch.object(module, name, mocked)
                patcher.start()
                self.addCleanup(patcher.stop)
        return mocked

    def make_download(self, name='download.mp4'):
        path = self.downloads / name
        path.write_bytes(b'video')
        return path


class TestRequestGuards(RouteTestCase):
    def test_only_loopback_hosts_are_served(self):
        for host, expected in [('localhost', 200), ('localhost:5000', 200), ('LOCALHOST', 200),
                               ('127.0.0.1:5000', 200), ('[::1]:5000', 200),
                               ('evil.example', 400), ('localhost.evil.com', 400),
                               ('127.0.0.1.evil.com', 400), ('192.168.1.10:5000', 400),
                               ('localhost.', 400), ('user@localhost', 400),
                               ('evil.com\\@localhost', 400)]:
            with self.subTest(host=host):
                response = self.client.get('/api/health', headers={'Host': host})
                self.assertEqual(response.status_code, expected)

    def test_host_header_parser(self):
        allowed = ('localhost', '127.0.0.1', '[::1]', 'My.Box')
        for host in ['localhost', 'LOCALHOST:5000', '127.0.0.1:1', '[::1]', '[::1]:65535',
                     'my.box', 'MY.BOX:8080']:
            with self.subTest(host=host):
                self.assertTrue(app_enhanced.host_is_allowed(host, allowed))
        # (ports like 'localhost:abc' never reach the app through the test client, so they
        # are checked here, against the parser itself)
        for host in ['', None, 'localhost\t', ' localhost', 'localhost:', ':5000', '::1',
                     '[::1', 'localhost:65536', 'localhost:abc', 'localhost:99999',
                     'localhost:5000:80', '[::ffff:127.0.0.1]', 'a@localhost',
                     'localhost/path', 'localhost#x']:
            with self.subTest(host=host):
                self.assertFalse(app_enhanced.host_is_allowed(host, allowed))

    def test_security_headers_are_set(self):
        response = self.client.get('/api/health')
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertEqual(response.headers['Referrer-Policy'], 'no-referrer')
        csp = response.headers['Content-Security-Policy']
        for directive in ["frame-ancestors 'none'", "object-src 'none'", "connect-src 'self'",
                          "base-uri 'self'"]:
            self.assertIn(directive, csp)
        self.assertNotIn('Strict-Transport-Security', response.headers)

    def test_hsts_is_only_sent_over_https(self):
        response = self.client.get('/api/health', base_url='https://localhost')
        self.assertIn('Strict-Transport-Security', response.headers)


class TestCrossSiteGuards(RouteTestCase):
    """Another website must not be able to drive the local API from the user's browser."""

    def test_api_calls_from_other_sites_are_refused(self):
        self.extractor.cleanup_old_files.reset_mock()  # create_app() already swept once
        for site in ('cross-site', 'same-site'):
            for method, path in [('get', '/api/health'), ('post', '/api/cleanup'),
                                 ('get', '/api/youtube-auth'), ('get', '/api/trending')]:
                with self.subTest(site=site, path=path):
                    response = getattr(self.client, method)(path, headers={'Sec-Fetch-Site': site})
                    self.assertEqual(response.status_code, 403)
                    self.assertFalse(response.get_json()['success'])
        self.extractor.cleanup_old_files.assert_not_called()

    def test_same_origin_and_non_browser_clients_are_fine(self):
        for headers in [{'Sec-Fetch-Site': 'same-origin'}, {'Sec-Fetch-Site': 'none'}, {}]:
            with self.subTest(headers=headers):
                self.assertEqual(self.client.get('/api/health', headers=headers).status_code, 200)

    def test_foreign_origins_are_refused(self):
        for origin in ['http://evil.example', 'https://localhost.evil.com', 'null',
                       'http://localhost@evil.com', 'file://', 'ftp://localhost']:
            with self.subTest(origin=origin):
                response = self.client.post('/api/cleanup', headers={'Origin': origin})
                self.assertEqual(response.status_code, 403)

    def test_the_apps_own_origin_is_accepted(self):
        for origin in ['http://localhost:5000', 'http://127.0.0.1:5000', 'http://[::1]:5000',
                       'https://localhost']:
            with self.subTest(origin=origin):
                response = self.client.post('/api/cleanup', headers={'Origin': origin})
                self.assertEqual(response.status_code, 200)

    def test_pages_and_the_oauth_callback_can_be_reached_from_other_sites(self):
        """Following a link, and Google's redirect back after sign-in, are cross-site navigations."""
        headers = {'Sec-Fetch-Site': 'cross-site'}
        self.assertEqual(self.client.get('/', headers=headers).status_code, 200)
        response = self.client.get('/oauth2callback', headers=headers)
        self.assertEqual(response.status_code, 400)  # missing code/state, but not blocked as 403


class TestRequestSize(RouteTestCase):
    def test_oversized_bodies_are_refused_with_json(self):
        huge = '{"url": "' + 'a' * (2 * 1024 * 1024) + '"}'
        response = self.client.post('/api/validate-url', data=huge, content_type='application/json')
        self.assertEqual(response.status_code, 413)
        self.assertFalse(response.get_json()['success'])

    def test_normal_bodies_are_accepted(self):
        response = self.client.post('/api/validate-url', json={'url': 'https://example.com/x'})
        self.assertEqual(response.status_code, 200)


class TestErrorHandling(RouteTestCase):
    def test_unknown_routes_and_methods_return_json_errors(self):
        for method, path, status in [('get', '/nope', 404), ('post', '/api/health', 405)]:
            with self.subTest(path=path):
                response = getattr(self.client, method)(path)
                self.assertEqual(response.status_code, status)
                self.assertFalse(response.get_json()['success'])

    def test_non_json_bodies_are_a_client_error(self):
        for path in ['/api/validate-url', '/api/extract', '/api/video-info',
                     '/api/create-short', '/api/upload-to-youtube', '/api/test-platform']:
            with self.subTest(path=path):
                response = self.client.post(path, data='plain', content_type='text/plain')
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()['success'])

    def test_unexpected_errors_do_not_leak_details(self):
        self.extractor.get_video_info.side_effect = RuntimeError(r'secret C:\Users\me\token')

        response = self.client.post('/api/video-info', json={'url': VALID_URL})

        self.assertEqual(response.status_code, 500)
        body = response.get_data(as_text=True)
        self.assertNotIn('secret', body)
        self.assertNotIn('Users', body)
        self.assertTrue(response.get_json()['error_id'])

    def test_removed_debug_and_fake_endpoints_are_gone(self):
        for path in ['/api/test-ytdlp', '/api/search', '/api/platform-status',
                     '/api/youtube-callback']:
            with self.subTest(path=path):
                self.assertEqual(self.client.post(path, json={}).status_code, 404)


class TestPagesAndInfo(RouteTestCase):
    def test_pages_render(self):
        for path in ['/', '/extract', '/trending', '/create-short']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_dashboard_renders_with_analytics(self):
        with patch.object(app_enhanced, 'get_analytics', return_value={}), \
                patch.object(app_enhanced, 'get_recent_requests', return_value=[]):
            self.assertEqual(self.client.get('/dashboard').status_code, 200)

    def test_health(self):
        self.assertEqual(self.client.get('/api/health').get_json()['status'], 'healthy')

    def test_categories_come_from_the_shared_table(self):
        data = self.client.get('/api/video-categories').get_json()
        self.assertEqual(data['total'], 15)

    def test_platform_guidance_makes_no_invented_reliability_claims(self):
        data = self.client.post('/api/test-platform', json={'url': VALID_URL}).get_json()
        self.assertEqual(data['platform'], 'youtube')
        self.assertTrue(data['valid'])
        self.assertNotIn('reliability', data['info'])

    def test_platform_guidance_for_unsupported_urls(self):
        data = self.client.post('/api/test-platform', json={'url': 'https://example.com/x'}).get_json()
        self.assertFalse(data['valid'])

    def test_platform_check_agrees_with_what_create_short_would_accept(self):
        """Any URL on a supported host used to count as valid, even a channel page."""
        for url in ['https://www.youtube.com/', 'https://www.youtube.com/@somechannel',
                    'https://evil.com\\.youtube.com/watch?v=abc123',
                    'https://www.youtube.com:8443/watch?v=abc123']:
            with self.subTest(url=url):
                data = self.client.post('/api/test-platform', json={'url': url}).get_json()
                self.assertFalse(data['valid'])
                self.assertTrue(data['info']['notes'])
        data = self.client.post('/api/test-platform', json={'url': VALID_URL}).get_json()
        self.assertTrue(data['valid'])

    def test_platform_guidance_needs_a_string_url(self):
        for body in [{}, {'url': ''}, {'url': 5}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/api/test-platform', json=body).status_code, 400)

    def test_trending_passes_validated_parameters(self):
        with patch.object(app_enhanced, 'get_youtube_trending', return_value=[{'id': 'a'}]) as get:
            data = self.client.get('/api/trending?region=VN&category=10&max_results=5').get_json()
        get.assert_called_once_with('10', 'VN', 5)
        self.assertEqual(data['total'], 1)

    def test_trending_rejects_bad_input(self):
        self.assertEqual(self.client.get('/api/trending?max_results=abc').status_code, 400)
        self.assertEqual(self.client.get('/api/trending?platform=tiktok').status_code, 400)

    def test_cleanup_reports_the_result(self):
        self.extractor.cleanup_old_files.return_value = (3, 5, [])
        data = self.client.post('/api/cleanup').get_json()
        self.assertEqual((data['files_deleted'], data['space_freed_mb']), (3, 5))


class TestAppShell(RouteTestCase):
    """Every page shares one sidebar and top bar, and the sidebar marks the page you are on."""
    PAGES = [('/', 'Home'), ('/extract', 'Extract frames'), ('/create-short', 'Create short'),
             ('/trending', 'Trending'), ('/dashboard', 'Dashboard')]

    def get_page(self, path):
        with patch.object(app_enhanced, 'get_analytics', return_value={}), \
                patch.object(app_enhanced, 'get_recent_requests', return_value=[]):
            response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        return response.get_data(as_text=True)

    def test_each_page_marks_only_its_own_link_as_current(self):
        for path, label in self.PAGES:
            with self.subTest(path=path):
                html = self.get_page(path)
                self.assertEqual(html.count('aria-current="page"'), 1)
                self.assertIn(f'aria-current="page" title="{label}"', html)

    def test_each_page_names_itself_in_the_top_bar(self):
        for path, label in self.PAGES[1:]:
            with self.subTest(path=path):
                self.assertIn(f'<h1>{label}</h1>', self.get_page(path))
        self.assertIn('<h1>Hey, let&#39;s get started!</h1>', self.get_page('/'))

    def test_every_page_links_to_every_tool(self):
        for path, _ in self.PAGES:
            with self.subTest(path=path):
                html = self.get_page(path)
                for target in ['href="/"', 'href="/extract"', 'href="/create-short"',
                               'href="/trending"', 'href="/dashboard"']:
                    self.assertIn(target, html)

    def test_the_frame_form_lives_on_extract_and_the_home_page_is_a_launcher(self):
        self.assertIn('id="extractForm"', self.get_page('/extract'))
        home = self.get_page('/')
        self.assertNotIn('id="extractForm"', home)
        self.assertIn('id="launchForm"', home)


class TestValidateAndVideoInfo(RouteTestCase):
    def test_validate_url_reports_invalid_urls(self):
        data = self.client.post('/api/validate-url', json={'url': 'https://example.com/x'}).get_json()
        self.assertFalse(data['valid'])
        self.extractor.get_video_info.assert_not_called()

    def test_validate_url_includes_video_details(self):
        self.extractor.get_video_info.return_value = (
            True, {'title': 'T', 'duration': 5, 'thumbnail': 'u'}, None)
        data = self.client.post('/api/validate-url', json={'url': VALID_URL}).get_json()
        self.assertTrue(data['valid'])
        self.assertEqual(data['platform'], 'youtube')
        self.assertEqual(data['title'], 'T')

    def test_video_info(self):
        self.extractor.get_video_info.return_value = (True, {'title': 'T'}, None)
        data = self.client.post('/api/video-info', json={'url': VALID_URL}).get_json()
        self.assertEqual(data['video_info']['title'], 'T')

    def test_video_info_failure_is_a_client_error(self):
        self.extractor.get_video_info.return_value = (False, None, 'Not available')
        response = self.client.post('/api/video-info', json={'url': VALID_URL})
        self.assertEqual((response.status_code, response.get_json()['error']), (400, 'Not available'))


class TestExtractFrames(RouteTestCase):
    def post(self, **overrides):
        body = {'url': VALID_URL, 'timestamps': ['5', '1:10']}
        body.update(overrides)
        return self.client.post('/api/extract', json=body)

    def test_rejects_bad_input_before_downloading(self):
        for overrides in [{'url': ''}, {'url': 'https://example.com/x'}, {'timestamps': []},
                          {'timestamps': ['1:60']}, {'timestamps': 'abc'}]:
            with self.subTest(overrides=overrides):
                self.assertEqual(self.post(**overrides).status_code, 400)
        self.extractor.download_video.assert_not_called()

    def test_download_failures_are_reported(self):
        self.extractor.download_video.return_value = (None, None, 'Video unavailable')
        response = self.post()
        self.assertEqual((response.status_code, response.get_json()['error']), (400, 'Video unavailable'))
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'failed'))

    def test_extracts_frames_and_removes_the_download(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.return_value = (True, None)
        self.extractor.get_video_info.return_value = (True, {'title': 'Title', 'duration': 60}, None)

        data = self.post().get_json()

        self.assertTrue(data['success'])
        self.assertEqual([frame['timestamp'] for frame in data['frames']], [5, 70])
        for frame in data['frames']:
            self.assertRegex(frame['url'], r'^/frames/frame_\d+s_[0-9a-f]{8}\.jpg$')
        self.assertFalse(video.exists())
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'completed'))
        self.assertEqual(self.db.log_extracted_frame.call_count, 2)

    def test_download_is_removed_even_when_extraction_crashes(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.side_effect = RuntimeError('boom')

        response = self.post()

        self.assertEqual(response.status_code, 500)  # unexpected: generic error, not a 400
        self.assertNotIn('boom', response.get_data(as_text=True))
        self.assertFalse(video.exists())
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'failed'))

    def test_partial_failures_become_warnings(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.side_effect = [(True, None), (False, 'past the end')]

        data = self.post().get_json()

        self.assertEqual(len(data['frames']), 1)
        self.assertEqual(len(data['warnings']), 1)

    def test_all_frames_failing_is_an_error(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.return_value = (False, 'past the end')
        self.assertEqual(self.post().status_code, 400)


class TestServeFiles(RouteTestCase):
    def test_serves_existing_frames_and_shorts(self):
        (self.frames / 'frame_1s_abcd1234.jpg').write_bytes(b'jpegdata')
        (self.shorts / 'My Clip_abcd1234_short.mp4').write_bytes(b'mp4data')

        frame = self.client.get('/frames/frame_1s_abcd1234.jpg')
        short = self.client.get('/shorts/My%20Clip_abcd1234_short.mp4')

        self.assertEqual((frame.status_code, frame.data), (200, b'jpegdata'))
        self.assertEqual((short.status_code, short.data), (200, b'mp4data'))
        frame.close()
        short.close()

    def test_missing_traversing_and_wrong_type_files_are_404(self):
        (self.frames / 'notes.txt').write_bytes(b'x')
        (self.frames.parent / 'secret.jpg').write_bytes(b'x')
        for path in ['/frames/missing.jpg', '/frames/notes.txt', '/frames/..%2Fsecret.jpg',
                     '/frames/..%5Csecret.jpg', '/shorts/missing.mp4', '/shorts/..%2Fsecret.mp4']:
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 404)


class TestShortsLibrary(RouteTestCase):
    """Earlier shorts stay available after the page is closed or refreshed."""

    def setUp(self):
        super().setUp()
        patcher = patch('library.video_duration', return_value=30.0)
        patcher.start()
        self.addCleanup(patcher.stop)

    def delete(self, filename):
        return self.client.post('/api/shorts/delete', json={'filename': filename})

    def test_lists_the_shorts_in_the_output_folder(self):
        (self.shorts / 'My Clip_abcd1234_short.mp4').write_bytes(b'mp4data')

        data = self.client.get('/api/shorts').get_json()

        self.assertTrue(data['success'])
        self.assertEqual([item['filename'] for item in data['shorts']], ['My Clip_abcd1234_short.mp4'])
        self.assertEqual(data['shorts'][0]['title'], 'My Clip')
        self.assertEqual(data['shorts'][0]['url'], '/shorts/My%20Clip_abcd1234_short.mp4')

    def test_an_empty_folder_gives_an_empty_list(self):
        self.assertEqual(self.client.get('/api/shorts').get_json()['shorts'], [])

    def test_deletes_a_short_by_file_name(self):
        short = self.shorts / 'My Clip_abcd1234_short.mp4'
        short.write_bytes(b'mp4data')

        response = self.delete('My Clip_abcd1234_short.mp4')

        self.assertEqual(response.status_code, 200)
        self.assertFalse(short.exists())

    def test_never_deletes_outside_the_shorts_folder(self):
        outside = self.shorts.parent / 'secret.mp4'
        outside.write_bytes(b'x')
        (self.shorts / 'notes.txt').write_bytes(b'x')
        for name in ['../secret.mp4', '..\\secret.mp4', 'notes.txt', 'missing.mp4', '']:
            with self.subTest(name=name):
                self.assertEqual(self.delete(name).status_code, 404)
        self.assertTrue(outside.exists())
        self.assertTrue((self.shorts / 'notes.txt').exists())

    def test_rejects_a_missing_or_non_text_file_name(self):
        for body in [{}, {'filename': 5}, {'filename': ['a.mp4']}]:
            with self.subTest(body=body):
                self.assertEqual(self.client.post('/api/shorts/delete', json=body).status_code, 400)


class TestCreateShort(RouteTestCase):
    def post(self, **overrides):
        body = {'url': VALID_URL, 'start_time': '0:30', 'duration': 20, 'quality': 'low'}
        body.update(overrides)
        return self.client.post('/api/create-short', json=body)

    def fake_render(self, *args, **kwargs):
        output = args[1]
        Path(output).write_bytes(b'rendered-short')
        return {'start_time': kwargs['start'], 'duration': kwargs['duration'], 'warnings': []}

    def test_rejects_invalid_requests_before_downloading(self):
        for overrides in [{'url': ''}, {'url': 5}, {'url': 'https://example.com/x'},
                          {'start_time': '1:60'}, {'start_time': -3}, {'duration': 0},
                          {'duration': 9999}, {'duration': 'abc'}, {'quality': 'ultra'},
                          {'text_overlay': {'text': 'x' * 500}}, {'text_overlay': {'text': 'a', 'color': 'x;y'}}]:
            with self.subTest(overrides=overrides):
                response = self.post(**overrides)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.get_json()['success'])
        self.extractor.download_video.assert_not_called()

    def test_creates_a_short_and_removes_the_download(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'My: Video/Title', None)

        with patch.object(media_jobs, 'create_short', side_effect=self.fake_render) as render:
            data = self.post(vertical_format=True, text_overlay={'text': 'Hi'}).get_json()

        self.assertTrue(data['success'])
        self.assertRegex(data['filename'], r'^[\w -]+_[0-9a-f]{8}_short\.mp4$')
        self.assertNotIn(':', data['filename'])
        self.assertNotIn('/', data['filename'])
        self.assertEqual(data['download_url'], '/shorts/' + quote(data['filename']))
        self.assertNotIn(' ', data['download_url'])
        self.assertEqual((data['quality'], data['duration'], data['start_time']), ('low', 20, 30))
        self.assertEqual(data['file_size'], len(b'rendered-short'))
        self.assertTrue((self.shorts / data['filename']).exists())
        self.assertFalse(video.exists())

        kwargs = render.call_args.kwargs
        self.assertEqual((kwargs['start'], kwargs['duration'], kwargs['vertical']), (30, 20, True))
        self.assertEqual(kwargs['text_overlay']['text'], 'Hi')
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'completed'))

    def test_vertical_format_must_be_a_json_boolean(self):
        """'true' used to be silently treated as false, giving a non-vertical short."""
        for value in ['true', 1, 'yes', None, []]:
            with self.subTest(value=value):
                response = self.post(vertical_format=value)
                self.assertEqual(response.status_code, 400)
                self.assertIn('vertical_format', response.get_json()['error'])
        self.extractor.download_video.assert_not_called()

    def test_legacy_overlay_text_field_is_still_accepted(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(media_jobs, 'create_short', side_effect=self.fake_render) as render:
            self.post(overlay_text='Legacy')
        self.assertEqual(render.call_args.kwargs['text_overlay']['text'], 'Legacy')

    def test_download_failure_is_a_client_error_with_the_reason(self):
        self.extractor.download_video.return_value = (None, None, 'Video unavailable')
        response = self.post()
        self.assertEqual((response.status_code, response.get_json()['error']), (400, 'Video unavailable'))

    def test_render_problems_are_reported_and_the_download_is_removed(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(media_jobs, 'create_short',
                          side_effect=ShortVideoError('Start time (30s) exceeds video duration (10.0s)')):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn('exceeds video duration', response.get_json()['error'])
        self.assertFalse(video.exists())

    def test_unexpected_render_errors_are_generic_and_the_download_is_removed(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(media_jobs, 'create_short', side_effect=RuntimeError(r'C:\secret\path')):
            response = self.post()
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('secret', response.get_data(as_text=True))
        self.assertFalse(video.exists())

    def test_overlay_warnings_are_passed_on(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)

        def render(*args, **kwargs):
            Path(args[1]).write_bytes(b'x')
            return {'start_time': 0, 'duration': 1, 'warnings': ['Text overlay was skipped']}

        with patch.object(media_jobs, 'create_short', side_effect=render):
            data = self.post(text_overlay={'text': 'Hi'}).get_json()
        self.assertEqual(data['warnings'], ['Text overlay was skipped'])


class TestYouTubeRoutes(RouteTestCase):
    def setUp(self):
        super().setUp()
        self.uploader.is_authenticated.return_value = True
        self.uploader.validate_short_video.return_value = (True, 'ok')
        self.uploader.upload_video.return_value = (True, 'Video uploaded successfully', 'vid123')

    def upload(self, **body):
        return self.client.post('/api/upload-to-youtube', json=body)

    def make_short(self, name='clip_abcd1234_short.mp4'):
        path = self.shorts / name
        path.write_bytes(b'short')
        return path

    def test_upload_takes_a_file_name_from_the_shorts_folder(self):
        short = self.make_short()

        data = self.upload(filename=short.name, title='My title').get_json()

        self.assertTrue(data['success'])
        self.assertEqual(data['youtube_url'], 'https://www.youtube.com/watch?v=vid123')
        kwargs = self.uploader.upload_video.call_args.kwargs
        self.assertEqual(Path(kwargs['video_path']), short.resolve())
        self.assertEqual((kwargs['title'], kwargs['privacy_status']), ('My title', 'private'))

    def test_server_paths_are_never_accepted(self):
        short = self.make_short()
        outside = self.frames.parent / 'secret.mp4'
        outside.write_bytes(b'x')
        for body in [{'video_path': str(short)}, {'filename': str(short)},
                     {'filename': '../secret.mp4'}, {'filename': '..\\secret.mp4'},
                     {'filename': str(outside)}, {'filename': 'missing.mp4'}, {'filename': 5}, {}]:
            with self.subTest(body=body):
                self.assertIn(self.upload(**body).status_code, (400, 404))
        self.uploader.upload_video.assert_not_called()

    def test_privacy_and_field_types_are_validated(self):
        short = self.make_short()
        for body in [{'privacy': 'everyone'}, {'privacy': 5}, {'title': 5}, {'description': []},
                     {'tags': 'abc'}]:
            with self.subTest(body=body):
                self.assertEqual(self.upload(filename=short.name, **body).status_code, 400)
        self.uploader.upload_video.assert_not_called()

    def test_upload_requires_sign_in(self):
        short = self.make_short()
        self.uploader.is_authenticated.return_value = False
        self.assertEqual(self.upload(filename=short.name).status_code, 401)
        self.uploader.upload_video.assert_not_called()

    def test_videos_that_do_not_fit_shorts_are_rejected(self):
        short = self.make_short()
        self.uploader.validate_short_video.return_value = (False, 'Video too long: 90.0s (max 60s)')
        response = self.upload(filename=short.name)
        self.assertEqual(response.status_code, 400)
        self.assertIn('too long', response.get_json()['error'])

    def test_upload_failures_are_reported_as_bad_gateway(self):
        short = self.make_short()
        self.uploader.upload_video.return_value = (False, 'YouTube API error (403): quotaExceeded', None)
        response = self.upload(filename=short.name)
        self.assertEqual(response.status_code, 502)
        self.assertEqual(response.get_json()['error'], 'YouTube API error (403): quotaExceeded')

    def test_auth_status_reports_the_sign_in_state_without_side_effects(self):
        """Polling this must never start (and so invalidate) a sign-in in progress."""
        for signed_in in (True, False):
            with self.subTest(signed_in=signed_in):
                self.uploader.is_authenticated.return_value = signed_in
                response = self.client.get('/api/youtube-auth')
                self.assertEqual(response.get_json(), {'authenticated': signed_in})
        self.uploader.begin_auth.assert_not_called()

    def test_starting_sign_in_returns_the_consent_url(self):
        self.uploader.is_authenticated.return_value = False
        self.uploader.begin_auth.return_value = 'https://accounts.google.com/o/oauth2/auth?x=1'
        data = self.client.post('/api/youtube-auth/start').get_json()
        self.assertEqual(data, {'authenticated': False,
                                'auth_url': 'https://accounts.google.com/o/oauth2/auth?x=1'})

    def test_starting_sign_in_when_already_signed_in_does_not_restart_it(self):
        data = self.client.post('/api/youtube-auth/start').get_json()
        self.assertEqual(data, {'authenticated': True})
        self.uploader.begin_auth.assert_not_called()

    def test_starting_sign_in_reports_setup_problems(self):
        self.uploader.is_authenticated.return_value = False
        self.uploader.begin_auth.side_effect = YouTubeUploaderError('client_secrets.json not found.')
        response = self.client.post('/api/youtube-auth/start')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'client_secrets.json not found.')

    def test_starting_sign_in_is_not_available_as_a_get(self):
        self.assertEqual(self.client.get('/api/youtube-auth/start').status_code, 405)

    def test_oauth_callback_completes_sign_in(self):
        self.uploader.complete_auth.return_value = (True, 'Authentication completed successfully')
        response = self.client.get('/oauth2callback?code=code1&state=state1')
        self.assertEqual(response.status_code, 200)
        self.uploader.complete_auth.assert_called_once_with('code1', 'state1')
        self.assertIn('close this window', response.get_data(as_text=True).lower())

    def test_oauth_callback_failures_and_cancellation(self):
        self.uploader.complete_auth.return_value = (False, 'Sign-in state did not match.')
        self.assertEqual(self.client.get('/oauth2callback?code=c&state=bad').status_code, 400)

        self.uploader.complete_auth.reset_mock()
        for query in ['error=access_denied', 'state=only', 'code=only', '']:
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f'/oauth2callback?{query}').status_code, 400)
        self.uploader.complete_auth.assert_not_called()

    def test_oauth_callback_escapes_messages(self):
        self.uploader.complete_auth.return_value = (False, '<script>alert(1)</script>')
        body = self.client.get('/oauth2callback?code=c&state=s').get_data(as_text=True)
        self.assertNotIn('<script>alert(1)</script>', body)
        self.assertIn('&lt;script&gt;', body)

    def test_quota_info(self):
        self.uploader.get_upload_quota_info.return_value = {'docs_url': 'https://developers.google.com/'}
        self.assertIn('docs_url', self.client.get('/api/youtube-quota').get_json())


class TestRateLimitingDisabled(RouteTestCase):
    rate_limit_enabled = False

    def test_decorated_routes_work_when_rate_limiting_is_switched_off(self):
        """
        Regression: with RATE_LIMIT_ENABLED=false Flask-Limiter does not register
        itself on the app, so the app has to keep the Limiter alive.
        """
        import gc
        gc.collect()
        response = self.client.post('/api/video-info', json={})
        self.assertEqual(response.status_code, 400)  # 500 = limiter was garbage collected


class TestRateLimiting(RouteTestCase):
    rate_limit_enabled = True

    def test_expensive_routes_are_limited_with_a_json_429(self):
        statuses = [self.client.post('/api/create-short', json={}).status_code for _ in range(8)]
        self.assertIn(429, statuses)
        response = self.client.post('/api/create-short', json={})
        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.get_json()['success'])


class TestFileRoutesAreNotRateLimited(RouteTestCase):
    """A result page loads one image per frame (up to 50), and videos fetch in ranges."""
    rate_limit_enabled = True

    def test_serving_files_does_not_use_up_the_api_rate_limit(self):
        for path in ['/frames/missing.jpg', '/shorts/missing.mp4']:
            with self.subTest(path=path):
                statuses = {self.client.get(path).status_code for _ in range(60)}
                self.assertEqual(statuses, {404})


class TestJobs(RouteTestCase):
    """The pages start downloads and renders as background jobs and poll them."""

    def wait_for(self, job_id, states=('succeeded', 'failed', 'cancelled')):
        deadline = time.time() + 5
        while time.time() < deadline:
            job = self.client.get(f'/api/jobs/{job_id}').get_json()['job']
            if job['state'] in states:
                return job
            time.sleep(0.02)
        self.fail(f'job {job_id} did not reach {states}')

    def start(self, kind, body):
        response = self.client.post(f'/api/jobs/{kind}', json=body)
        self.assertEqual(response.status_code, 202, response.get_data(as_text=True))
        return response.get_json()['job']

    def test_an_extract_job_reports_progress_and_returns_the_frames(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.return_value = (True, None)

        started = self.start('extract', {'url': VALID_URL, 'timestamps': ['5', '1:10']})
        self.assertEqual((started['kind'], started['stage_count']), ('extract', 2))
        job = self.wait_for(started['id'])

        self.assertEqual(job['state'], 'succeeded')
        self.assertEqual([frame['timestamp'] for frame in job['result']['frames']], [5, 70])
        self.assertEqual(job['result']['url'], VALID_URL, 'a page picking the job up saves it under its link')
        self.assertEqual(job['progress'], 1)
        self.assertFalse(video.exists())
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'completed'))
        on_progress = self.extractor.download_video.call_args.kwargs['on_progress']
        self.assertTrue(callable(on_progress), 'the download reports its progress to the job')

    def test_bad_requests_are_rejected_before_a_job_starts(self):
        for kind, body in [('extract', {'url': VALID_URL, 'timestamps': ['1:60']}),
                           ('extract', {'url': 'https://example.com/x', 'timestamps': ['5']}),
                           ('create-short', {'url': VALID_URL, 'duration': 9999}),
                           ('create-short', {'url': VALID_URL, 'vertical_format': 'true'})]:
            with self.subTest(kind=kind, body=body):
                self.assertEqual(self.client.post(f'/api/jobs/{kind}', json=body).status_code, 400)
        self.extractor.download_video.assert_not_called()
        self.assertEqual(self.client.get('/api/jobs').get_json()['jobs'], [])

    def test_a_failed_download_fails_the_job_with_its_reason(self):
        self.extractor.download_video.return_value = (None, None, 'Video unavailable')
        job = self.wait_for(self.start('create-short', {'url': VALID_URL})['id'])
        self.assertEqual((job['state'], job['error']), ('failed', 'Video unavailable'))
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'failed'))

    def test_unexpected_errors_fail_the_job_without_details(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(media_jobs, 'create_short', side_effect=RuntimeError(r'C:\secret\path')):
            job = self.wait_for(self.start('create-short', {'url': VALID_URL})['id'])
        self.assertEqual(job['state'], 'failed')
        self.assertNotIn('secret', job['error'])
        self.assertFalse(video.exists())

    def test_a_render_can_be_cancelled_and_leaves_no_files(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        rendering = threading.Event()

        def endless_render(source, output, **kwargs):
            Path(output).write_bytes(b'partial')
            try:
                while True:  # like MoviePy: progress after every frame, until cancelled
                    rendering.set()
                    kwargs['on_progress'](0.5)
                    time.sleep(0.01)
            finally:
                Path(output).unlink(missing_ok=True)

        with patch.object(media_jobs, 'create_short', side_effect=endless_render):
            job_id = self.start('create-short', {'url': VALID_URL})['id']
            self.assertTrue(rendering.wait(5))
            running = self.client.get(f'/api/jobs/{job_id}').get_json()['job']
            self.assertEqual((running['state'], running['stage'], running['progress']), ('running', 'render', 0.5))

            cancel = self.client.post(f'/api/jobs/{job_id}/cancel')
            self.assertEqual(cancel.status_code, 200)
            job = self.wait_for(job_id)

        self.assertEqual(job['state'], 'cancelled')
        self.assertFalse(video.exists())
        self.assertEqual(list(self.shorts.iterdir()), [])
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'cancelled'))

    def test_cancelling_an_extraction_removes_the_frames_it_already_wrote(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        second_frame = threading.Event()

        def extract(path, seconds, output):
            Path(output).write_bytes(b'jpeg')
            if seconds == 70:
                second_frame.set()
                time.sleep(0.5)  # the cancel arrives while this frame is written
            return True, None

        self.extractor.extract_frame_at_timestamp.side_effect = extract
        job_id = self.start('extract', {'url': VALID_URL, 'timestamps': ['5', '1:10', '2:00']})['id']
        self.assertTrue(second_frame.wait(5))
        self.client.post(f'/api/jobs/{job_id}/cancel')
        self.assertEqual(self.wait_for(job_id)['state'], 'cancelled')
        self.assertEqual(list(self.frames.iterdir()), [])
        self.assertFalse(video.exists())

    def test_a_job_cancelled_before_it_starts_is_recorded_as_cancelled(self):
        registry = JobRegistry(max_workers=1)
        self.addCleanup(registry.shutdown)
        release = threading.Event()
        self.addCleanup(release.set)
        with patch.object(app_enhanced, 'job_registry', registry):
            registry.submit('short', ['render'], lambda reporter: release.wait(5) or {})
            waiting = self.start('create-short', {'url': VALID_URL})
            self.assertEqual(waiting['state'], 'queued')
            self.client.post(f"/api/jobs/{waiting['id']}/cancel")
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'cancelled'))
        self.extractor.download_video.assert_not_called()

    def test_too_many_waiting_jobs_are_refused_with_429(self):
        with patch.object(app_enhanced.job_registry, '_max_unfinished', 0):
            response = self.client.post('/api/jobs/extract', json={'url': VALID_URL, 'timestamps': ['5']})
        self.assertEqual(response.status_code, 429)
        self.assertFalse(response.get_json()['success'])
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'failed'))

    def test_unknown_and_malformed_job_ids_are_404(self):
        for job_id in ['0' * 32, 'not-a-job', '../etc']:
            with self.subTest(job_id=job_id):
                self.assertEqual(self.client.get(f'/api/jobs/{job_id}').status_code, 404)
                self.assertEqual(self.client.post(f'/api/jobs/{job_id}/cancel').status_code, 404)

    def test_jobs_are_listed_newest_first(self):
        self.extractor.download_video.return_value = (None, None, 'Video unavailable')
        first = self.start('extract', {'url': VALID_URL, 'timestamps': ['5']})['id']
        self.wait_for(first)
        second = self.start('create-short', {'url': VALID_URL})['id']
        self.wait_for(second)
        listed = [job['id'] for job in self.client.get('/api/jobs').get_json()['jobs']]
        self.assertEqual(listed[:2], [second, first])


class TestJobPollingIsNotRateLimited(RouteTestCase):
    """An open page asks about its job about once a second."""
    rate_limit_enabled = True

    def test_polling_does_not_use_up_the_api_rate_limit(self):
        statuses = {self.client.get('/api/jobs').status_code for _ in range(60)}
        statuses |= {self.client.get(f'/api/jobs/{"0" * 32}').status_code for _ in range(60)}
        self.assertEqual(statuses, {200, 404})


class TestStartupCleanup(RouteTestCase):
    """Leftovers are swept when the app is created, so gunicorn gets it too."""

    def test_creating_the_app_sweeps_old_files(self):
        self.extractor.cleanup_old_files.reset_mock()
        create_app()
        self.extractor.cleanup_old_files.assert_called_once()

    def test_renders_cut_off_by_a_stop_are_removed_at_startup(self):
        rendering = self.shorts / '.rendering'
        rendering.mkdir()
        (rendering / 'Clip_abcd1234_short.mp4').write_bytes(b'half a video')
        (rendering / 'Clip_abcd1234_short.tmp-audio.m4a').write_bytes(b'audio')
        create_app()
        self.assertEqual(list(rendering.iterdir()), [])

    def test_a_failing_sweep_does_not_prevent_startup(self):
        self.extractor.cleanup_old_files.side_effect = OSError('disk')
        app = create_app()
        self.assertEqual(app.test_client().get('/api/health').status_code, 200)


class TestMain(unittest.TestCase):
    def test_main_binds_to_the_configured_host(self):
        fake_app = Mock()
        with patch.object(app_enhanced, 'create_app', return_value=fake_app):
            app_enhanced.main()

        kwargs = fake_app.run.call_args.kwargs
        config = get_config()
        self.assertEqual((kwargs['host'], kwargs['port'], kwargs['debug']),
                         (config.HOST, config.PORT, config.DEBUG))

    def test_main_never_enables_the_debugger_unless_asked(self):
        fake_app = Mock()
        with patch.object(app_enhanced, 'create_app', return_value=fake_app), \
                patch.object(get_config(), 'DEBUG', False):
            app_enhanced.main()
        self.assertIs(fake_app.run.call_args.kwargs['debug'], False)


if __name__ == '__main__':
    unittest.main()
