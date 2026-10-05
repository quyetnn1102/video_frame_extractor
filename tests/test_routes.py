"""Contract tests for the Flask app: routes, security headers and error handling."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import app_enhanced
from app_enhanced import create_app
from config import get_config
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
        for name, value in [('FRAMES_FOLDER', self.frames), ('SHORTS_FOLDER', self.shorts),
                            ('DOWNLOAD_FOLDER', self.downloads),
                            ('RATELIMIT_ENABLED', self.rate_limit_enabled)]:
            patcher = patch.object(config, name, value, create=True)
            patcher.start()
            self.addCleanup(patcher.stop)

        self.extractor = self.patch_module('extractor')
        self.uploader = self.patch_module('youtube_uploader')
        self.db = self.patch_module('db_manager')
        self.db.log_video_request.return_value = 7

        self.app = create_app()
        self.client = self.app.test_client()

    def patch_module(self, name):
        patcher = patch.object(app_enhanced, name, Mock())
        mocked = patcher.start()
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
                               ('127.0.0.1.evil.com', 400), ('192.168.1.10:5000', 400)]:
            with self.subTest(host=host):
                response = self.client.get('/api/health', headers={'Host': host})
                self.assertEqual(response.status_code, expected)

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
        for path in ['/', '/trending', '/create-short']:
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

        self.assertIn(response.status_code, (400, 500))
        self.assertFalse(video.exists())

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

        with patch.object(app_enhanced, 'create_short', side_effect=self.fake_render) as render:
            data = self.post(vertical_format=True, text_overlay={'text': 'Hi'}).get_json()

        self.assertTrue(data['success'])
        self.assertRegex(data['filename'], r'^[\w -]+_[0-9a-f]{8}_short\.mp4$')
        self.assertNotIn(':', data['filename'])
        self.assertNotIn('/', data['filename'])
        self.assertEqual(data['download_url'], '/shorts/' + data['filename'])
        self.assertEqual((data['quality'], data['duration'], data['start_time']), ('low', 20, 30))
        self.assertEqual(data['file_size'], len(b'rendered-short'))
        self.assertTrue((self.shorts / data['filename']).exists())
        self.assertFalse(video.exists())

        kwargs = render.call_args.kwargs
        self.assertEqual((kwargs['start'], kwargs['duration'], kwargs['vertical']), (30, 20, True))
        self.assertEqual(kwargs['text_overlay']['text'], 'Hi')
        self.assertEqual(self.db.update_video_request.call_args.args[:2], (7, 'completed'))

    def test_legacy_overlay_text_field_is_still_accepted(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(app_enhanced, 'create_short', side_effect=self.fake_render) as render:
            self.post(overlay_text='Legacy')
        self.assertEqual(render.call_args.kwargs['text_overlay']['text'], 'Legacy')

    def test_download_failure_is_a_client_error_with_the_reason(self):
        self.extractor.download_video.return_value = (None, None, 'Video unavailable')
        response = self.post()
        self.assertEqual((response.status_code, response.get_json()['error']), (400, 'Video unavailable'))

    def test_render_problems_are_reported_and_the_download_is_removed(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(app_enhanced, 'create_short',
                          side_effect=ShortVideoError('Start time (30s) exceeds video duration (10.0s)')):
            response = self.post()
        self.assertEqual(response.status_code, 400)
        self.assertIn('exceeds video duration', response.get_json()['error'])
        self.assertFalse(video.exists())

    def test_unexpected_render_errors_are_generic_and_the_download_is_removed(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'T', None)
        with patch.object(app_enhanced, 'create_short', side_effect=RuntimeError(r'C:\secret\path')):
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

        with patch.object(app_enhanced, 'create_short', side_effect=render):
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

    def test_auth_status_when_signed_in(self):
        self.assertEqual(self.client.get('/api/youtube-auth').get_json(), {'authenticated': True})

    def test_auth_returns_the_consent_url_when_signed_out(self):
        self.uploader.is_authenticated.return_value = False
        self.uploader.begin_auth.return_value = 'https://accounts.google.com/o/oauth2/auth?x=1'
        data = self.client.get('/api/youtube-auth').get_json()
        self.assertEqual(data, {'authenticated': False,
                                'auth_url': 'https://accounts.google.com/o/oauth2/auth?x=1'})

    def test_auth_reports_setup_problems(self):
        self.uploader.is_authenticated.return_value = False
        self.uploader.begin_auth.side_effect = YouTubeUploaderError('client_secrets.json not found.')
        response = self.client.get('/api/youtube-auth')
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()['error'], 'client_secrets.json not found.')

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


class TestMain(unittest.TestCase):
    def test_main_binds_to_the_configured_host_and_cleans_up_first(self):
        fake_app = Mock()
        with patch.object(app_enhanced, 'create_app', return_value=fake_app), \
                patch.object(app_enhanced, 'extractor') as extractor:
            extractor.cleanup_old_files.return_value = (0, 0, [])
            app_enhanced.main()

        extractor.cleanup_old_files.assert_called_once()
        kwargs = fake_app.run.call_args.kwargs
        config = get_config()
        self.assertEqual((kwargs['host'], kwargs['port'], kwargs['debug']),
                         (config.HOST, config.PORT, config.DEBUG))
        self.assertEqual(config.HOST, '127.0.0.1')

    def test_startup_cleanup_failures_do_not_prevent_startup(self):
        fake_app = Mock()
        with patch.object(app_enhanced, 'create_app', return_value=fake_app), \
                patch.object(app_enhanced, 'extractor') as extractor:
            extractor.cleanup_old_files.side_effect = OSError('disk')
            app_enhanced.main()
        fake_app.run.assert_called_once()


if __name__ == '__main__':
    unittest.main()
