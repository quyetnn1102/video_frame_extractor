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
        patcher = patch.object(library, 'read_media_info', return_value=library.MediaInfo(12.5, 1080, 1920))
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

    def test_pages_go_through_every_short(self):
        for index in range(5):
            self.make(f'Clip{index}_1a2b3c4d_short.mp4', age_seconds=index)
        pages = [library.list_shorts(self.folder, limit=2, offset=offset) for offset in (0, 2, 4)]
        names = [item['filename'] for page in pages for item in page]
        self.assertEqual(names, [f'Clip{index}_1a2b3c4d_short.mp4' for index in range(5)])
        self.assertEqual(library.count_shorts(self.folder), 5)

    def test_each_short_is_read_once_while_it_is_unchanged(self):
        self.make('Clip_1a2b3c4d_short.mp4')
        library.list_shorts(self.folder)
        library.list_shorts(self.folder)
        self.assertEqual(library.read_media_info.call_count, 1)
        item = library.list_shorts(self.folder)[0]
        self.assertEqual((item['width'], item['height']), (1080, 1920))


class TestPosters(unittest.TestCase):
    """A still per short, so lists do not load every video to show it."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.folder = Path(tmp.name)

    def make_video(self, name='Phạm Ngũ Lão_1a2b3c4d_short.mp4', size=(720, 1280), seconds=2, fps=10):
        """A real (tiny) video; the non-ASCII name is the case cv2.imwrite gets wrong on Windows."""
        import cv2
        import numpy as np
        path = self.folder / name
        temp = self.folder / 'source.avi'  # cv2 writes ASCII paths only; the name is given after
        writer = cv2.VideoWriter(str(temp), cv2.VideoWriter_fourcc(*'MJPG'), fps, size)
        for index in range(seconds * fps):
            writer.write(np.full((size[1], size[0], 3), (index * 10) % 255, dtype=np.uint8))
        writer.release()
        os.replace(temp, path)
        return path

    def test_a_poster_is_a_small_jpeg_named_after_the_short(self):
        video = self.make_video()
        self.assertTrue(library.make_poster(video))
        poster = library.poster_path(video)
        self.assertEqual(poster.parent.name, library.POSTER_FOLDER)
        self.assertEqual(poster.name, 'Phạm Ngũ Lão_1a2b3c4d_short.jpg')
        self.assertEqual(poster.read_bytes()[:2], b'\xff\xd8', 'a JPEG')
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(poster.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual(image.shape[1], library.POSTER_WIDTH)
        self.assertEqual(image.shape[0], 640, 'the 9:16 shape is kept')

    def test_a_file_that_is_not_a_video_gets_no_poster(self):
        broken = self.folder / 'broken_1a2b3c4d_short.mp4'
        broken.write_bytes(b'not a video')
        self.assertFalse(library.make_poster(broken))
        self.assertFalse(library.poster_path(broken).exists())

    def test_sync_makes_missing_posters_and_removes_orphans(self):
        video = self.make_video('Clip_1a2b3c4d_short.mp4')
        posters = self.folder / library.POSTER_FOLDER
        posters.mkdir()
        (posters / 'Deleted_5e6f7a8b_short.jpg').write_bytes(b'old')
        self.assertEqual(library.sync_posters(self.folder), (1, 1))
        self.assertTrue(library.poster_path(video).is_file())
        self.assertEqual(sorted(path.name for path in posters.iterdir()), ['Clip_1a2b3c4d_short.jpg'])
        self.assertEqual(library.sync_posters(self.folder), (0, 0), 'nothing to do the second time')

    def test_sync_keeps_the_poster_of_a_short_made_while_it_ran(self):
        """The short is listed first; one rendered after that must keep its new poster."""
        posters = self.folder / library.POSTER_FOLDER
        posters.mkdir()
        late_poster = posters / 'Late_1a2b3c4d_short.jpg'
        real_glob = Path.glob

        def glob_then_render(path, pattern):
            found = list(real_glob(path, pattern))
            if pattern == '*.mp4':  # the render finishes right after the list of shorts was made
                (self.folder / 'Late_1a2b3c4d_short.mp4').write_bytes(b'video')
                late_poster.write_bytes(b'jpeg')
            return iter(found)

        with patch.object(Path, 'glob', glob_then_render):
            library.sync_posters(self.folder)
        self.assertTrue(late_poster.exists())

    def test_sync_removes_temporary_files_left_by_a_crash(self):
        posters = self.folder / library.POSTER_FOLDER
        posters.mkdir()
        old, recent = posters / '.old.partial', posters / '.recent.partial'
        for partial in (old, recent):
            partial.write_bytes(b'half')
        stamp = old.stat().st_mtime - library.STALE_PARTIAL_SECONDS - 1
        os.utime(old, (stamp, stamp))
        library.sync_posters(self.folder)
        self.assertEqual((old.exists(), recent.exists()), (False, True), 'a recent one may still be in use')

    def test_the_list_points_to_the_poster_when_there_is_one(self):
        video = self.make_video('Clip_1a2b3c4d_short.mp4')
        self.assertIsNone(library.list_shorts(self.folder)[0]['poster'])
        library.make_poster(video)
        self.assertEqual(library.list_shorts(self.folder)[0]['poster'], '/shorts/posters/Clip_1a2b3c4d_short.jpg')
        library.remove_poster(video)
        self.assertFalse(library.poster_path(video).exists())


class TestVideoDuration(unittest.TestCase):
    def test_a_file_that_is_not_a_video_has_no_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            broken = Path(tmp) / 'broken.mp4'
            broken.write_bytes(b'not a video')
            self.assertIsNone(library.video_duration(broken))


if __name__ == '__main__':
    unittest.main()
