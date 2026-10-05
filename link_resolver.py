"""
Safe resolution of share-link redirects (currently fb.watch).

yt-dlp has no extractor for these short hosts, and the generic extractor that
would follow them is disabled. We resolve them ourselves instead: only the
short-link host is ever requested, redirects are never followed automatically,
and every redirect target must pass the normal URL validation before it is
handed to yt-dlp.
"""
from typing import Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

from validators import validator

# Hosts that only redirect to the real video page.
SHORT_LINK_HOSTS = frozenset({'fb.watch'})
MAX_REDIRECT_HOPS = 3
REQUEST_TIMEOUT_SECONDS = 10
REDIRECT_STATUS_CODES = frozenset({301, 302, 303, 307, 308})
USER_AGENT = 'Mozilla/5.0 (compatible; VideoFrameExtractor)'


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or '').lower()
    except ValueError:
        return ''


def resolve_short_url(url: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve a short share link to the platform's canonical video URL.

    Returns:
        (resolved_url, error_message). URLs on other hosts are returned
        unchanged without any network access.
    """
    if _host(url) not in SHORT_LINK_HOSTS:
        return url, None

    current = url
    for _ in range(MAX_REDIRECT_HOPS):
        try:
            response = requests.get(
                current,
                allow_redirects=False,
                timeout=REQUEST_TIMEOUT_SECONDS,
                headers={'User-Agent': USER_AGENT},
                stream=True,
            )
        except requests.RequestException:
            return None, "Could not resolve the short link"

        try:
            status = response.status_code
            location = response.headers.get('Location')
        finally:
            response.close()

        if status not in REDIRECT_STATUS_CODES or not location:
            return None, "The short link did not lead to a video"

        current = urljoin(current, location)
        is_valid, _, _ = validator.validate_url(current)
        if not is_valid:
            return None, "The short link redirected to an unsupported URL"

        if _host(current) not in SHORT_LINK_HOSTS:
            return current, None

    return None, "The short link redirected too many times"
