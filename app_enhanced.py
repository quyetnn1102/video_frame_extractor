"""
Flask application: web pages and JSON API for the Video Frame Extractor.

Heavy lifting lives in other modules (video_processor, short_video, trending,
youtube_uploader); this module validates requests, calls them, and shapes the
responses. It is built for local use: it listens on loopback by default and
only answers requests whose Host header is on the allow-list.
"""
import io
import os
import re
import time
import zipfile
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from flask import (Flask, jsonify, render_template, render_template_string, request,
                   send_file, send_from_directory)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

import media_jobs
from clip_finder import ClipFinderError, suggest_clips
from config import get_config
from database import db_manager, get_analytics, get_recent_requests
from jobs import JobFailed, JobQueueFull, JobRegistry, NullReporter
from library import POSTER_FOLDER, folder_size_bytes, list_shorts, remove_poster, sync_posters
from logger import LogContext, api_logger, app_logger
from media_jobs import (DEFAULT_SHORT_DURATION, EXTRACT_STAGES, SHORT_STAGES, finish_request_record,
                        parse_extract_request, parse_short_request, run_recorded)
from short_video import (MAX_SHORT_DURATION, MIN_SHORT_DURATION, ShortVideoError, parse_duration,
                         remove_partial_renders, text_overlay_available)
from trending import VIDEO_CATEGORIES, get_youtube_trending
from validators import MAX_TIMESTAMPS, resolve_in_folder, validator
from video_processor import extractor, javascript_runtime_available
from youtube_uploader import PRIVACY_STATUSES, YouTubeUploaderError, youtube_uploader

APP_VERSION = '2.1.0'
LOOPBACK_HOSTS = ('127.0.0.1', 'localhost', '::1')
HOST_HEADER = re.compile(r'(?P<host>\[[0-9a-f:.]+\]|[a-z0-9.-]+)(?::(?P<port>\d{1,5}))?')
MAX_PORT = 65535
CROSS_SITE_VALUES = ('cross-site', 'same-site')
JOB_ID_PATTERN = re.compile(r'[0-9a-f]{32}')
RECENT_REQUESTS_SHOWN = 10
MAX_TRENDING_RESULTS = 50

# One registry per process: deploy.py runs a single worker, so every request sees the same jobs
job_registry = JobRegistry(max_workers=get_config().MAX_CONCURRENT_JOBS)

CONTENT_SECURITY_POLICY = "; ".join([
    "default-src 'self'",
    # No 'unsafe-inline': pages keep their scripts and styles in /static (tests/test_templates.py)
    "script-src 'self' https://cdn.jsdelivr.net",
    "style-src 'self' https://cdn.jsdelivr.net https://cdnjs.cloudflare.com",
    "font-src 'self' https://cdnjs.cloudflare.com",
    "img-src 'self' data: https:",
    "media-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
])

HTTP_ERROR_MESSAGES = {
    400: 'Bad request',
    404: 'Not found',
    405: 'Method not allowed',
    413: 'Request too large',
    415: 'Unsupported media type',
    429: 'Rate limit exceeded. Please try again later.',
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
        'notes': 'Public videos with a full douyin.com/video/<id> link',
        'tips': ['v.douyin.com short links are not supported; open the video and copy its full URL'],
    },
}

OAUTH_RESULT_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>YouTube sign-in</title>
<link rel="stylesheet" href="/static/css/app.css"></head>
<body><main class="result-page">
<h1>{{ heading }}</h1><p>{{ message }}</p><p>You can close this window.</p>
</main>
<script src="/static/js/oauth-result.js"></script>
</body></html>"""


def json_error(message: str, status: int):
    """Standard error envelope used by every API route."""
    return jsonify({'success': False, 'error': message}), status


def get_json_body() -> Optional[Dict[str, Any]]:
    """The request's JSON object, or None (Flask would raise 400/415 instead)."""
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else None


