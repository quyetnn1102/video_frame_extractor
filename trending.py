"""
YouTube trending videos via the official YouTube Data API v3 (videos.list).

Moved out of app_enhanced.py so the parsing helpers can be tested on their
own. The API key is sent in a header (never in the URL) and is never logged.
"""
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import requests

from logger import app_logger

YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
REQUEST_TIMEOUT_SECONDS = 10
MAX_RESULTS_LIMIT = 50  # API maximum
DEFAULT_REGION = 'US'
DESCRIPTION_PREVIEW_LENGTH = 200

REGION_PATTERN = re.compile(r'[A-Z]{2}')
CATEGORY_PATTERN = re.compile(r'\d{1,3}')
ERROR_CODE_PATTERN = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')  # e.g. API_KEY_INVALID, quotaExceeded

# Why there are no live results, so the page can say what to do (None: live results)
NO_KEY, BAD_KEY, QUOTA, UNAVAILABLE, EMPTY = 'no_key', 'bad_key', 'quota', 'unavailable', 'empty'
QUOTA_CODES = frozenset({'quotaExceeded', 'dailyLimitExceeded', 'rateLimitExceeded',
                         'userRateLimitExceeded', 'RESOURCE_EXHAUSTED'})
KEY_CODES = frozenset({'keyInvalid', 'keyExpired', 'API_KEY_INVALID', 'API_KEY_EXPIRED',
                       'accessNotConfigured', 'SERVICE_DISABLED'})

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


def _error_codes(response) -> List[str]:
    """Machine-readable codes from a Google API error body (never its free-text message)."""
    try:
        error = response.json().get('error') or {}
        found = [error.get('status')]
        found += [entry.get('reason') for key in ('details', 'errors') for entry in error.get(key) or []]
    except (ValueError, AttributeError, TypeError):
        return []
    codes = [code for code in found if isinstance(code, str) and ERROR_CODE_PATTERN.fullmatch(code)]
    return list(dict.fromkeys(codes))


def describe_api_failure(error: Exception) -> str:
    """
    What to log about a failed API call: the exception type, the HTTP status and Google's
    error codes (API_KEY_INVALID, quotaExceeded, ...). The exception text and the error
    message are left out because they can embed the request URL or the API key.
    """
    parts = [type(error).__name__]
    response = getattr(error, 'response', None)
    if response is not None:
        parts.append(f"HTTP {response.status_code}")
        parts += _error_codes(response)
    return ', '.join(parts)


def failure_reason(error: Exception) -> str:
    """QUOTA, BAD_KEY or UNAVAILABLE for a failed API call, from Google's error codes."""
    response = getattr(error, 'response', None)
    codes = set(_error_codes(response)) if response is not None else set()
    if codes & QUOTA_CODES:
        return QUOTA
    if codes & KEY_CODES:
        return BAD_KEY
    return UNAVAILABLE


def get_youtube_trending(category: str = '0', region: str = DEFAULT_REGION,
                         max_results: int = 20) -> List[Dict[str, Any]]:
    """Fetch the most popular videos; falls back to sample data on any failure."""
    videos, _ = fetch_trending(category, region, max_results)
    return videos or get_fallback_trending_data()


def fetch_trending(category: str = '0', region: str = DEFAULT_REGION,
                   max_results: int = 20) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """
    (videos, reason). The reason is None for live results; otherwise the videos are the sample
    data (NO_KEY, BAD_KEY, QUOTA, UNAVAILABLE) or none at all (EMPTY: YouTube has no videos
    for this category and region).
    """
    api_key = os.getenv('YOUTUBE_API_KEY')
    if not api_key:
        app_logger.error("YouTube API key not found in environment variables")
        return get_fallback_trending_data(), NO_KEY

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
        app_logger.error(f"YouTube API request failed ({describe_api_failure(error)})")
        return get_fallback_trending_data(), failure_reason(error)

    if not items:
        app_logger.warning("No items found in YouTube API response")
        return [], EMPTY

    videos = []
    for item in items:
        try:
            videos.append(_to_video(item))
        except (KeyError, TypeError, ValueError) as error:
            app_logger.error(f"Skipping malformed video item ({type(error).__name__})")

    if not videos:
        app_logger.warning("No valid videos processed from YouTube API")
        return get_fallback_trending_data(), UNAVAILABLE

    app_logger.info(f"Fetched {len(videos)} trending videos from YouTube API")
    return videos, None
