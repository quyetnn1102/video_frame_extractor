"""Tests for short_video.py: request validation, crop geometry and rendering."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

import short_video
from short_video import (ShortVideoError, compute_vertical_crop, normalize_quality,
                         normalize_text_overlay, parse_duration, parse_start_time)


class TestParseStartTime(unittest.TestCase):
    def test_accepts_seconds_and_clock_formats(self):
        cases = [(0, 0), (12.5, 12.5), ('90', 90), ('1:30', 90), ('0:59:59', 3599),
                 (None, 0), ('', 0), ('  ', 0)]
        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(parse_start_time(value), expected)

    def test_rejects_invalid_values(self):
        for value in [-1, '-5', '1:60', '0:99', 'abc', True, float('nan'), float('inf'),
                      [1], {}, 10 ** 9, '1:2']:
            with self.subTest(value=value):
                with self.assertRaises(ShortVideoError):
                    parse_start_time(value)


class TestParseDuration(unittest.TestCase):
    def test_accepts_the_allowed_range(self):
        self.assertEqual(parse_duration(30), 30)
        self.assertEqual(parse_duration('45'), 45)
        self.assertEqual(parse_duration(1.5), 1.5)
        self.assertEqual(parse_duration(short_video.MAX_SHORT_DURATION), 300)

    def test_rejects_out_of_range_and_non_numbers(self):
        for value in [0, 0.5, -3, 301, 'x', None, True, float('nan'), [30]]:
            with self.subTest(value=value):
                with self.assertRaises(ShortVideoError):
                    parse_duration(value)


class TestNormalizeQuality(unittest.TestCase):
    def test_defaults_and_case_insensitivity(self):
        self.assertEqual(normalize_quality(None), 'medium')
        self.assertEqual(normalize_quality(''), 'medium')
        self.assertEqual(normalize_quality('HIGH'), 'high')

    def test_rejects_unknown_quality(self):
        for value in ['ultra', '5000k', 3]:
            with self.subTest(value=value):
                with self.assertRaises(ShortVideoError):
                    normalize_quality(value)


class TestNormalizeTextOverlay(unittest.TestCase):
    def test_nothing_to_draw(self):
        for value in [None, '', '   ', {}, {'text': ''}, {'text': '  '}, {'fontsize': 20}]:
            with self.subTest(value=value):
                self.assertIsNone(normalize_text_overlay(value))

    def test_plain_string_uses_defaults(self):
        overlay = normalize_text_overlay('Hello')
        self.assertEqual(overlay, {'text': 'Hello', 'fontsize': 50, 'color': 'white',
                                   'stroke_color': 'black', 'stroke_width': 2,
                                   'position': 'bottom'})

    def test_dict_values_are_validated_and_kept(self):
        overlay = normalize_text_overlay({'text': 'Hi', 'fontsize': 80, 'color': '#ff0000',
                                          'stroke_color': 'blue', 'stroke_width': 0,
                                          'position': 'top'})
        self.assertEqual((overlay['fontsize'], overlay['color'], overlay['position']),
                         (80, '#ff0000', 'top'))

    def test_control_characters_are_removed_and_percent_is_escaped(self):
        overlay = normalize_text_overlay('a\x00b\r\nc 100%')
        self.assertEqual(overlay['text'], 'abc 100%%')

    def test_rejects_unsafe_or_out_of_range_values(self):
        bad = [
            'x' * 101,
            {'text': 'a', 'fontsize': 9999},
            {'text': 'a', 'fontsize': 4},
            {'text': 'a', 'fontsize': 20.5},
            {'text': 'a', 'stroke_width': 99},
            {'text': 'a', 'color': 'red; rm -rf'},
            {'text': 'a', 'color': '#12345'},
            {'text': 'a', 'color': 'xml:/etc/passwd'},
            {'text': 'a', 'position': 'left'},
            {'text': 5},
            123,
            ['text'],
        ]
        for value in bad:
            with self.subTest(value=value):
                with self.assertRaises(ShortVideoError):
                    normalize_text_overlay(value)


class TestVerticalCrop(unittest.TestCase):
    def test_wide_sources_are_cropped_at_the_sides(self):
        self.assertEqual(compute_vertical_crop(1920, 1080), (656, 0, 1263, 1080))

    def test_tall_sources_are_cropped_top_and_bottom(self):
        self.assertEqual(compute_vertical_crop(400, 1000), (0, 144, 400, 855))

    def test_exact_vertical_needs_no_crop(self):
        self.assertIsNone(compute_vertical_crop(1080, 1920))

    def test_crop_box_stays_inside_the_frame_and_is_9_16(self):
        for width, height in [(1920, 1080), (640, 480), (500, 500), (300, 900), (1080, 1921)]:
            with self.subTest(size=(width, height)):
                x1, y1, x2, y2 = compute_vertical_crop(width, height)
                self.assertTrue(0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height)
                self.assertAlmostEqual((x2 - x1) / (y2 - y1), 9 / 16, delta=0.01)

    def test_rejects_empty_frames(self):
        with self.assertRaises(ValueError):
            compute_vertical_crop(0, 100)


def ffmpeg_available():
    try:
        import imageio_ffmpeg
        imageio_ffmpeg.get_ffmpeg_exe()
        return True
    except Exception:
        return False


@unittest.skipUnless(ffmpeg_available(), 'bundled ffmpeg binary not available')
class TestCreateShort(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        self.source = self.make_source()

    def make_source(self, seconds=4, fps=10, size=(160, 90)):
        path = self.folder / 'source.avi'
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'MJPG'), fps, size)
        for index in range(seconds * fps):
            writer.write(np.full((size[1], size[0], 3), (index * 5) % 255, dtype=np.uint8))
        writer.release()
        return path

    def video_size_and_length(self, path):
        capture = cv2.VideoCapture(str(path))
        try:
            return (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)),
                    int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)),
                    capture.get(cv2.CAP_PROP_FRAME_COUNT) / (capture.get(cv2.CAP_PROP_FPS) or 1))
        finally:
            capture.release()

    def test_renders_a_vertical_clip_of_the_requested_length(self):
        output = self.folder / 'short.mp4'

        result = short_video.create_short(self.source, output, start=1, duration=2,
                                          vertical=True, quality='low')

        self.assertEqual(result['duration'], 2)
        self.assertEqual(result['warnings'], [])
        width, height, length = self.video_size_and_length(output)
        self.assertEqual((width, height), short_video.SHORT_SIZE)
        self.assertAlmostEqual(length, 2, delta=0.3)
        self.assertEqual(list(self.folder.glob('*.tmp-audio.*')), [])

    def test_duration_is_clamped_to_the_end_of_the_video(self):
        output = self.folder / 'short.mp4'
        result = short_video.create_short(self.source, output, start=3, duration=30,
                                          vertical=False, quality='low')
        self.assertAlmostEqual(result['duration'], 1, delta=0.2)

    def test_start_past_the_end_fails_and_leaves_no_file(self):
        output = self.folder / 'short.mp4'
        with self.assertRaises(ShortVideoError):
            short_video.create_short(self.source, output, start=60, duration=5)
        self.assertFalse(output.exists())

    def test_text_overlay_never_blocks_the_video(self):
        output = self.folder / 'short.mp4'
        overlay = normalize_text_overlay('Hello')

        result = short_video.create_short(self.source, output, start=0, duration=1,
                                          quality='low', text_overlay=overlay)

        self.assertTrue(output.exists())
        self.assertGreater(output.stat().st_size, 0)
        self.assertIsInstance(result['warnings'], list)


if __name__ == '__main__':
    unittest.main()