def host_is_allowed(host_header: Optional[str], allowed_hosts) -> bool:
    """
    True when a Host header is exactly `<allowed host>` or `<allowed host>:<port>`.

    The whole header must match a strict pattern (no userinfo, tabs, paths or
    extra colons), instead of being parsed leniently and then trusted.
    """
    match = HOST_HEADER.fullmatch((host_header or '').lower())
    if not match:
        return False
    port = match.group('port')
    if port is not None and int(port) > MAX_PORT:
        return False
    allowed = {host.strip('[]').lower() for host in allowed_hosts}
    return match.group('host').strip('[]') in allowed


def origin_is_allowed(origin: str, allowed_hosts) -> bool:
    """True when an Origin header names this app (an allowed host over http or https)."""
    try:
        parsed = urlsplit(origin)
    except ValueError:
        return False
    return (parsed.scheme in ('http', 'https') and bool(parsed.netloc)
            and host_is_allowed(parsed.netloc, allowed_hosts))


def storage_usage(config) -> Dict[str, int]:
    """Bytes kept by this app in its working folders (shown on the dashboard)."""
    return {
        'frames': folder_size_bytes(config.FRAMES_FOLDER),
        'shorts': folder_size_bytes(config.SHORTS_FOLDER),
        'downloads': folder_size_bytes(config.DOWNLOAD_FOLDER),
    }


def collect_system_info(base_dir, include_uptime: bool = False) -> Dict[str, Any]:
    import psutil

    info = {
        'cpu_percent': psutil.cpu_percent(),
        'memory_percent': psutil.virtual_memory().percent,
        'disk_usage': psutil.disk_usage(str(base_dir)).percent,
    }
    if include_uptime:
        info['uptime'] = time.time() - psutil.boot_time()
    return info


def start_request_record(url: str, platform: str) -> int:
    return db_manager.log_video_request(
        url_hash=validator.hash_sensitive_data(url),
        platform=platform,
        user_ip=request.remote_addr,
        user_agent=(request.headers.get('User-Agent') or '')[:200],
    )


