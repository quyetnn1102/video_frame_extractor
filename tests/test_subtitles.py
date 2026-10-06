"""Vietnamese subtitles: finding and blurring burned-in text, drawing new text, the job, the route."""
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import cv2
import numpy as np

import media_jobs
import subtitles
from jobs import JobFailed, NullReporter
from subtitles import Cue, SubtitleError
from tests.test_routes import RouteTestCase
from translation import TranslationError

WIDTH, HEIGHT = 360, 640
TEXT_ROW = 560  # baseline of the burned-in subtitle, in the lower part like Douyin's


def frame(with_text=False, row=TEXT_ROW, shade=90):
    """An RGB frame; the 'subtitle' is white text with a thick black outline."""
    image = np.full((HEIGHT, WIDTH, 3), shade, dtype=np.uint8)
    if with_text:
        for color, thickness in (((0, 0, 0), 8), ((255, 255, 255), 3)):
            cv2.putText(image, 'SUBTITLE', (30, row), cv2.FONT_HERSHEY_SIMPLEX, 1.6, color, thickness)
    return image


def outlined_text_pixels(image, band):
    gray = cv2.cvtColor(image[band[0]:band[1]], cv2.COLOR_RGB2GRAY)
    near_dark = cv2.dilate((gray < 60).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    return int(((gray > 200) & near_dark).sum())


class TestFindSubtitleBand(unittest.TestCase):
    def test_the_rows_of_changing_subtitles_are_found(self):
        frames = [frame(with_text=index % 2 == 0) for index in range(12)]
        band = subtitles.find_subtitle_band(frames)
        self.assertIsNotNone(band)
        top, bottom = band
        self.assertLess(top, TEXT_ROW - 30)
        self.assertGreater(bottom, TEXT_ROW)
        self.assertLess(bottom - top, HEIGHT * 0.15)

    def test_a_video_without_subtitles_has_no_band(self):
        self.assertIsNone(subtitles.find_subtitle_band([frame() for _ in range(6)]))
        self.assertIsNone(subtitles.find_subtitle_band([]))

    def test_titles_in_the_upper_half_are_left_alone(self):
        self.assertIsNone(subtitles.find_subtitle_band([frame(with_text=True, row=120) for _ in range(6)]))

    def test_fine_bright_detail_everywhere_is_not_mistaken_for_subtitles(self):
        noise = np.random.default_rng(1).choice([0, 255], size=(HEIGHT, WIDTH, 1)).astype(np.uint8)
        self.assertIsNone(subtitles.find_subtitle_band([np.repeat(noise, 3, axis=2)] * 4))


class TestCover(unittest.TestCase):
    band = (TEXT_ROW - 50, TEXT_ROW + 20)

    def test_blurring_hides_the_text_and_touches_only_the_band(self):
        original = frame(with_text=True)
        before = original.copy()
        blurred = subtitles.blur_band(original, self.band)
        np.testing.assert_array_equal(original, before, 'the input frame is not changed')
        self.assertGreater(outlined_text_pixels(original, self.band), 100)
        self.assertEqual(outlined_text_pixels(blurred, self.band), 0)
        np.testing.assert_array_equal(blurred[:self.band[0]], original[:self.band[0]])
        np.testing.assert_array_equal(blurred[self.band[1]:], original[self.band[1]:])

    def test_only_frames_showing_text_are_blurred_and_briefly_after(self):
        cover = subtitles.SubtitleCover(self.band)
        text, plain = frame(with_text=True), frame()
        self.assertIsNot(cover.apply(text, 1.0), text)
        self.assertIsNot(cover.apply(plain, 1.0 + subtitles.COVER_HOLD_SECONDS / 2), plain,
                         'a subtitle fading out does not make the blur flicker')
        self.assertIs(cover.apply(plain, 2.0 + subtitles.COVER_HOLD_SECONDS), plain)

    def test_a_band_on_the_bottom_edge_is_blurred_to_the_last_row(self):
        original = frame(with_text=True, row=HEIGHT - 4)
        band = (HEIGHT - 60, HEIGHT)
        blurred = subtitles.blur_band(original, band)
        self.assertEqual(outlined_text_pixels(blurred, band), 0)
        self.assertGreater(np.abs(blurred[-1].astype(int) - original[-1]).mean(), 5)

    def test_going_back_in_time_forgets_the_hold(self):
        cover = subtitles.SubtitleCover(self.band)
        cover.apply(frame(with_text=True), 5.0)
        plain = frame()
        self.assertIs(cover.apply(plain, 1.0), plain)


class TestCaptions(unittest.TestCase):
    def test_a_long_line_is_wrapped_and_kept_inside_the_frame(self):
        text = 'Có được mũ triều thiên hạnh phúc thật sự sẽ là một bước đi êm đẹp cho tất cả chúng ta'
        font, lines = subtitles.fit_text(text, 1080, 1920)
        self.assertLessEqual(len(lines), subtitles.MAX_LINES)
        self.assertEqual(' '.join(lines), text)
        for line in lines:
            self.assertLessEqual(font.getlength(line), 1080 * (1 - 2 * subtitles.SIDE_MARGIN_SHARE))

    def test_a_short_line_stays_on_one_line_at_full_size(self):
        font, lines = subtitles.fit_text('Tai giả.', 1080, 1920)
        self.assertEqual(lines, ['Tai giả.'])
        self.assertEqual(font.size, round(1920 * subtitles.FONT_SHARE))

    def test_a_caption_is_centred_on_the_band_and_drawn_into_the_frame(self):
        caption = subtitles.render_caption(Cue(1, 2, 'Anh không có tai à?'), (WIDTH, HEIGHT), 540)
        middle = caption.top + caption.image.shape[0] / 2
        self.assertAlmostEqual(middle, 540, delta=10)
        self.assertLessEqual(caption.left + caption.image.shape[1], WIDTH)
        plain = frame()
        drawn = subtitles.draw_caption(plain, caption)
        self.assertGreater(int((drawn == 255).all(axis=2).sum()), 50, 'white text was drawn')
        self.assertEqual(int((plain == 255).all(axis=2).sum()), 0, 'the input frame is not changed')

    def test_a_caption_near_the_bottom_edge_is_kept_in_the_frame(self):
        caption = subtitles.render_caption(Cue(1, 2, 'Leo lên.'), (WIDTH, HEIGHT), HEIGHT)
        self.assertEqual(caption.top + caption.image.shape[0], HEIGHT)

    def test_a_cue_too_long_for_two_lines_is_split_over_its_time(self):
        long_text = ' '.join(['Chúng ta sẽ phải chuyển sang tai thật của động vật'] * 6)
        parts = subtitles.split_long_cue(Cue(10.0, 16.0, long_text), (1080, 1920))
        self.assertGreater(len(parts), 1)
        self.assertEqual(' '.join(part.text for part in parts), long_text)
        self.assertEqual((parts[0].start, parts[-1].end), (10.0, 16.0))
        for before, after in zip(parts, parts[1:]):
            self.assertAlmostEqual(before.end, after.start)
        for part in parts:
            self.assertLessEqual(len(subtitles.fit_text(part.text, 1080, 1920)[1]), subtitles.MAX_LINES)

    def test_a_cue_that_fits_is_kept_as_it_is(self):
        cue = Cue(1.0, 2.0, 'Leo lên.')
        self.assertEqual(subtitles.split_long_cue(cue, (1080, 1920)), [cue])

    def test_an_earlier_longer_caption_still_shows_after_a_short_one_inside_it(self):
        long = subtitles.render_caption(Cue(0.0, 10.0, 'Dài'), (WIDTH, HEIGHT), 540)
        short = subtitles.render_caption(Cue(2.0, 3.0, 'Ngắn'), (WIDTH, HEIGHT), 540)
        track = subtitles.CaptionTrack([long, short])
        self.assertEqual([track.at(t) for t in (1.0, 2.5, 5.0)], [long, short, long])

    def test_the_track_shows_each_caption_only_between_its_start_and_end(self):
        first = subtitles.render_caption(Cue(1.0, 2.0, 'Một'), (WIDTH, HEIGHT), 540)
        second = subtitles.render_caption(Cue(3.0, 4.0, 'Hai'), (WIDTH, HEIGHT), 540)
        track = subtitles.CaptionTrack([second, first])
        self.assertEqual([track.at(t) for t in (0.5, 1.0, 1.9, 2.5, 3.5, 4.0)],
                         [None, first, first, None, second, None])

    def test_text_is_cleaned_of_control_characters_and_extra_spaces(self):
        self.assertEqual(subtitles.clean_text(' 你是\n不是\x00没有  耳朵 '), '你是 不是 没有 耳朵')


class TestTranscribe(unittest.TestCase):
    def fake_model(self, language, segments, speech=True):
        model = Mock()
        model.transcribe.return_value = (iter(segments), SimpleNamespace(
            language=language, duration=10.0, duration_after_vad=10.0 if speech else 0.0))
        return model

    def test_no_speech_gives_no_lines_before_the_language_is_checked(self):
        model = self.fake_model('nn', [], speech=False)
        with patch.object(subtitles, 'load_speech_model', return_value=model):
            self.assertEqual(subtitles.transcribe(Path('video.mp4'), lambda _: None), ('nn', []))

    def test_unreadable_sound_is_explained(self):
        model = Mock()
        model.transcribe.side_effect = IndexError('no audio stream')
        with patch.object(subtitles, 'load_speech_model', return_value=model):
            with self.assertRaises(SubtitleError) as raised:
                subtitles.transcribe(Path('video.mp4'), lambda _: None)
        self.assertIn('no audio', raised.exception.message)

    def test_speech_becomes_cleaned_timed_lines_with_progress(self):
        segments = [SimpleNamespace(start=0.0, end=2.0, text=' 人不能进入 '),
                    SimpleNamespace(start=2.5, end=2.5, text='空'),      # no length: dropped
                    SimpleNamespace(start=3.0, end=5.0, text='   '),     # no text: dropped
                    SimpleNamespace(start=6.0, end=10.0, text='快点')]
        progress = []
        with patch.object(subtitles, 'load_speech_model', return_value=self.fake_model('zh', segments)):
            language, cues = subtitles.transcribe(Path('video.mp4'), progress.append)
        self.assertEqual(language, 'zh')
        self.assertEqual(cues, [Cue(0.0, 2.0, '人不能进入'), Cue(6.0, 10.0, '快点')])
        self.assertEqual(progress, [0.2, 0.25, 0.5, 1.0])

    def test_an_unsupported_language_stops_before_the_speech_is_read(self):
        def never():
            raise AssertionError('the speech was read')
            yield

        with patch.object(subtitles, 'load_speech_model', return_value=self.fake_model('ja', never())):
            with self.assertRaises(SubtitleError) as raised:
                subtitles.transcribe(Path('video.mp4'), lambda _: None)
        self.assertIn('cannot be translated', raised.exception.message)

    def test_only_known_speech_models_are_loaded(self):
        from config import get_config
        for name in ('../models/x', 'someone/whisper-tiny'):
            with self.subTest(name=name), patch.object(get_config(), 'WHISPER_MODEL', name),                     patch('faster_whisper.WhisperModel') as model:
                with self.assertRaises(SubtitleError) as raised:
                    subtitles.load_speech_model()
                model.assert_not_called()
                self.assertIn('WHISPER_MODEL must be one of', raised.exception.message)

    def test_a_model_that_cannot_load_gives_a_safe_message(self):
        with patch('faster_whisper.WhisperModel', side_effect=OSError(r'C:\Users\secret')):
            with self.assertRaises(SubtitleError) as raised:
                subtitles.load_speech_model()
        self.assertNotIn('secret', raised.exception.message)
        self.assertIn('WHISPER_MODEL', raised.exception.message)


class TestRenderSubtitled(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def make_video(self, with_text, seconds=2, fps=10):
        path = self.folder / 'source.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, (WIDTH, HEIGHT))
        for index in range(seconds * fps):
            image = frame(with_text=with_text and index < fps)  # a subtitle in the first second
            writer.write(cv2.cvtColor(image, cv2.COLOR_RGB2BGR))
        writer.release()
        return path

    def read_frame(self, path, t):
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(str(path))
        try:
            return clip.get_frame(t)
        finally:
            clip.close()

    def test_the_old_subtitle_is_blurred_and_the_new_one_drawn(self):
        source = self.make_video(with_text=True)
        output = self.folder / 'out.mp4'
        progress = []
        blurred = subtitles.render_subtitled(source, output, [Cue(0.0, 0.9, 'Xin chào')], progress.append)

        self.assertTrue(blurred)
        self.assertTrue(output.is_file())
        self.assertEqual(progress[-1], 1.0)
        band = subtitles.find_subtitle_band([frame(with_text=True)] * 4)
        before, after = self.read_frame(source, 0.5), self.read_frame(output, 0.5)
        self.assertLess(np.abs(after[:band[0]].astype(int) - before[:band[0]]).mean(), 3,
                        'the picture above the band is unchanged')
        self.assertGreater(np.abs(after[band[0]:band[1]].astype(int) - before[band[0]:band[1]]).mean(), 10)
        self.assertEqual(os.listdir(self.folder / '.rendering'), [], 'no partial render is left')

    def test_without_burned_in_subtitles_nothing_is_blurred(self):
        source = self.make_video(with_text=False)
        self.assertFalse(subtitles.render_subtitled(source, self.folder / 'out.mp4', [Cue(0.0, 1.0, 'Một')]))


class TestSubtitleJob(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.source = Path(tmp.name) / '无限游戏 AI短剧_b6d14f9b_short.mp4'
        self.source.write_bytes(b'video')
        self.rendered = []

        def fake_render(source, output, cues, on_progress):
            output.write_bytes(b'subtitled')
            self.rendered.append(cues)
            return True

        for name, value in [('transcribe', Mock(return_value=('zh', [Cue(0, 1, '你好'), Cue(2, 3, '嗯')]))),
                            ('translate_to_vietnamese', Mock(return_value=['Xin chào', ''])),
                            ('render_subtitled', Mock(side_effect=fake_render)),
                            ('make_poster', Mock())]:
            patcher = patch.object(media_jobs, name, value)
            setattr(self, name, patcher.start())
            self.addCleanup(patcher.stop)

    def test_a_subtitled_copy_is_made_beside_the_original(self):
        result = media_jobs.add_vietnamese_subtitles(self.source, NullReporter())

        self.assertEqual(result['title'], '无限游戏 AI短剧 Vietsub')
        self.assertRegex(result['filename'], r'^无限游戏 AI短剧 Vietsub_[0-9a-f]{8}_short\.mp4$')
        self.assertTrue((self.source.parent / result['filename']).is_file())
        self.assertEqual(self.source.read_bytes(), b'video', 'the original is unchanged')
        self.assertEqual((result['language'], result['subtitle_count']), ('Chinese', 1))
        self.assertEqual(self.rendered, [[Cue(0, 1, 'Xin chào')]], 'lines without a translation are dropped')
        self.assertNotIn('warnings', result)
        self.make_poster.assert_called_once()

    def test_a_long_title_keeps_the_vietsub_mark(self):
        source = self.source.with_name('x' * 60 + '_b6d14f9b_short.mp4')
        source.write_bytes(b'video')
        result = media_jobs.add_vietnamese_subtitles(source, NullReporter())
        self.assertTrue(result['title'].endswith(' Vietsub'))
        self.assertLessEqual(len(result['title']), media_jobs.MAX_FRAME_FILENAME_TITLE)

    def test_a_short_without_burned_in_subtitles_gets_a_note(self):
        self.render_subtitled.side_effect = lambda source, output, cues, on_progress: False
        result = media_jobs.add_vietnamese_subtitles(self.source, NullReporter())
        self.assertIn('nothing was blurred', result['warnings'][0])

    def test_problems_become_job_failures_with_their_message(self):
        for name, error in [('transcribe', SubtitleError('Could not load the speech model.')),
                            ('translate_to_vietnamese', TranslationError('Could not download the model.'))]:
            with self.subTest(name=name), patch.object(media_jobs, name, side_effect=error):
                with self.assertRaises(JobFailed) as raised:
                    media_jobs.add_vietnamese_subtitles(self.source, NullReporter())
                self.assertEqual(raised.exception.message, error.message)
        self.render_subtitled.assert_not_called()

    def test_nothing_translated_fails_instead_of_rendering_an_empty_copy(self):
        self.translate_to_vietnamese.return_value = ['', '']
        with self.assertRaises(JobFailed):
            media_jobs.add_vietnamese_subtitles(self.source, NullReporter())
        self.render_subtitled.assert_not_called()

    def test_silence_fails_with_an_explanation(self):
        self.transcribe.return_value = ('zh', [])
        with self.assertRaises(JobFailed) as raised:
            media_jobs.add_vietnamese_subtitles(self.source, NullReporter())
        self.assertIn('No speech', raised.exception.message)


class TestSubtitleRoute(RouteTestCase):
    def post(self, body):
        return self.client.post('/api/jobs/subtitles', json=body)

    def wait_for_end(self, job_id):
        deadline = time.time() + 5
        while time.time() < deadline:
            job = self.client.get(f'/api/jobs/{job_id}').get_json()['job']
            if job['state'] in ('succeeded', 'failed', 'cancelled'):
                return job
            time.sleep(0.02)
        self.fail(f'job {job_id} did not end')

    def test_a_short_in_the_library_gets_a_subtitle_job(self):
        short = self.shorts / 'Clip_abcd1234_short.mp4'
        short.write_bytes(b'video')
        with patch.object(media_jobs, 'add_vietnamese_subtitles', return_value={'success': True}) as work:
            response = self.post({'filename': short.name})
            self.assertEqual(response.status_code, 202)
            started = response.get_json()['job']
            job = self.wait_for_end(started['id'])
        self.assertEqual((started['kind'], started['stage_count']), ('subtitles', 3))
        self.assertEqual(job['state'], 'succeeded')
        # The same file, though the path may be spelled differently (8.3 names on Windows CI)
        self.assertTrue(work.call_args.args[0].samefile(short))

    def test_one_subtitle_job_runs_at_a_time(self):
        short = self.shorts / 'Clip_abcd1234_short.mp4'
        short.write_bytes(b'video')
        release = threading.Event()
        with patch.object(media_jobs, 'add_vietnamese_subtitles',
                          side_effect=lambda path, reporter: release.wait(5) and {'success': True}):
            first = self.post({'filename': short.name})
            second = self.post({'filename': short.name})
            release.set()
            self.wait_for_end(first.get_json()['job']['id'])
        self.assertEqual((first.status_code, second.status_code), (202, 409))
        self.assertIn('already', second.get_json()['error'])

    def test_only_shorts_in_the_library_can_be_named(self):
        (self.shorts / 'notes.txt').write_text('x')
        for body, status in [({}, 400), ({'filename': 7}, 400), ({'filename': 'missing.mp4'}, 404),
                             ({'filename': '../secret.mp4'}, 404), ({'filename': 'notes.txt'}, 404),
                             ({'filename': 'C:\\Windows\\win.mp4'}, 404)]:
            with self.subTest(body=body):
                self.assertEqual(self.post(body).status_code, status)
        self.assertEqual(self.client.get('/api/jobs').get_json()['jobs'], [])


if __name__ == '__main__':
    unittest.main()
