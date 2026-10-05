"""Tests for trending.py: parsing helpers and the YouTube API call."""
import os
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import requests

import trending

SECRET_KEY_VALUE = 'AIzaFAKE-test-key-0123456789'


def api_item(video_id='vid1', **overrides):
    item = {
        'id': video_id,
        'snippet': {
            'title': 'A title',
            'description': 'x' * 300,
            'channelTitle': 'Channel',
            'publishedAt': '2020-01-01T00:00:00Z',
            'categoryId': '10',
            'thumbnails': {'medium': {'url': 'https://i.ytimg.com/vi/vid1/mq.jpg'}},
        },
        'statistics': {'viewCount': '1234'},
        'contentDetails': {'duration': 'PT4M13S'},
    }
    item.update(overrides)
    return item


def api_response(items):
    response = Mock()
    response.json.return_value = {'items': items}
    response.raise_for_status.return_value = None
    return response


class TestParsers(unittest.TestCase):
    def test_parse_youtube_duration(self):
        cases = {'PT4M13S': '4:13', 'PT1H2M30S': '1:02:30', 'PT45S': '0:45',
                 'PT10M': '10:00', 'PT1H': '1:00:00', 'PT0S': '0:00',
                 'garbage': '0:00', '': '0:00', None: '0:00'}
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(trending.parse_youtube_duration(raw), expected)

    def test_calculate_time_ago(self):
        def ago(**delta):
            moment = datetime.now(timezone.utc) - timedelta(**delta)
            return trending.calculate_time_ago(moment.isoformat().replace('+00:00', 'Z'))

        self.assertEqual(ago(seconds=5), 'Just now')
        self.assertEqual(ago(minutes=5, seconds=5), '5 minutes ago')
        self.assertEqual(ago(hours=2, minutes=1), '2 hours ago')
        self.assertEqual(ago(days=1, hours=1), '1 day ago')
        self.assertEqual(ago(days=3), '3 days ago')
        self.assertEqual(ago(days=90), '3 months ago')
        self.assertEqual(ago(days=800), '2 years ago')

    def test_calculate_time_ago_tolerates_bad_input(self):
        for value in ['', 'not a date', None]:
            with self.subTest(value=value):
                self.assertEqual(trending.calculate_time_ago(value), 'Recently')

    def test_category_names_come_from_one_table(self):
        self.assertEqual(trending.get_youtube_category_name('10'), 'Music')
        self.assertEqual(trending.get_youtube_category_name('999'), 'Unknown')
        self.assertIn('29', trending.VIDEO_CATEGORIES)


class TestGetYoutubeTrending(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {'YOUTUBE_API_KEY': SECRET_KEY_VALUE})
        env.start()
        self.addCleanup(env.stop)

    def test_without_an_api_key_it_does_not_call_the_api(self):
        with patch.dict(os.environ, {'YOUTUBE_API_KEY': ''}):
            with patch('trending.requests.get') as get:
                videos = trending.get_youtube_trending()
        get.assert_not_called()
        self.assertEqual(videos, trending.get_fallback_trending_data())

    def test_api_key_is_sent_in_a_header_not_the_url(self):
        with patch('trending.requests.get', return_value=api_response([api_item()])) as get:
            trending.get_youtube_trending()
        self.assertNotIn('key', get.call_args.kwargs['params'])
        self.assertEqual(get.call_args.kwargs['headers'], {'X-Goog-Api-Key': SECRET_KEY_VALUE})
        self.assertGreater(get.call_args.kwargs['timeout'], 0)

    def test_maps_the_api_response(self):
        with patch('trending.requests.get', return_value=api_response([api_item()])):
            videos = trending.get_youtube_trending()

        self.assertEqual(len(videos), 1)
        video = videos[0]
        self.assertEqual(video['url'], 'https://www.youtube.com/watch?v=vid1')
        self.assertEqual(video['duration'], '4:13')
        self.assertEqual(video['views'], '1234')
        self.assertEqual(video['category'], 'Music')
        self.assertTrue(video['description'].endswith('...'))
        self.assertEqual(len(video['description']), 203)

    def test_untrusted_region_and_category_are_not_forwarded(self):
        with patch('trending.requests.get', return_value=api_response([api_item()])) as get:
            trending.get_youtube_trending(category='10&key=evil', region='US&x=1')
        params = get.call_args.kwargs['params']
        self.assertEqual(params['regionCode'], 'US')
        self.assertNotIn('videoCategoryId', params)

    def test_valid_region_and_category_are_forwarded_and_results_capped(self):
        with patch('trending.requests.get', return_value=api_response([api_item()])) as get:
            trending.get_youtube_trending(category='10', region='VN', max_results=500)
        params = get.call_args.kwargs['params']
        self.assertEqual((params['regionCode'], params['videoCategoryId']), ('VN', '10'))
        self.assertEqual(params['maxResults'], 50)

    def test_request_failures_fall_back_without_logging_the_key(self):
        failure = requests.HTTPError(
            f'403 for https://www.googleapis.com/youtube/v3/videos?key={SECRET_KEY_VALUE}')
        with patch('trending.requests.get', side_effect=failure), \
                patch('trending.app_logger') as log:
            videos = trending.get_youtube_trending()

        self.assertEqual(videos, trending.get_fallback_trending_data())
        logged = ' '.join(str(call) for call in log.mock_calls)
        self.assertNotIn(SECRET_KEY_VALUE, logged)
        self.assertNotIn('googleapis.com', logged)

    def test_malformed_items_are_skipped(self):
        items = [{'no_id': True}, api_item('good')]
        with patch('trending.requests.get', return_value=api_response(items)):
            videos = trending.get_youtube_trending()
        self.assertEqual([video['id'] for video in videos], ['good'])

    def test_empty_response_falls_back(self):
        with patch('trending.requests.get', return_value=api_response([])):
            self.assertEqual(trending.get_youtube_trending(), trending.get_fallback_trending_data())


if __name__ == '__main__':
    unittest.main()
