"""Clip suggestions: reading captions, choosing a track, and scoring the moments (offline)."""
import unittest
from unittest.mock import MagicMock, patch

import clip_finder
from clip_finder import Caption, ClipFinderError, choose_caption_url, parse_json3, suggest_windows


def heatmap(values, step=10.0):
    """A heatmap of len(values) steps of `step` seconds."""
    return [{'start_time': index * step, 'end_time': (index + 1) * step, 'value': value}
            for index, value in enumerate(values)]


class TestParseJson3(unittest.TestCase):
    def test_reads_lines_and_skips_empty_and_line_break_events(self):
        data = {'events': [
            {'tStartMs': 0, 'dDurationMs': 2000},                                   # no text
            {'tStartMs': 1500, 'dDurationMs': 2500, 'segs': [{'utf8': 'Hello '}, {'utf8': 'there'}]},
            {'tStartMs': 4000, 'segs': [{'utf8': '\n'}]},                           # line break only
            {'tStartMs': 5000, 'dDurationMs': 1000, 'segs': [{'utf8': 'Second\nline'}]},
        ]}
        self.assertEqual(parse_json3(data), [Caption(1.5, 4.0, 'Hello there'), Caption(5.0, 6.0, 'Second line')])

    def test_survives_an_empty_document(self):
        self.assertEqual(parse_json3({}), [])

    def test_malformed_data_is_skipped_not_fatal(self):
        """Captions come from the network; odd data must leave the heatmap suggestions intact."""
        for data in [[], 'text', None, {'events': 'x'}, {'events': [5, None, 'x']},
                     {'events': [{'tStartMs': None, 'segs': [{'utf8': 'a'}]},
                                 {'tStartMs': 'soon', 'segs': [{'utf8': 'b'}]},
                                 {'tStartMs': 1000, 'segs': ['not a dict', {'utf8': 7}]}]}]:
            with self.subTest(data=data):
                parse_json3(data)  # never raises
        good = parse_json3({'events': [{'tStartMs': 3000, 'segs': [{'utf8': 'late'}]},
                                       {'tStartMs': '1000', 'dDurationMs': 'x', 'segs': [{'utf8': 'bad duration'}]},
                                       {'tStartMs': 1000, 'segs': [{'utf8': 'early'}]}]})
        self.assertEqual([caption.text for caption in good], ['early', 'late'], 'sorted, bad events skipped')


class TestChooseCaptionUrl(unittest.TestCase):
    def track(self, code, ext='json3', host='www.youtube.com'):
        return {code: [{'ext': 'vtt', 'url': f'https://{host}/vtt'}, {'ext': ext, 'url': f'https://{host}/{code}'}]}

    def test_uploaded_captions_come_first(self):
        info = {'language': 'en', 'subtitles': self.track('en'), 'automatic_captions': self.track('en-orig')}
        self.assertEqual(choose_caption_url(info), 'https://www.youtube.com/en')

    def test_automatic_captions_only_in_the_spoken_language(self):
        info = {'language': 'vi', 'automatic_captions': {**self.track('de'), **self.track('vi-orig'), **self.track('en')}}
        self.assertEqual(choose_caption_url(info), 'https://www.youtube.com/vi-orig')
        translated_only = {'language': 'vi', 'automatic_captions': {**self.track('de'), **self.track('fr')}}
        self.assertIsNone(choose_caption_url(translated_only), 'machine translations are not used')

    def test_only_youtube_hosts_over_https(self):
        for url in ['http://www.youtube.com/x', 'https://evil.example/x', 'https://youtube.com.evil.example/x']:
            with self.subTest(url=url):
                info = {'subtitles': {'en': [{'ext': 'json3', 'url': url}]}}
                self.assertIsNone(choose_caption_url(info))


