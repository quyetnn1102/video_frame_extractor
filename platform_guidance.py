"""
What the pages tell people about each supported platform: how well it works and what to try
when a link fails. Shown by the link check (/api/test-platform) and the video preview.
"""

# The names as the platforms write them, for anything shown on a page
PLATFORM_NAMES = {
    'youtube': 'YouTube',
    'tiktok': 'TikTok',
    'facebook': 'Facebook',
    'instagram': 'Instagram',
    'douyin': 'Douyin',
}

PLATFORM_GUIDANCE = {
    'youtube': {
        'status': 'supported',
        'notes': 'Public videos, Shorts and live replays up to the duration limit',
        'tips': ['Copy the URL from the browser address bar or the Share button'],
    },
    'tiktok': {
        'status': 'supported',
        'notes': 'Public videos; some are region-blocked',
        'tips': ['Share → Copy link works (vm.tiktok.com / vt.tiktok.com links are fine)'],
    },
    'facebook': {
        'status': 'limited',
        'notes': 'Public videos only',
        'tips': ['Videos that need a login or are private cannot be downloaded',
                 'fb.watch share links are supported'],
    },
    'instagram': {
        'status': 'limited',
        'notes': 'Public posts and reels; some content needs a logged-in session',
        'tips': ['Use public posts or reels',
                 'For restricted content provide instagram_cookies.txt (see the README)'],
    },
    'douyin': {
        'status': 'limited',
        'notes': 'Public videos; Douyin often refuses automated downloads',
        'tips': ['douyin.com/video/<id>, ?modal_id=<id> and v.douyin.com share links all work',
                 'If Douyin refuses, export your browser cookies to douyin_cookies.txt (see the README)'],
    },
}