def create_app() -> Flask:
    """Application factory"""
    app = Flask(__name__)

    config = get_config()
    app.config.from_object(config)

    # Only trust X-Forwarded-* headers when a reverse proxy is configured
    if config.TRUSTED_PROXY_COUNT > 0:
        hops = config.TRUSTED_PROXY_COUNT
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops)

    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[f"{config.RATE_LIMIT_PER_MINUTE} per minute"],
        storage_uri="memory://",
    )
    limiter.init_app(app)
    # The @limiter.limit decorators only hold a weak reference to the Limiter. When
    # RATE_LIMIT_ENABLED=false, init_app() returns before registering it on the app,
    # so the Limiter would be garbage collected once create_app() returns and every
    # decorated route would fail with "ReferenceError: weakly-referenced object ...".
    app.extensions['rate_limiter'] = limiter

    if not javascript_runtime_available():
        app_logger.warning("No JavaScript runtime (Node.js, Deno or Bun) found: YouTube downloads may "
                           "fail with HTTP 403. Install Node.js and restart the app.")

    @app.before_request
    def guard_request():
        request.start_time = time.time()
        # A rebinding attack reaches this server under an attacker's hostname
        if not host_is_allowed(request.host, config.ALLOWED_HOSTS):
            app_logger.warning("Rejected request with unexpected Host header")
            return json_error('Invalid Host header', 400)

        # There is no login, so the browser must not let another website call the API.
        # Pages and /oauth2callback are exempt: following a link or Google's redirect
        # back after sign-in are cross-site navigations.
        if request.path.startswith('/api/'):
            if request.headers.get('Sec-Fetch-Site') in CROSS_SITE_VALUES:
                return json_error('Cross-site requests are not allowed', 403)
            origin = request.headers.get('Origin')
            if origin is not None and not origin_is_allowed(origin, config.ALLOWED_HOSTS):
                return json_error('Origin not allowed', 403)

    @app.after_request
    def finish_response(response):
        if hasattr(request, 'start_time'):
            api_logger.log_api_request(
                method=request.method,
                endpoint=request.endpoint or request.path,
                user_ip=get_remote_address(),
                user_agent=request.headers.get('User-Agent', 'Unknown'),
                status_code=response.status_code,
                duration_ms=(time.time() - request.start_time) * 1000,
            )

        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Content-Security-Policy'] = CONTENT_SECURITY_POLICY
        if request.is_secure:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        return response

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        return json_error(HTTP_ERROR_MESSAGES.get(error.code, error.name), error.code)

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        error_id = uuid.uuid4().hex[:8]
        app_logger.exception(f"Unhandled error {error_id}", error_type=type(error).__name__)
        return jsonify({'success': False, 'error': 'Internal server error',
                        'error_id': error_id}), 500

    # -- pages ----------------------------------------------------------------

    @app.route('/')
    def index():
        return render_template('index.html')

    @app.route('/extract')
    def extract_page():
        return render_template('extract.html')

    @app.route('/trending')
    def trending_page():
        return render_template('trending.html')

    @app.route('/create-short')
    def create_short_page():
        # Captions need ImageMagick; without it the field is disabled and says why
        return render_template('create_short.html', text_overlay_available=text_overlay_available())

    @app.route('/dashboard')
    def dashboard():
        try:
            system_info = collect_system_info(config.BASE_DIR)
            return render_template('dashboard.html', analytics=get_analytics(),
                                   system_info=system_info,
                                   recent_requests=get_recent_requests(limit=RECENT_REQUESTS_SHOWN),
                                   storage=storage_usage(config), cleanup_hours=config.AUTO_CLEANUP_HOURS)
        except Exception as error:  # the page should still load without metrics
            app_logger.error(f"Dashboard error ({type(error).__name__})")
            return render_template('dashboard.html', analytics={}, system_info={},
                                   recent_requests=[], storage={}, cleanup_hours=config.AUTO_CLEANUP_HOURS)

    # -- API: validation and information --------------------------------------

    @app.route('/api/health')
    def health_check():
        return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat(),
                        'version': APP_VERSION})

    @app.route('/api/dashboard-data')
    def dashboard_data():
        try:
            return jsonify({
                'analytics': get_analytics(),
                'system_info': collect_system_info(config.BASE_DIR, include_uptime=True),
                'recent_requests': get_recent_requests(limit=RECENT_REQUESTS_SHOWN),
                'storage': storage_usage(config),
                'timestamp': datetime.now().isoformat(),
            })
        except Exception as error:
            app_logger.error(f"Dashboard API error ({type(error).__name__})")
            return json_error('Failed to fetch dashboard data', 500)

    @app.route('/api/validate-url', methods=['POST'])
    @limiter.limit("30 per minute")
    def validate_url():
        data = get_json_body()
        if data is None or 'url' not in data:
            return json_error('URL is required', 400)

        url = data['url']
        is_valid, platform, error = validator.validate_url(url)
        if not is_valid:
            return jsonify({'success': False, 'valid': False, 'error': error})

        response = {'success': True, 'valid': True, 'platform': platform}
        info_success, video_info, _ = extractor.get_video_info(url.strip())
        if info_success and video_info:
            response.update({
                'title': video_info.get('title', 'Unknown'),
                'duration': video_info.get('duration'),
                'thumbnail': video_info.get('thumbnail'),
            })
        return jsonify(response)

    @app.route('/api/video-info', methods=['POST'])
    @limiter.limit("20 per minute")
    def get_video_info():
        data = get_json_body()
        if data is None or not isinstance(data.get('url'), str):
            return json_error('URL is required', 400)

        url = data['url'].strip()
        is_valid, _, error = validator.validate_url(url)
        if not is_valid:
            return json_error(error, 400)

        success, video_info, info_error = extractor.get_video_info(url)
        if not success:
            return json_error(info_error, 400)
        return jsonify({'success': True, 'video_info': video_info})

    @app.route('/api/test-platform', methods=['POST'])
    @limiter.limit("30 per minute")
    def test_platform_compatibility():
        data = get_json_body()
        url = data.get('url') if data else None
        if not isinstance(url, str) or not url.strip():
            return json_error('URL is required', 400)

        # Same check create-short applies, so "valid" here means the link will be accepted
        url = url.strip()
        is_valid, platform, error = validator.validate_url(url)
        if platform == 'unknown':
            platform = validator.get_platform_from_url(url)
        guidance = PLATFORM_GUIDANCE.get(platform)

        if is_valid:
            info = guidance
        else:
            info = {
                'status': 'invalid' if guidance else 'unsupported',
                'notes': error or 'Unsupported platform',
                'tips': guidance['tips'] if guidance else
                        ['Try a YouTube, TikTok, Facebook, Instagram or Douyin link'],
            }
        return jsonify({'platform': platform, 'valid': is_valid, 'info': info})

    @app.route('/api/video-categories')
    def get_video_categories():
        categories = [{'id': key, 'name': name} for key, name in VIDEO_CATEGORIES.items()]
        return jsonify({'categories': categories, 'total': len(categories)})

    @app.route('/api/trending')
    def get_trending():
        platform = request.args.get('platform', 'youtube').lower()
        if platform != 'youtube':
            return jsonify({
                'success': False,
                'error': f'Platform "{platform}" is not supported yet',
                'supported_platforms': ['youtube'],
            }), 400

        try:
            max_results = int(request.args.get('max_results', '20'))
        except ValueError:
            return json_error('max_results must be a number', 400)
        max_results = max(1, min(max_results, MAX_TRENDING_RESULTS))

        category = request.args.get('category', '0')
        region = request.args.get('region', 'US')
        videos = get_youtube_trending(category, region, max_results)
        return jsonify({
            # Sample data stands in when YouTube cannot be reached; the page must say so
            'sample': bool(videos) and all(str(video.get('id', '')).startswith('fallback') for video in videos),
            'api_key_configured': bool(os.getenv('YOUTUBE_API_KEY')),
            'platform': platform,
            'category': category,
            'region': region,
            'videos': videos,
            'total': len(videos),
            'timestamp': datetime.now().isoformat(),
        })

    # -- API: frames ------------------------------------------------------------

    @app.route('/api/extract', methods=['POST'])
    @limiter.limit("10 per minute")
    def extract_frames():
        """Synchronous: answers when the frames are ready. The pages use /api/jobs/extract."""
        extract_request, error = parse_extract_request(get_json_body())
        if error:
            return json_error(error, 400)
        record_id = start_request_record(extract_request.url, extract_request.platform)
        try:
            result = run_recorded(record_id, 'Frame extraction crashed',
                                  lambda: media_jobs.extract_frames(extract_request, record_id, NullReporter()))
        except JobFailed as failure:
            return json_error(failure.message, 400)
        return jsonify(result)

    # The file routes are cheap and a results page loads up to 50 frames at once (and
    # videos are fetched in ranges), so they are exempt from the API rate limit.
    @app.route('/frames/<filename>')
    @limiter.exempt
    def serve_frame(filename):
        path = resolve_in_folder(config.FRAMES_FOLDER, filename, ('.jpg',))
        if path is None:
            return json_error('Not found', 404)
        return send_from_directory(config.FRAMES_FOLDER, path.name)

    @app.route('/api/frames/archive', methods=['POST'])
    @limiter.limit("10 per minute")
    def download_frames_archive():
        """Several frames as one zip file. Takes frame file names, never paths."""
        data = get_json_body()
        names = data.get('filenames') if data else None
        if (not isinstance(names, list) or not names or len(names) > MAX_TIMESTAMPS
                or not all(isinstance(name, str) for name in names)):
            return json_error('filenames must be a list of frame file names', 400)
        paths = [path for path in (resolve_in_folder(config.FRAMES_FOLDER, name, ('.jpg',))
                                   for name in dict.fromkeys(names)) if path is not None]
        if not paths:
            return json_error('These frames are no longer on disk', 404)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_STORED) as archive:  # JPEGs do not compress further
            for path in paths:
                try:
                    archive.write(path, arcname=path.name)
                except OSError:
                    continue  # removed meanwhile (cleanup): the zip has the others
        buffer.seek(0)
        return send_file(buffer, mimetype='application/zip', as_attachment=True, download_name='frames.zip')

    # -- API: short videos --------------------------------------------------------

    @app.route('/api/clip-suggestions', methods=['POST'])
    @limiter.limit("10 per minute")
    def clip_suggestions():
        """The most replayed moments of a YouTube video, from its heatmap and captions."""
        data = get_json_body()
        url = data.get('url') if data else None
        if not isinstance(url, str) or not url.strip():
            return json_error('URL is required', 400)
        is_valid, platform, url_error = validator.validate_url(url.strip())
        if not is_valid:
            return json_error(url_error, 400)
        if platform != 'youtube':
            return json_error('Suggestions need YouTube data, so they work for YouTube links only.', 400)
        try:
            duration = parse_duration(data.get('duration', DEFAULT_SHORT_DURATION))
        except ShortVideoError:
            return json_error(f'Length must be between {MIN_SHORT_DURATION} and {MAX_SHORT_DURATION} seconds', 400)
        try:
            result = suggest_clips(url.strip(), duration, config.MAX_VIDEO_DURATION)
        except ClipFinderError as error:
            return json_error(error.user_message, 400)
        return jsonify({'success': True, **result})

    @app.route('/api/create-short', methods=['POST'])
    @limiter.limit("5 per minute")
    def create_short_video():
        """Synchronous: answers when the short is rendered. The pages use /api/jobs/create-short."""
        short_request, error = parse_short_request(get_json_body())
        if error:
            return json_error(error, 400)
        with LogContext(api_logger, "Short video creation"):
            record_id = start_request_record(short_request.url, short_request.platform)
            try:
                result = run_recorded(record_id, 'Rendering failed',
                                      lambda: media_jobs.render_short(short_request, NullReporter()))
            except JobFailed as failure:
                return json_error(failure.message, 400)
            return jsonify(result)

    # -- API: background jobs (download + extract / render, with progress and cancel) ----

    def start_job(kind: str, stages, record_id: int, work):
        """Queues `work` (it records its own outcome); answers 202 with the job, or 429."""
        queued_at = time.time()
        try:
            job = job_registry.submit(kind, stages, work, on_cancel_while_queued=lambda: finish_request_record(
                record_id, 'cancelled', queued_at, 'Cancelled by the user'))
        except JobQueueFull:
            finish_request_record(record_id, 'failed', queued_at, 'Too many jobs waiting')
            return json_error('Too many jobs are running or waiting. Wait for one to finish.', 429)
        return jsonify({'success': True, 'job': job_registry.snapshot(job.id)}), 202

    @app.route('/api/jobs/extract', methods=['POST'])
    @limiter.limit("10 per minute")
    def start_extract_job():
        extract_request, error = parse_extract_request(get_json_body())
        if error:
            return json_error(error, 400)
        # Recorded here: the request (IP, user agent) is gone by the time the job runs
        record_id = start_request_record(extract_request.url, extract_request.platform)
        return start_job('extract', EXTRACT_STAGES, record_id, lambda reporter: run_recorded(
            record_id, 'Frame extraction crashed',
            lambda: media_jobs.extract_frames(extract_request, record_id, reporter)))

    @app.route('/api/jobs/create-short', methods=['POST'])
    @limiter.limit("5 per minute")
    def start_short_job():
        short_request, error = parse_short_request(get_json_body())
        if error:
            return json_error(error, 400)
        record_id = start_request_record(short_request.url, short_request.platform)
        return start_job('short', SHORT_STAGES, record_id, lambda reporter: run_recorded(
            record_id, 'Rendering failed', lambda: media_jobs.render_short(short_request, reporter)))

    # Polled about once a second by an open page, so not counted against the API limit
    @app.route('/api/jobs')
    @limiter.exempt
    def list_jobs():
        return jsonify({'success': True, 'jobs': job_registry.snapshots()})

    @app.route('/api/jobs/<job_id>')
    @limiter.exempt
    def job_status(job_id):
        job = job_registry.snapshot(job_id) if JOB_ID_PATTERN.fullmatch(job_id) else None
        if job is None:
            return json_error('Job not found', 404)
        return jsonify({'success': True, 'job': job})

    @app.route('/api/jobs/<job_id>/cancel', methods=['POST'])
    @limiter.limit("30 per minute")
    def cancel_job(job_id):
        job = job_registry.cancel(job_id) if JOB_ID_PATTERN.fullmatch(job_id) else None
        if job is None:
            return json_error('Job not found', 404)
        return jsonify({'success': True, 'job': job})

    @app.route('/shorts/posters/<filename>')
    @limiter.exempt
    def serve_short_poster(filename):
        """Only serves posters that exist; they are made when a short is created or at startup."""
        folder = config.SHORTS_FOLDER / POSTER_FOLDER
        path = resolve_in_folder(folder, filename, ('.jpg',))
        if path is None:
            return json_error('Not found', 404)
        return send_from_directory(folder, path.name)

    @app.route('/shorts/<filename>')
    @limiter.exempt
    def serve_short_video(filename):
        path = resolve_in_folder(config.SHORTS_FOLDER, filename, ('.mp4',))
        if path is None:
            return json_error('Not found', 404)
        return send_from_directory(config.SHORTS_FOLDER, path.name)

    @app.route('/api/shorts')
    def list_generated_shorts():
        return jsonify({'success': True, 'shorts': list_shorts(config.SHORTS_FOLDER)})

    @app.route('/api/shorts/delete', methods=['POST'])
    @limiter.limit("30 per minute")
    def delete_generated_short():
        data = get_json_body()
        filename = data.get('filename') if data else None
        if not isinstance(filename, str):
            return json_error('filename is required', 400)
        path = resolve_in_folder(config.SHORTS_FOLDER, filename, ('.mp4',))
        if path is None:
            return json_error('Not found', 404)
        try:
            path.unlink()
        except PermissionError:
            return json_error('The short is open in another program. Close it and try again.', 409)
        except OSError as error:
            app_logger.error(f"Could not delete a short ({type(error).__name__})")
            return json_error('Could not delete the short', 500)
        remove_poster(path)
        return jsonify({'success': True})

    @app.route('/api/cleanup', methods=['POST'])
    @limiter.limit("5 per minute")
    def cleanup_files():
        files_deleted, space_freed, errors = extractor.cleanup_old_files()
        sync_posters(config.SHORTS_FOLDER)  # posters of deleted shorts go too
        response = {
            'success': True,
            'files_deleted': files_deleted,
            'space_freed_mb': space_freed,
            'message': f'Cleaned up {files_deleted} files, freed {space_freed} MB',
        }
        if errors:
            response['warnings'] = errors
        return jsonify(response)

    # -- API: YouTube -----------------------------------------------------------

    @app.route('/api/youtube-auth')
    @limiter.limit("120 per minute")  # the page polls this while the sign-in window is open
    def youtube_auth_status():
        """Sign-in state only. No side effects, so polling cannot disturb a sign-in in progress."""
        return jsonify({'authenticated': youtube_uploader.is_authenticated()})

    @app.route('/api/youtube-auth/start', methods=['POST'])
    @limiter.limit("20 per minute")
    def youtube_auth_start():
        """Begin sign-in and return the Google consent URL to open in a popup."""
        if youtube_uploader.is_authenticated():
            return jsonify({'authenticated': True})
        try:
            return jsonify({'authenticated': False, 'auth_url': youtube_uploader.begin_auth()})
        except YouTubeUploaderError as error:
            app_logger.warning(f"YouTube sign-in could not start: {error.user_message}")
            return jsonify({'success': False, 'authenticated': False, 'error': error.user_message}), 400

    @app.route('/oauth2callback')
    @limiter.limit("10 per minute")
    def oauth2_callback():
        """Where Google sends the user back after the consent screen."""
        if request.args.get('error'):
            return render_template_string(
                OAUTH_RESULT_PAGE, heading='Sign-in cancelled',
                message='YouTube access was not granted.'), 400

        code, state = request.args.get('code'), request.args.get('state')
        if not code or not state:
            return render_template_string(
                OAUTH_RESULT_PAGE, heading='Sign-in failed',
                message='The response from Google was incomplete.'), 400

        success, message = youtube_uploader.complete_auth(code, state)
        heading = 'YouTube connected' if success else 'Sign-in failed'
        return render_template_string(
            OAUTH_RESULT_PAGE, heading=heading, message=message), (200 if success else 400)

    @app.route('/api/upload-to-youtube', methods=['POST'])
    @limiter.limit("5 per minute")
    def upload_to_youtube():
        data = get_json_body()
        if data is None:
            return json_error('JSON body required', 400)

        # Only the name of a short created by this app is accepted, never a path
        filename = data.get('filename')
        if not isinstance(filename, str) or not filename:
            return json_error('filename is required', 400)

        title = data.get('title', '')
        description = data.get('description', '')
        tags = data.get('tags')
        privacy = data.get('privacy', 'private')
        if not isinstance(title, str) or not isinstance(description, str):
            return json_error('title and description must be text', 400)
        if tags is not None and not isinstance(tags, list):
            return json_error('tags must be a list', 400)
        if privacy not in PRIVACY_STATUSES:
            return json_error(f"privacy must be one of: {', '.join(PRIVACY_STATUSES)}", 400)

        video_path = resolve_in_folder(config.SHORTS_FOLDER, filename, ('.mp4',))
        if video_path is None:
            return json_error('Video not found', 404)

        if not youtube_uploader.is_authenticated():
            return json_error('Please sign in to YouTube first', 401)

        is_valid, validation_message = youtube_uploader.validate_short_video(str(video_path))
        if not is_valid:
            return json_error(f'Video validation failed: {validation_message}', 400)

        success, message, video_id = youtube_uploader.upload_video(
            video_path=str(video_path), title=title, description=description,
            tags=tags, privacy_status=privacy, is_short=True)
        if not success:
            return json_error(message, 502)

        return jsonify({
            'success': True,
            'message': message,
            'privacy': privacy,
            'video_id': video_id,
            'youtube_url': f'https://www.youtube.com/watch?v={video_id}',
            'studio_url': f'https://studio.youtube.com/video/{video_id}/edit',
        })

    @app.route('/api/youtube-quota')
    def youtube_quota():
        return jsonify(youtube_uploader.get_upload_quota_info())

    # Done here, not in main(), so gunicorn and tests get it too
    run_startup_cleanup()
    return app


