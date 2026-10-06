"""Tests for youtube_uploader.py: credential storage, OAuth state and uploads."""
import json
import os
import pickle
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import httplib2
import numpy as np
from googleapiclient.errors import HttpError

import youtube_uploader as module
from youtube_uploader import YouTubeUploader, YouTubeUploaderError, normalize_tags

CREDENTIALS_INFO = {
    'token': 'access-token', 'refresh_token': 'refresh-token',
    'client_id': 'client-id', 'client_secret': 'client-secret',
    'token_uri': 'https://oauth2.googleapis.com/token',
    'scopes': YouTubeUploader.YOUTUBE_UPLOAD_SCOPE,
}


def http_error(status, message=None):
    content = json.dumps({'error': {'message': message}}).encode() if message else b'{}'
    return HttpError(httplib2.Response({'status': str(status)}), content)


class UploaderTestCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.secrets_file = self.folder / 'client_secrets.json'
        self.credentials_file = self.folder / 'youtube_credentials.json'
        self.uploader = YouTubeUploader(
            client_secrets_file=self.secrets_file,
            credentials_file=self.credentials_file,
            redirect_uri='http://localhost:5000/oauth2callback',
        )
        self.uploader._sleep = Mock()


class TestCredentialStorage(UploaderTestCase):
    def test_credentials_are_saved_as_json_not_pickle(self):
        credentials = Mock()
        credentials.to_json.return_value = json.dumps(CREDENTIALS_INFO)

        self.uploader._save_credentials(credentials)

        self.assertEqual(json.loads(self.credentials_file.read_text()), CREDENTIALS_INFO)
        self.assertFalse(self.credentials_file.with_suffix('.pickle').exists())

    @unittest.skipIf(os.name == 'nt', 'POSIX permission bits are not meaningful on Windows')
    def test_credentials_file_is_owner_only(self):
        credentials = Mock()
        credentials.to_json.return_value = '{}'
        self.uploader._save_credentials(credentials)
        self.assertEqual(self.credentials_file.stat().st_mode & 0o777, 0o600)

    def test_saving_leaves_no_temporary_files(self):
        credentials = Mock()
        credentials.to_json.return_value = json.dumps(CREDENTIALS_INFO)
        self.uploader._save_credentials(credentials)
        self.assertEqual([path.name for path in self.folder.iterdir()], [self.credentials_file.name])

    def test_a_failed_save_keeps_the_previous_credentials(self):
        """The write is atomic: a crash half-way must not leave a corrupt file behind."""
        self.credentials_file.write_text(json.dumps(CREDENTIALS_INFO))
        credentials = Mock()
        credentials.to_json.side_effect = RuntimeError('serialisation failed')

        with self.assertRaises(RuntimeError):
            self.uploader._save_credentials(credentials)

        self.assertEqual(json.loads(self.credentials_file.read_text()), CREDENTIALS_INFO)
        self.assertEqual([path.name for path in self.folder.iterdir()], [self.credentials_file.name])

    def test_a_failed_save_is_reported(self):
        self.uploader.credentials_file = self.folder / 'missing-dir' / 'creds.json'
        with self.assertRaises(YouTubeUploaderError):
            self.uploader._save_credentials(Mock(to_json=Mock(return_value='{}')))

    def test_saved_credentials_round_trip(self):
        self.credentials_file.write_text(json.dumps(CREDENTIALS_INFO))
        credentials = self.uploader._load_credentials()
        self.assertEqual(credentials.refresh_token, 'refresh-token')

    def test_corrupt_credentials_are_ignored(self):
        self.credentials_file.write_text('{not json')
        self.assertIsNone(self.uploader._load_credentials())

    def test_legacy_pickle_files_are_never_unpickled(self):
        marker = self.folder / 'pickle-was-executed'

        class Malicious:
            def __reduce__(self):
                return (open, (str(marker), 'w'))

        self.credentials_file.with_suffix('.pickle').write_bytes(pickle.dumps(Malicious()))

        self.assertIsNone(self.uploader._load_credentials())
        self.assertFalse(marker.exists())


