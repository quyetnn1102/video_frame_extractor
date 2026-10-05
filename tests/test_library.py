"""The list of earlier shorts shown on the Create short page."""
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import library


class TestShortTitle(unittest.TestCase):
    def test_strips_the_random_id_and_marker_added_when_the_short_was_made(self):
        self.assertEqual(library.short_title('Me at the zoo_1a2b3c4d_short'), 'Me at the zoo')

    def test_keeps_underscores_that_belong_to_the_title(self):
        self.assertEqual(library.short_title('my_best_clip_1a2b3c4d_short'), 'my_best_clip')

    def test_falls_back_when_nothing_is_left(self):
        self.assertEqual(library.short_title('_1a2b3c4d_short'), 'Short video')

    def test_leaves_other_names_alone(self):
        self.assertEqual(library.short_title('holiday'), 'holiday')


class TestListShorts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)
        patcher = patch.object(library, 'video_duration', return_value=12.5)
        patcher.start()
        self.addCleanup(patcher.stop)

    def make(self, name, age_seconds=0, content=b'video'):
        path = self.folder / name
        path.write_bytes(content)
        stamp = path.stat().st_mtime - age_seconds
        os.utime(path, (stamp, stamp))
        return path

    def test_newest_short_comes_first(self):
        self.make('Old_1a2b3c4d_short.mp4', age_seconds=500)
        self.make('New_5e6f7a8b_short.mp4', age_seconds=10)
        names = [item['filename'] for item in library.list_shorts(self.folder)]
        self.assertEqual(names, ['New_5e6f7a8b_short.mp4', 'Old_1a2b3c4d_short.mp4'])

    def test_describes_each_short(self):
        self.make('Me at the zoo_1a2b3c4d_short.mp4', content=b'x' * 2048)
        item = library.list_shorts(self.folder)[0]
        self.assertEqual(item['title'], 'Me at the zoo')
        self.assertEqual(item['size'], 2048)
        self.assertEqual(item['duration'], 12.5)
        self.assertEqual(item['url'], '/shorts/Me%20at%20the%20zoo_1a2b3c4d_short.mp4')
        created = datetime.fromisoformat(item['created'])
        self.assertIsNotNone(created.tzinfo, 'the browser needs the time zone to show local time')

    def test_only_lists_videos_directly_in_the_folder(self):
        self.make('Clip_1a2b3c4d_short.mp4')
        self.make('notes.txt')
        (self.folder / 'folder.mp4').mkdir()
        names = [item['filename'] for item in library.list_shorts(self.folder)]
        self.assertEqual(names, ['Clip_1a2b3c4d_short.mp4'])

    def test_limits_the_list(self):
        for index in range(5):
            self.make(f'Clip{index}_1a2b3c4d_short.mp4', age_seconds=index)
        self.assertEqual(len(library.list_shorts(self.folder, limit=3)), 3)

    def test_a_missing_folder_is_an_empty_library(self):
        self.assertEqual(library.list_shorts(self.folder / 'missing'), [])


class TestVideoDuration(unittest.TestCase):
    def test_a_file_that_is_not_a_video_has_no_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'broken.mp4'
            broken.write_bytes(b'not a video')
            self.assertIsNone(library.video_duration(broken))


if __name__ == '__main__':
    unittest.main()