def run_startup_cleanup() -> None:
    """Sweep files older than AUTO_CLEANUP_HOURS, and renders cut off when the app last stopped."""
    try:
        deleted, freed_mb, _ = extractor.cleanup_old_files()
        partial = remove_partial_renders(get_config().SHORTS_FOLDER)
        # Posters for shorts made before they existed; and none for shorts that were deleted
        posters_made, posters_removed = sync_posters(get_config().SHORTS_FOLDER)
        app_logger.info("Startup cleanup finished", files_deleted=deleted, space_freed_mb=freed_mb,
                        partial_renders_removed=partial, posters_made=posters_made,
                        posters_removed=posters_removed)
    except (OSError, ValueError) as error:
        app_logger.warning(f"Startup cleanup failed ({type(error).__name__})")


def main():
    """Main entry point"""
    config = get_config()
    app = create_app()

    if config.HOST not in LOOPBACK_HOSTS:
        app_logger.warning(
            "Listening on a non-loopback address: this app has no login. "
            "Only do this on a trusted network and set ALLOWED_HOSTS.",
            host=config.HOST)
    app_logger.info("Starting Video Frame Extractor", environment=config.FLASK_ENV,
                    host=config.HOST, port=config.PORT, debug=config.DEBUG)

    app.run(host=config.HOST, port=config.PORT, debug=config.DEBUG, threaded=True)


if __name__ == '__main__':
    main()