class TestIsAuthenticated(UploaderTestCase):
    def test_false_without_saved_credentials(self):
        self.assertFalse(self.uploader.is_authenticated())

    def test_true_with_valid_credentials_builds_the_service(self):
        with patch.object(self.uploader, '_load_credentials', return_value=Mock(valid=True)), \
                patch.object(module, 'build') as build:
            self.assertTrue(self.uploader.is_authenticated())
        self.assertIs(self.uploader.youtube_service, build.return_value)

    def test_expired_credentials_are_refreshed_and_saved(self):
        credentials = Mock(valid=False, expired=True, refresh_token='r')
        with patch.object(self.uploader, '_load_credentials', return_value=credentials), \
                patch.object(self.uploader, '_save_credentials') as save, \
                patch.object(module, 'build'):
            self.assertTrue(self.uploader.is_authenticated())
        credentials.refresh.assert_called_once()
        save.assert_called_once_with(credentials)

    def test_failed_refresh_means_not_authenticated(self):
        credentials = Mock(valid=False, expired=True, refresh_token='r')
        credentials.refresh.side_effect = RuntimeError('revoked')
        with patch.object(self.uploader, '_load_credentials', return_value=credentials):
            self.assertFalse(self.uploader.is_authenticated())

    def test_invalid_credentials_without_refresh_token_are_rejected(self):
        credentials = Mock(valid=False, expired=True, refresh_token=None)
        with patch.object(self.uploader, '_load_credentials', return_value=credentials):
            self.assertFalse(self.uploader.is_authenticated())


