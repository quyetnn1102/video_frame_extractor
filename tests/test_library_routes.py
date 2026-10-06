"""The library API: pages through every short, says which ones are in use or cannot go to YouTube."""
import threading
from unittest.mock import patch

import app_enhanced
import media_jobs
from jobs import NullReporter
from library import MediaInfo
from media_jobs import ExtractRequest
from tests.test_routes import VALID_URL, RouteTestCase


class LibraryRouteTestCase(RouteTestCase):
    def setUp(self):
        super().setUp()
        patcher = patch('library.read_media_info', return_value=MediaInfo(30.0, 1080, 1920))
        self.read_media_info = patcher.start()
        self.addCleanup(patcher.stop)

    def make_short(self, name):
        (self.shorts / name).write_bytes(b'video')
        return name


class TestLibraryPages(LibraryRouteTestCase):
    def test_a_page_says_how_many_shorts_there_are_in_all(self):
        for index in range(5):
            self.make_short(f'Clip{index}_1a2b3c4d_short.mp4')
        data = self.client.get('/api/shorts?limit=2&offset=2').get_json()
        self.assertEqual((len(data['shorts']), data['total'], data['offset'], data['limit']), (2, 5, 2, 2))

    def test_bad_page_parameters_are_refused(self):
        for query in ('limit=0', 'limit=500', 'limit=abc', 'offset=-1', 'offset=1.5'):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/shorts?' + query).status_code, 400)

    def test_shorts_youtube_would_refuse_carry_the_reason(self):
        self.make_short('Wide_1a2b3c4d_short.mp4')
        self.read_media_info.return_value = MediaInfo(30.0, 1920, 1080)
        item = self.client.get('/api/shorts').get_json()['shorts'][0]
        self.assertIn('aspect ratio', item['upload_problem'])
        self.assertFalse(item['busy'])


class TestShortsInUse(LibraryRouteTestCase):
    def test_a_short_being_subtitled_is_marked_and_cannot_be_deleted(self):
        name = self.make_short('Clip_1a2b3c4d_short.mp4')
        release = threading.Event()
        with patch.object(media_jobs, 'add_vietnamese_subtitles',
                          side_effect=lambda path, reporter: release.wait(5) and {'success': True}):
            self.assertEqual(self.client.post('/api/jobs/subtitles', json={'filename': name}).status_code, 202)
            item = self.client.get('/api/shorts').get_json()['shorts'][0]
            refused = self.client.post('/api/shorts/delete', json={'filename': name})
            release.set()
        self.assertTrue(item['busy'])
        self.assertEqual(refused.status_code, 409)
        self.assertIn('in use', refused.get_json()['error'])
        self.assertTrue((self.shorts / name).exists())

    def test_a_short_being_uploaded_is_in_use_until_the_upload_ends(self):
        name = self.make_short('Clip_1a2b3c4d_short.mp4')
        with app_enhanced.uploading(name):
            self.assertIn(name, app_enhanced.shorts_in_use())
        self.assertNotIn(name, app_enhanced.shorts_in_use())


class TestFrameWarnings(RouteTestCase):
    def test_each_failed_timecode_gets_one_readable_line(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.side_effect = [
            (True, None), (False, 'no frame there (it may be past the end of the video)')]
        result = media_jobs.extract_frames(ExtractRequest(VALID_URL, 'youtube', (5, 85)), 0, NullReporter())
        self.assertEqual(result['warnings'], ['1:25: no frame there (it may be past the end of the video)'])

    def test_when_every_timecode_fails_the_message_stays_short(self):
        video = self.make_download()
        self.extractor.download_video.return_value = (str(video), 'Title', None)
        self.extractor.extract_frame_at_timestamp.return_value = (False, 'no frame there')
        with self.assertRaises(media_jobs.JobFailed) as raised:
            media_jobs.extract_frames(ExtractRequest(VALID_URL, 'youtube', tuple(range(10))), 0, NullReporter())
        self.assertTrue(raised.exception.message.startswith('No frames could be extracted. 0:00: no frame there'))
        self.assertTrue(raised.exception.message.endswith('and 7 more'))
