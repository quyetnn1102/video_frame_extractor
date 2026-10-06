"""The library API: pages through every short, says which ones are in use or cannot go to YouTube."""
import threading
from unittest.mock import patch

import app_enhanced
import library_api
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
        for query in ('limit=0', 'limit=500', 'limit=abc', 'offset=-1', 'offset=1.5', 'limit=%C2%B2',
                      'offset=99999999'):
            with self.subTest(query=query):
                self.assertEqual(self.client.get('/api/shorts?' + query).status_code, 400)

    def test_shorts_youtube_would_refuse_carry_the_reason(self):
        self.make_short('Wide_1a2b3c4d_short.mp4')
        self.read_media_info.return_value = MediaInfo(30.0, 1920, 1080)
        item = self.client.get('/api/shorts').get_json()['shorts'][0]
        self.assertIn('aspect ratio', item['upload_problem'])
        self.assertFalse(item['busy'])


class TestLibraryPage(LibraryRouteTestCase):
    def test_your_shorts_has_its_own_page(self):
        page = self.client.get('/shorts')
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="resultsContent"', page.get_data(as_text=True))

    def test_subtitled_and_uploaded_shorts_say_so(self):
        self.make_short('Clip Vietsub_1a2b3c4d_short.mp4')
        self.make_short('Clip_5e6f7a8b_short.mp4')
        self.db.get_uploads.return_value = {'Clip_5e6f7a8b_short.mp4': {'video_id': 'vid9', 'privacy': 'private'}}
        items = {item['filename']: item for item in self.client.get('/api/shorts').get_json()['shorts']}
        self.assertTrue(items['Clip Vietsub_1a2b3c4d_short.mp4']['subtitled'])
        self.assertIsNone(items['Clip Vietsub_1a2b3c4d_short.mp4']['youtube_url'])
        self.assertFalse(items['Clip_5e6f7a8b_short.mp4']['subtitled'])
        self.assertEqual(items['Clip_5e6f7a8b_short.mp4']['youtube_url'], 'https://www.youtube.com/watch?v=vid9')


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
        with library_api.uploading(name):
            with library_api.uploading(name):  # a second upload of the same short
                pass
            self.assertIn(name, library_api.shorts_in_use(app_enhanced.job_registry),
                          'still in use while the first upload runs')
        self.assertNotIn(name, library_api.shorts_in_use(app_enhanced.job_registry))


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


class TestPhaseFiveRequests(RouteTestCase):
    def test_frames_can_be_png_and_are_served_and_zipped(self):
        from media_jobs import parse_extract_request
        request, error = parse_extract_request({'url': VALID_URL, 'timestamps': ['5'], 'format': 'png'})
        self.assertEqual((request.image_format, error), ('png', None))
        self.assertIn('format must be one of', parse_extract_request(
            {'url': VALID_URL, 'timestamps': ['5'], 'format': 'gif'})[1])
        (self.frames / 'frame_5s_1a2b3c4d.png').write_bytes(b'png')
        self.assertEqual(self.client.get('/frames/frame_5s_1a2b3c4d.png').status_code, 200)
        archive = self.client.post('/api/frames/archive', json={'filenames': ['frame_5s_1a2b3c4d.png']})
        self.assertEqual(archive.status_code, 200)

    def test_the_same_moment_twice_is_extracted_once(self):
        from media_jobs import parse_extract_request
        request, _ = parse_extract_request({'url': VALID_URL, 'timestamps': ['90', '0:05', '1:30']})
        self.assertEqual(request.seconds, (90, 5))

    def test_the_crop_position_reaches_the_render(self):
        from media_jobs import parse_short_request
        request, _ = parse_short_request({'url': VALID_URL, 'vertical_format': True, 'crop_position': 0.2})
        self.assertEqual(request.crop_position, 0.2)
        self.assertIn('Crop position', parse_short_request({'url': VALID_URL, 'crop_position': 2})[1])

    def test_quality_labels_match_the_bitrates_the_server_uses(self):
        from short_video import QUALITY_BITRATES
        page = self.client.get('/create-short').get_data(as_text=True)
        for name, bitrate in QUALITY_BITRATES.items():
            megabits = int(bitrate.rstrip('k')) // 1000
            with self.subTest(quality=name):
                self.assertRegex(page, rf'<option value="{name}"[^>]*>[^<]*{megabits} Mbit/s')


class TestPageShortcuts(RouteTestCase):
    def test_trending_offers_every_category_the_server_knows(self):
        from trending import VIDEO_CATEGORIES
        page = self.client.get('/trending').get_data(as_text=True)
        for category_id in VIDEO_CATEGORIES:
            self.assertIn(f'<option value="{category_id}">', page)

    def test_the_top_bar_shortcut_appears_only_where_it_adds_something(self):
        """Home has its own launcher and Trending cards their own actions."""
        for path, expected in [('/', None), ('/trending', None), ('/create-short', 'href="/extract"'),
                               ('/extract', 'href="/create-short">Create short'), ('/shorts', 'New short')]:
            with self.subTest(path=path):
                page = self.client.get(path).get_data(as_text=True)
                actions = page.split('class="topbar-actions">')[1].split('</div>')[0]
                if expected is None:
                    self.assertNotIn('<a ', actions)
                else:
                    self.assertIn(expected, actions)
