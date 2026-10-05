"""
YouTube trending videos via the official YouTube Data API v3 (videos.list).

Moved out of app_enhanced.py so the parsing helpers can be tested on their
own. The API key is sent in a header (never in the URL) and is never logged.
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List

import requests

from logger import app_logger

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RESULTS_LIMIT = 50  # API maximum
DEFAULT_REGION = 'US'
DESCRIPTION_PREVIEW_LENGTH = 200

REGION_PATTERN = re.compile(r'[A-Z]{2}')
CATEGORY_PATTERN = re.compile(r'\d{1,3}')

# Single source of truth for category names and the /api/video-categories list.
VIDEO_CATEGORIES = {
    '1': 'Film & Animation',
    '2': 'Autos & Vehicles',
    '10': 'Music',
    '15': 'Pets & Animals',
    '17': 'Sports',
    '19': 'Travel & Events',
    '20': 'Gaming',
    '22': 'People & Blogs',
    '23': 'Comedy',
    '24': 'Entertainment',
    '25': 'News & Politics',
    '26': 'Howto & Style',
    '27': 'Education',
    '28': 'Science & Technology',
    '29': 'Nonprofits & Activism',
}


def get_youtube_category_name(category_id: str) -> str:
    """Map a YouTube category ID to its name."""
    return VIDEO_CATEGORIES.get(category_id, 'Unknown')


def parse_youtube_duration(duration_str: str) -> str:
    """
    Convert an ISO 8601 duration to a readable one.
    Example: PT4M13S -> 4:13, PT1H2M30S -> 1:02:30
    """
    match = re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?', duration_str or '')
    if not match:
        return "0:00"

    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    if hours > 0:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def calculate_time_ago(published_at: str) -> str:
    """Human-readable age of an ISO timestamp such as 2025-01-15T10:30:00Z."""
    try:
        published = datetime.fromisoformat(published_at.replace('Z', '+00:00'))
        diff = datetime.now(published.tzinfo) - published
    except (ValueError, AttributeError, TypeError):
        return "Recently"

    def plural(count: int, unit: str) -> str:
        return f"{count} {unit}{'s' if count != 1 else ''} ago"

    if diff.days > 365:
        return plural(diff.days // 365, 'year')
    if diff.days > 30:
        return plural(diff.days // 30, 'month')
    if diff.days > 0:
        return plural(diff.days, 'day')
    if diff.seconds > 3600:
        return plural(diff.seconds // 3600, 'hour')
    if diff.seconds > 60:
        return plural(diff.seconds // 60, 'minute')
    return "Just now"


def get_fallback_trending_data() -> List[Dict[str, Any]]:
    """Sample data shown when the YouTube API is unavailable."""
    return [{
        'id': 'fallback1',
        'title': '[DEMO] Sample Trending Video',
        'description': 'This is sample data shown when YouTube API is unavailable',
        'thumbnail': 'https://img.youtube.com/vi/dQw4w9WgXcQ/mqdefault.jpg',
        'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'channel': 'Demo Channel',
        'views': '1000000',
        'duration': '3:35',
        'published': '2 hours ago',
        'category': 'Demo',
    }]


def _preview(description: str) -> str:
    if len(description) > DESCRIPTION_PREVIEW_LENGTH:
        return description[:DESCRIPTION_PREVIEW_LENGTH] + '...'
    return description


def _to_video(item: Dict[str, Any]) -> Dict[str, Any]:
    snippet = item.get('snippet', {})
    statistics = item.get('statistics', {})
    video_id = item['id']
    return {
        'id': video_id,
        'title': snippet.get('title', 'Untitled'),
        'description': _preview(snippet.get('description') or ''),
        'thumbnail': snippet.get('thumbnails', {}).get('medium', {}).get(
            'url', f'https://img.youtube.com/vi/{video_id}/mqdefault.jpg'),
        'url': f"https://www.youtube.com/watch?v={video_id}",
        'channel': snippet.get('channelTitle', 'Unknown Channel'),
        'views': str(int(statistics.get('viewCount', 0))),
        'duration': parse_youtube_duration(item.get('contentDetails', {}).get('duration', 'PT0S')),
        'published': calculate_time_ago(snippet.get('publishedAt', '')),
        'category': get_youtube_category_name(snippet.get('categoryId', '1')),
    }


def get_youtube_trending(category: str = '0', region: str = DEFAULT_REGION,
                         max_results: int = 20) -> List[Dict[str, Any]]:
    """Fetch the most popular videos; falls back to sample data on any failure."""
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        app_logger.error("YouTube API key not found in environment variables")
        return get_fallback_trending_data()

    region = region if REGION_PATTERN.fullmatch(region or '') else DEFAULT_REGION
    params = {
        'part': 'snippet,statistics,contentDetails',
        'chart': 'mostPopular',
        'regionCode': region,
        'maxResults': max(1, min(int(max_results), MAX_RESULTS_LIMIT)),
    }
    if category != '0' and CATEGORY_PATTERN.fullmatch(category or ''):
        params['videoCategoryId'] = category

    try:
        response = requests.get(
            YOUTUBE_VIDEOS_URL,
            params=params,
            headers={'X-Goog-Api-Key': api_key},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        items = response.json().get('items')
    except (requests.RequestException, ValueError) as error:
        # Only the error type is logged: exception text can embed the request URL.
        app_logger.error(f"YouTube API request failed ({type(error).__name__})")
        return get_fallback_trending_data()

    if not items:
        app_logger.warning("No items found in YouTube API response")
        return get_fallback_trending_data()

    videos = []
    for item in items:
        try:
            videos.append(_to_video(item))
        except (KeyError, TypeError, ValueError) as error:
            app_logger.error(f"Skipping malformed video item ({type(error).__name__})")

    if not videos:
        app_logger.warning("No valid videos processed from YouTube API")
        return get_fallback_trending_data()

    app_logger.info(f"Fetched {len(videos)} trending videos from YouTube API")
    return videos