class TestOAuthFlow(UploaderTestCase):
    def setUp(self):
        super().setUp()
        self.secrets_file.write_text('{}')
        self.flow = Mock()
        self.flow.authorization_url.return_value = ('https://accounts.google.com/auth?x=1', 'STATE-1')
        self.flow.credentials.to_json.return_value = json.dumps(CREDENTIALS_INFO)
        flow_class = Mock()
        flow_class.from_client_secrets_file.return_value = self.flow
        patcher = patch.object(module, '_flow_class', return_value=flow_class)
        self.flow_class = flow_class
        patcher.start()
        self.addCleanup(patcher.stop)
        build = patch.object(module, 'build')
        build.start()
        self.addCleanup(build.stop)

    def test_begin_auth_requires_the_client_secrets_file(self):
        self.secrets_file.unlink()
        with self.assertRaises(YouTubeUploaderError):
            self.uploader.begin_auth()

    def test_begin_auth_returns_the_consent_url_with_the_configured_redirect(self):
        url = self.uploader.begin_auth()

        self.assertEqual(url, 'https://accounts.google.com/auth?x=1')
        kwargs = self.flow_class.from_client_secrets_file.call_args.kwargs
        self.assertEqual(kwargs['redirect_uri'], 'http://localhost:5000/oauth2callback')
        self.assertEqual(kwargs['scopes'], YouTubeUploader.YOUTUBE_UPLOAD_SCOPE)

    def test_pkce_is_requested_explicitly(self):
        """
        google-auth-oauthlib 1.2.2's from_client_secrets_file passes
        autogenerate_code_verifier=None to Flow unless told otherwise (the True
        default only applies to calling Flow() directly), which turns PKCE off.
        """
        self.uploader.begin_auth()
        kwargs = self.flow_class.from_client_secrets_file.call_args.kwargs
        self.assertIs(kwargs.get('autogenerate_code_verifier'), True)

    def test_complete_auth_with_the_right_state_saves_credentials(self):
        self.uploader.begin_auth()

        ok, message = self.uploader.complete_auth('the-code', 'STATE-1')

        self.assertTrue(ok, message)
        self.flow.fetch_token.assert_called_once_with(code='the-code')
        self.assertEqual(json.loads(self.credentials_file.read_text()), CREDENTIALS_INFO)

    def test_a_wrong_state_is_rejected_without_ending_the_real_sign_in(self):
        """Anyone able to hit the callback must not be able to cancel the user's sign-in."""
        self.uploader.begin_auth()

        for forged in ['FORGED', '', 'STATE-', 'STATE-1 ', 'é', 'état-1', None, 5]:
            with self.subTest(state=forged):
                ok, _ = self.uploader.complete_auth('the-code', forged)
                self.assertFalse(ok)
        self.flow.fetch_token.assert_not_called()

        ok, message = self.uploader.complete_auth('the-code', 'STATE-1')  # the real one still works
        self.assertTrue(ok, message)

    def test_a_successful_sign_in_attempt_is_single_use(self):
        self.uploader.begin_auth()
        self.assertTrue(self.uploader.complete_auth('the-code', 'STATE-1')[0])
        self.assertFalse(self.uploader.complete_auth('the-code', 'STATE-1')[0])
        self.flow.fetch_token.assert_called_once()

    def test_two_concurrent_callbacks_complete_the_sign_in_only_once(self):
        import threading
        self.uploader.begin_auth()
        results = []
        barrier = threading.Barrier(8)

        def callback():
            barrier.wait()
            results.append(self.uploader.complete_auth('the-code', 'STATE-1')[0])

        threads = [threading.Thread(target=callback) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        self.assertEqual(results.count(True), 1)
        self.flow.fetch_token.assert_called_once()

    def test_complete_auth_without_a_pending_sign_in_fails(self):
        ok, _ = self.uploader.complete_auth('the-code', 'STATE-1')
        self.assertFalse(ok)

    def test_complete_auth_rejects_non_string_state_and_empty_code(self):
        self.uploader.begin_auth()
        self.assertFalse(self.uploader.complete_auth('code', None)[0])
        self.uploader.begin_auth()
        self.assertFalse(self.uploader.complete_auth('', 'STATE-1')[0])

    def test_pending_sign_in_expires(self):
        with patch.object(module.time, 'monotonic', side_effect=[0, module.AUTH_TIMEOUT_SECONDS + 1]):
            self.uploader.begin_auth()
            ok, _ = self.uploader.complete_auth('the-code', 'STATE-1')
        self.assertFalse(ok)

    def test_token_exchange_failure_gives_a_generic_message(self):
        self.flow.fetch_token.side_effect = RuntimeError('secret detail from the server')
        self.uploader.begin_auth()

        ok, message = self.uploader.complete_auth('the-code', 'STATE-1')

        self.assertFalse(ok)
        self.assertNotIn('secret detail', message)

    def test_missing_oauth_library_is_reported_clearly(self):
        with patch.object(module, '_flow_class', side_effect=YouTubeUploaderError('not installed')):
            with self.assertRaises(YouTubeUploaderError):
                self.uploader.begin_auth()


class TestUpload(UploaderTestCase):
    def setUp(self):
        super().setUp()
        self.video = self.folder / 'short.mp4'
        self.video.write_bytes(b'0' * 64)
        self.service = Mock()
        self.insert = self.service.videos.return_value.insert
        self.insert.return_value.next_chunk.return_value = (None, {'id': 'abc123'})
        self.uploader.youtube_service = self.service

    def upload(self, **overrides):
        arguments = dict(video_path=str(self.video), title='Title')
        arguments.update(overrides)
        return self.uploader.upload_video(**arguments)

    def test_successful_upload_returns_the_video_id(self):
        ok, message, video_id = self.upload()
        self.assertTrue(ok, message)
        self.assertEqual(video_id, 'abc123')

    def test_upload_defaults_to_private_and_marks_shorts(self):
        self.upload(description='My clip')
        body = self.insert.call_args.kwargs['body']
        self.assertEqual(body['status']['privacyStatus'], 'private')
        self.assertIn('#Shorts', body['snippet']['description'])

    def test_unknown_privacy_values_are_rejected_before_any_upload(self):
        for value in ['PUBLIC', 'everyone', None, 5, '']:
            with self.subTest(value=value):
                ok, _, video_id = self.upload(privacy_status=value)
                self.assertFalse(ok)
                self.assertIsNone(video_id)
        self.insert.assert_not_called()

    def test_title_description_and_tags_are_limited(self):
        self.upload(title='t' * 500, description='d' * 9000, tags=['ok', 5, '<b>x</b>', 'y' * 600])
        snippet = self.insert.call_args.kwargs['body']['snippet']
        self.assertEqual(len(snippet['title']), module.TITLE_LIMIT)
        self.assertLessEqual(len(snippet['description']), module.DESCRIPTION_LIMIT)
        self.assertEqual(snippet['tags'], ['ok', 'bx/b'])

    def test_the_shorts_tag_survives_a_very_long_description(self):
        self.upload(description='d' * 9000)
        description = self.insert.call_args.kwargs['body']['snippet']['description']
        self.assertLessEqual(len(description), module.DESCRIPTION_LIMIT)
        self.assertTrue(description.endswith('#Shorts'))

    def test_an_existing_shorts_tag_is_not_duplicated(self):
        self.upload(description='My clip #Shorts')
        description = self.insert.call_args.kwargs['body']['snippet']['description']
        self.assertEqual(description.count('#Shorts'), 1)

    def test_blank_title_gets_a_default(self):
        self.upload(title='   ')
        self.assertEqual(self.insert.call_args.kwargs['body']['snippet']['title'], module.DEFAULT_TITLE)

    def test_requires_authentication(self):
        self.uploader.youtube_service = None
        ok, message, _ = self.upload()
        self.assertFalse(ok)
        self.assertIn('Authentication required', message)

    def test_missing_file_does_not_reveal_the_server_path(self):
        ok, message, _ = self.upload(video_path=str(self.folder / 'nope.mp4'))
        self.assertFalse(ok)
        self.assertNotIn(str(self.folder), message)

    def test_server_errors_are_retried_with_backoff(self):
        self.insert.return_value.next_chunk.side_effect = [http_error(503), (None, {'id': 'abc123'})]
        ok, _, video_id = self.upload()
        self.assertTrue(ok)
        self.assertEqual(video_id, 'abc123')
        self.uploader._sleep.assert_called_once()

    def test_retries_are_bounded(self):
        self.insert.return_value.next_chunk.side_effect = [http_error(503)] * 10
        ok, _, _ = self.upload()
        self.assertFalse(ok)
        self.assertEqual(self.insert.return_value.next_chunk.call_count, module.UPLOAD_MAX_RETRIES + 1)

    def test_client_errors_are_not_retried_and_explain_the_cause(self):
        self.insert.return_value.next_chunk.side_effect = http_error(403, 'quotaExceeded')
        ok, message, _ = self.upload()
        self.assertFalse(ok)
        self.assertEqual(message, 'YouTube API error (403): quotaExceeded')
        self.assertEqual(self.insert.return_value.next_chunk.call_count, 1)

    def test_unexpected_errors_do_not_leak_details(self):
        self.insert.return_value.next_chunk.side_effect = RuntimeError('token=abc123')
        ok, message, _ = self.upload()
        self.assertFalse(ok)
        self.assertNotIn('abc123', message)


class TestNormalizeTags(unittest.TestCase):
    def test_non_lists_fall_back_to_defaults(self):
        for value in [None, 'tag', 5, {'a': 1}]:
            with self.subTest(value=value):
                self.assertEqual(normalize_tags(value), module.DEFAULT_TAGS)

    def test_filters_and_cleans_tags(self):
        self.assertEqual(normalize_tags(['a', '', '  ', 7, ' b ', '<c>']), ['a', 'b', 'c'])

    def test_total_length_is_capped(self):
        tags = normalize_tags(['x' * 200] * 5)
        self.assertLessEqual(sum(len(tag) for tag in tags), module.TAGS_CHARACTER_LIMIT)


class TestValidateShortVideo(UploaderTestCase):
    def make_video(self, size, seconds=2, fps=10):
        path = self.folder / f'{size[0]}x{size[1]}.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, size)
        for _ in range(seconds * fps):
            writer.write(np.zeros((size[1], size[0], 3), dtype=np.uint8))
        writer.release()
        return path

    def test_vertical_and_square_videos_are_valid(self):
        for size in [(48, 80), (64, 64)]:
            with self.subTest(size=size):
                ok, message = self.uploader.validate_short_video(str(self.make_video(size)))
                self.assertTrue(ok, message)

    def test_landscape_videos_are_rejected(self):
        ok, message = self.uploader.validate_short_video(str(self.make_video((80, 48))))
        self.assertFalse(ok)
        self.assertIn('aspect ratio', message)

    def test_unreadable_files_are_rejected(self):
        broken = self.folder / 'broken.mp4'
        broken.write_bytes(b'not a video')
        ok, _ = self.uploader.validate_short_video(str(broken))
        self.assertFalse(ok)


class TestQuotaInfo(UploaderTestCase):
    def test_points_to_the_official_quota_page_without_invented_numbers(self):
        info = self.uploader.get_upload_quota_info()
        self.assertTrue(info['docs_url'].startswith('https://developers.google.com/'))
        self.assertNotIn('1600', json.dumps(info))


class TestShortsProblem(unittest.TestCase):
    def test_what_youtube_would_refuse_is_named(self):
        from youtube_uploader import shorts_problem
        self.assertIn('too long', shorts_problem(61, 1080, 1920))
        self.assertIn('aspect ratio', shorts_problem(30, 1920, 1080))
        self.assertIsNone(shorts_problem(60, 1080, 1920))
        self.assertIsNone(shorts_problem(60.03, 1080, 1920), 'a 60 s render at 29.97 fps lasts 60.03 s')
        self.assertIsNone(shorts_problem(30, 1080, 1080), 'square videos are accepted')
        self.assertIsNone(shorts_problem(None, None, None), 'unknown values are checked at upload')


if __name__ == '__main__':
    unittest.main()