class TestSuggestWindows(unittest.TestCase):
    def test_the_most_replayed_stretch_comes_first(self):
        values = [0.2] * 10 + [0.9, 1.0, 0.9] + [0.2] * 7     # a peak at 100-130 s of 200 s
        clips = suggest_windows(heatmap(values), [], 200, 30)
        self.assertEqual((clips[0]['start'], clips[0]['duration']), (100.0, 30.0))
        self.assertEqual(clips[0]['score'], 1.0)
        self.assertIn('Most replayed', clips[0]['reason'])

    def test_the_intro_peak_is_ignored(self):
        """Everyone starts at the beginning, so the heatmap always peaks there."""
        values = [1.0] + [0.2] * 9 + [0.6] * 3 + [0.2] * 7
        clips = suggest_windows(heatmap(values), [], 200, 30)
        self.assertEqual(clips[0]['start'], 100.0)

    def test_clips_never_overlap_and_are_capped(self):
        clips = suggest_windows(heatmap([0.5 + (index % 3) / 10 for index in range(30)]), [], 300, 30)
        self.assertLessEqual(len(clips), clip_finder.MAX_SUGGESTIONS)
        spans = sorted((clip['start'], clip['start'] + clip['duration']) for clip in clips)
        for (_, end), (next_start, _) in zip(spans, spans[1:]):
            self.assertLessEqual(end, next_start)

    def test_clips_start_and_end_on_caption_lines_and_never_exceed_the_length(self):
        values = [0.2] * 10 + [1.0] * 3 + [0.2] * 7          # the replay peak is 100-130 s
        captions = [Caption(97.5, 103.0, 'So here is the trick'), Caption(103.0, 112.0, 'you hold it like this'),
                    Caption(112.0, 124.0, 'and then let go'), Caption(124.0, 131.0, 'and it flies')]
        clip = suggest_windows(heatmap(values), captions, 200, 30)[0]
        self.assertIn(clip['start'], {caption.start for caption in captions}, 'never starts mid-line')
        self.assertIn(round(clip['start'] + clip['duration'], 1), {caption.end for caption in captions})
        self.assertLessEqual(clip['duration'], 30)
        self.assertTrue(97.5 <= clip['start'] < 110, 'at the replay peak')
        self.assertTrue(clip['excerpt'])

    def test_a_start_inside_a_line_moves_back_to_the_line_start(self):
        captions = [Caption(97.5, 103.0, 'So here is the trick'), Caption(103.0, 112.0, 'you hold it like this')]
        self.assertEqual(clip_finder._snap(100.0, 30, captions, 200)[0], 97.5)
        self.assertEqual(clip_finder._snap(90.0, 30, captions, 200)[0], 90.0, 'no line within reach: unchanged')

    def test_without_a_heatmap_dense_talking_is_used(self):
        captions = [Caption(0, 5, 'hi'), Caption(60, 62, 'one two three four five six'),
                    Caption(62, 64, 'seven eight nine ten eleven twelve'), Caption(120, 125, 'bye')]
        clips = suggest_windows([], captions, 180, 10)
        self.assertEqual(clips[0]['start'], 60)
        self.assertIn('no replay data', clips[0]['reason'])

    def test_no_signal_means_no_suggestions(self):
        self.assertEqual(suggest_windows([], [], 180, 30), [])
        self.assertEqual(suggest_windows(heatmap([1.0]), [], 0, 30), [])

    def test_a_clip_longer_than_the_video_is_the_whole_video(self):
        clips = suggest_windows(heatmap([0.5, 0.7, 0.6]), [], 30, 60)
        self.assertEqual((clips[0]['start'], clips[0]['duration']), (0.0, 30.0))


class TestSuggestClips(unittest.TestCase):
    """The network part, with yt-dlp replaced."""

    def run_with(self, info=None, error=None):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        if error:
            ydl.extract_info.side_effect = error
        else:
            ydl.extract_info.return_value = info
        with patch.object(clip_finder.yt_dlp, 'YoutubeDL', return_value=ydl):
            return clip_finder.suggest_clips('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 30, 3600)

    def test_returns_the_clips_and_which_signals_were_found(self):
        result = self.run_with({'duration': 200, 'heatmap': heatmap([0.2] * 10 + [1.0] * 3 + [0.2] * 7)})
        self.assertEqual(result['signals'], {'heatmap': True, 'captions': False, 'captions_unreadable': False})
        self.assertEqual(result['clips'][0]['start'], 100.0)

    def test_captions_youtube_will_not_serve_are_reported_as_unreadable(self):
        ydl = MagicMock()
        ydl.__enter__.return_value = ydl
        ydl.extract_info.return_value = {
            'duration': 200, 'heatmap': heatmap([0.2] * 10 + [1.0] * 3 + [0.2] * 7),
            'subtitles': {'en': [{'ext': 'json3', 'url': 'https://www.youtube.com/api/timedtext?x=1'}]}}
        ydl.urlopen.side_effect = clip_finder.yt_dlp.utils.DownloadError('HTTP Error 429')
        with patch.object(clip_finder.yt_dlp, 'YoutubeDL', return_value=ydl):
            result = clip_finder.suggest_clips('https://www.youtube.com/watch?v=dQw4w9WgXcQ', 30, 3600)
        self.assertEqual(result['signals'], {'heatmap': True, 'captions': False, 'captions_unreadable': True})
        self.assertEqual(result['clips'][0]['start'], 100.0, 'the heatmap still works')

    def test_captions_redirected_away_from_youtube_are_dropped(self):
        response = MagicMock()
        response.__enter__.return_value = response
        response.url = 'http://127.0.0.1:8080/internal'
        response.read.return_value = b'{"events": [{"tStartMs": 0, "segs": [{"utf8": "secret"}]}]}'
        ydl = MagicMock()
        ydl.urlopen.return_value = response
        info = {'subtitles': {'en': [{'ext': 'json3', 'url': 'https://www.youtube.com/api/timedtext?x=1'}]}}
        self.assertEqual(clip_finder._fetch_captions(ydl, info), ([], True))
        response.read.assert_not_called()

    def test_replay_data_in_an_unexpected_shape_is_explained(self):
        with self.assertRaises(ClipFinderError) as raised:
            self.run_with({'duration': 200, 'heatmap': [{'start': 0, 'value': 1}]})
        self.assertIn('replay data', raised.exception.user_message)

    def test_problems_are_explained_without_exception_text(self):
        cases = [({'duration': 0}, 'no fixed length'), ({'duration': 99999}, 'longer than the app accepts'),
                 ({'duration': 200}, 'nothing to suggest')]
        for info, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(ClipFinderError) as raised:
                self.run_with(info)
            self.assertIn(expected, raised.exception.user_message)
        with self.assertRaises(ClipFinderError) as raised:
            self.run_with(error=clip_finder.yt_dlp.utils.DownloadError(r'C:\secret\cookies.txt'))
        self.assertNotIn('secret', raised.exception.user_message)


if __name__ == '__main__':
    unittest.main()
