# VideoExtract

A local web app that downloads a video from a link, extracts still frames at the timestamps you choose, and cuts short vertical clips (9:16) that you can download or upload to your own YouTube channel.

- **Frame extraction**: paste a link and a list of timestamps, get a JPEG per timestamp.
- **Short videos**: pick a start time and length (1-300 s), optionally crop to 9:16 and add a caption.
- **YouTube upload** (optional): upload a finished short to your own channel, private by default.
- **Trending page** (optional): the most popular YouTube videos, via the official YouTube Data API.
- **Dashboard**: request history and system load.

Downloads are done by [yt-dlp](https://github.com/yt-dlp/yt-dlp), frames by OpenCV, clips by MoviePy.

> **Built for personal, local use.** The app has no login and listens on `127.0.0.1` only. Read [Responsible use](#responsible-use) before downloading anything.

## Contents

[Supported platforms](#supported-platforms-and-limits) · [Quick start](#quick-start) · [Usage](#usage) · [Configuration](#configuration) · [Platform authentication](#platform-authentication) · [YouTube upload](#youtube-upload) · [API](#api) · [Architecture](#architecture) · [Deployment](#deployment) · [Testing](#testing) · [Troubleshooting](#troubleshooting) · [Security](#security-notes) · [Responsible use](#responsible-use) · [History and roadmap](#history-and-roadmap) · [Contributing](#contributing) · [License](#license)

## Supported platforms and limits

| Platform | Accepted links | Notes |
|---|---|---|
| YouTube | `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/` | Public videos |
| TikTok | `/@user/video/<id>`, `vm.tiktok.com`, `vt.tiktok.com`, `tiktok.com/t/` | Some videos are region-blocked |
| Instagram | `/p/`, `/reel/`, `/reels/`, `/tv/` | Public posts; restricted content needs [cookies](#platform-authentication) |
| Facebook | `/<page>/videos/<id>`, `/watch/?v=<id>`, `/reel/<id>`, `fb.watch/` | Public videos only |
| Douyin | `douyin.com/video/<id>` | `v.douyin.com` short links are not supported by yt-dlp |

Limits (all configurable, see [Configuration](#configuration)): the source video may be at most `MAX_VIDEO_DURATION` seconds (1 hour by default), `MAX_DOWNLOAD_MB` megabytes (500) and 720p; playlists are never downloaded; a short is 1-300 seconds. YouTube only accepts uploads of up to 60 seconds as Shorts.

Only the five platforms above are fetched: yt-dlp's generic extractor, which would download from arbitrary sites, is switched off.

## Quick start

Requires Python 3.10 or newer (CI runs 3.10 and 3.11). FFmpeg is bundled with MoviePy (`imageio-ffmpeg`), so you do not need to install it.

**Windows (PowerShell)**

```powershell
git clone https://github.com/quyetnn1102/video_frame_extractor.git
cd video_frame_extractor
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app_enhanced.py
```

**Linux / macOS**

```bash
git clone https://github.com/quyetnn1102/video_frame_extractor.git
cd video_frame_extractor
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app_enhanced.py
```

Open <http://localhost:5000>. Downloads, frames and shorts are stored in `downloads/`, `extracted_frames/` and `generated_shorts/`; files older than `AUTO_CLEANUP_HOURS` are removed at startup (and by `POST /api/cleanup`).

**Optional extras**

- *Text overlay on shorts* needs [ImageMagick](https://imagemagick.org/). Without it the short is still created, just without the caption. If MoviePy cannot find ImageMagick, set the `IMAGEMAGICK_BINARY` environment variable to the path of `magick.exe` / `convert`.
- *Trending page* needs a YouTube Data API key in `.env`: `YOUTUBE_API_KEY=...`. Without one the page shows a single demo entry.

## Usage

**Extract frames** (`/`): paste a video link and enter timestamps, one per line, as seconds (`90`), `MM:SS` (`1:30`) or `H:MM:SS` (`1:02:03`). Seconds must be 00-59 (and minutes too in `H:MM:SS`), a timestamp cannot exceed `MAX_VIDEO_DURATION`, and at most 50 are accepted. The video is deleted after the frames are extracted.

**Create a short** (`/create-short`): paste a link, choose the length and an optional start time (`90` or `1:30`; blank starts at the beginning), quality, vertical crop and caption. Wide or tall sources are cropped around the center to 9:16 and scaled to 1080x1920. Then download the MP4 or upload it to YouTube.

**Trending** (`/trending`): browse popular YouTube videos by region and category, and send one to the extractor.

**Dashboard** (`/dashboard`): request counts per platform, success rate, extracted frames, and CPU/memory/disk usage. Frame extraction and short creation are recorded; other calls are not.

## Configuration

Settings come from environment variables, which can be put in a `.env` file in the project root (it is git-ignored).

| Variable | Default | Purpose |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `5000` | Where the app listens. Keep the loopback address unless you know why not |
| `ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Host headers the app answers to (blocks DNS-rebinding attacks); add your domain behind a proxy |
| `FLASK_ENV` | `development` | `development`, `production` or `testing`. Any other value is an error |
| `FLASK_DEBUG` | off | Enables the interactive Werkzeug debugger. Never on a shared machine |
| `SECRET_KEY` | random per run | Required in production, at least 32 characters |
| `TRUSTED_PROXY_COUNT` | `0` | Number of reverse proxies in front of the app; `X-Forwarded-*` is ignored when 0 |
| `RATE_LIMIT_PER_MINUTE` | `30` (`10` in production) | Default per-IP limit; some routes have their own, see [API](#api) |
| `RATE_LIMIT_ENABLED` | `true` | Set `false` to disable rate limiting |
| `MAX_VIDEO_DURATION` | `3600` (`1800` in production) | Longest source video and latest timestamp, in seconds |
| `MAX_DOWNLOAD_MB` | `500` | Largest download |
| `SOCKET_TIMEOUT` / `DOWNLOAD_RETRIES` | `30` / `2` | Network stall timeout (s) and retries for downloads |
| `AUTO_CLEANUP_HOURS` | `24` (`4` in production) | Age after which files are deleted |
| `USE_BROWSER_COOKIES` | off | Let yt-dlp read your browser's cookies for Instagram (see below) |
| `YOUTUBE_API_KEY` | none | Trending page only |
| `YOUTUBE_REDIRECT_URI` | `http://localhost:<PORT>/oauth2callback` | OAuth redirect for YouTube upload |
| `LOG_LEVEL` | `INFO` | Log level; logs go to `logs/app.log` |

## Platform authentication

Most public videos need no login. **Instagram** sometimes refuses content unless you are signed in.

1. Sign in to Instagram in a **separate browser profile** with an account you do not mind losing.
2. Export that profile's cookies in Netscape format with a cookies.txt exporter you trust (review the extension's permissions first; some are malicious).
3. Save the file as `instagram_cookies.txt` in the project root. `instagram_cookies_template.txt` shows the format. The file is git-ignored.
4. The app uses the file automatically when it exists. Reading your *browser's* cookies directly is off unless you set `USE_BROWSER_COOKIES=true`, because it exposes your whole browser profile to the download process.

Treat `instagram_cookies.txt` like a password: never commit or share it, and delete it when you are done. Using a logged-in account to automate downloads can violate Instagram's terms and get the account restricted (see [Responsible use](#responsible-use)). Content that needs a login may still fail if the account cannot see it.

## YouTube upload

Optional. Uploads go to **your own channel**.

1. In the [Google Cloud Console](https://console.cloud.google.com/), create a project and enable **YouTube Data API v3**.
2. Configure the OAuth consent screen. While the app is in *Testing* mode, add your Google account as a test user.
3. Create an OAuth client ID. Choose **Desktop app** (nothing to register), or **Web application** and add `http://localhost:5000/oauth2callback` as an authorized redirect URI.
4. Download the JSON and save it as `client_secrets.json` in the project root (`client_secrets.json.template` shows the format; the file is git-ignored).
5. In `/create-short`, create a short and press **Upload to YouTube**. A Google sign-in window opens; after you approve, the upload starts.

Details worth knowing:

- Uploads are **private** by default. Google locks videos uploaded through API projects that have not passed its compliance audit to private; see the [videos.insert reference](https://developers.google.com/youtube/v3/docs/videos/insert). Change visibility in YouTube Studio.
- Only the `youtube.upload` scope is requested: the app cannot read or manage your channel.
- Credentials are saved to `youtube_credentials.json` (git-ignored, owner-only permissions). Delete it to sign out. A `youtube_credentials.pickle` from an older version is ignored; sign in again.
- Quotas depend on your project, see the [quota page](https://developers.google.com/youtube/v3/determine_quota_cost).
- Shorts must be at most 60 seconds and vertical or square.

## API

All endpoints return JSON (errors as `{"success": false, "error": "..."}`) and require a `Host` header from `ALLOWED_HOSTS`. Request bodies must be JSON objects. The default rate limit is `RATE_LIMIT_PER_MINUTE` per IP.

| Method and path | Purpose | Limit |
|---|---|---|
| `GET /`, `/create-short`, `/trending`, `/dashboard` | Pages | default |
| `POST /api/validate-url` `{url}` | Validate a link and fetch title/duration | 30/min |
| `POST /api/video-info` `{url}` | Video details without downloading | 20/min |
| `POST /api/test-platform` `{url}` | Platform guidance for a link | 30/min |
| `POST /api/extract` `{url, timestamps[]}` | Download, extract frames, delete the download | 10/min |
| `POST /api/create-short` `{url, start_time, duration, quality, vertical_format, text_overlay}` | Create a short | 5/min |
| `GET /frames/<file>`, `GET /shorts/<file>` | Serve generated files | default |
| `POST /api/cleanup` | Delete files older than `AUTO_CLEANUP_HOURS` | 5/min |
| `GET /api/trending?region=&category=&max_results=` | Popular YouTube videos | default |
| `GET /api/video-categories` | Category list | default |
| `GET /api/youtube-auth` | Sign-in state only (safe to poll) | 120/min |
| `POST /api/youtube-auth/start` | Begin sign-in; returns the Google consent URL | 20/min |
| `GET /oauth2callback` | Google redirects back here after sign-in | 10/min |
| `POST /api/upload-to-youtube` `{filename, title, description, tags, privacy}` | Upload a short from `generated_shorts/` by file name | 5/min |
| `GET /api/youtube-quota` | Pointer to the official quota rules | default |
| `GET /api/health`, `GET /api/dashboard-data` | Health and dashboard data | default |

Example:

```bash
curl -X POST http://localhost:5000/api/extract \
  -H "Content-Type: application/json" \
  -d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "timestamps": ["30", "1:23"]}'
```

`/api/create-short` accepts `quality` of `low`, `medium` (default) or `high`, `vertical_format` as a JSON boolean, and `text_overlay` as `{"text": "...", "position": "top|center|bottom", "fontsize": 8-200, "color": "white", "stroke_color": "black", "stroke_width": 0-10}` with at most 100 characters of text.

## Architecture

```
app_enhanced.py      Flask app: pages, JSON API, Host check, security headers, error handling
config.py            Settings from environment variables
validators.py        URL / timestamp / filename validation, safe path resolution
link_resolver.py     Safe resolution of fb.watch short links
video_processor.py   yt-dlp download (with limits) and OpenCV frame extraction
short_video.py       MoviePy short rendering and request validation
trending.py          YouTube trending via the Data API
youtube_uploader.py  OAuth sign-in and upload
database.py          SQLite request log used by the dashboard (app_data.db)
logger.py            Logging
deploy.py            Production helper (Linux): checks, systemd and nginx config
templates/           index, create_short, trending, dashboard pages
tests/               Offline unit tests
scripts/smoke_test.py  Manual check against a running server
```

Flow: the browser calls the JSON API; the app validates the request, yt-dlp downloads the video into `downloads/` (a platform extractor only, with size, duration and timeout limits), OpenCV extracts frames or MoviePy renders a short, the source download is deleted, and the result is served from `extracted_frames/` or `generated_shorts/`.

Processing runs inside the request, so a long clip can take minutes. There is no job queue.

## Deployment

The app is meant for localhost. If you must expose it, put it behind a reverse proxy that **adds authentication** (the app has none) and TLS, set `FLASK_ENV=production`, a strong `SECRET_KEY`, `ALLOWED_HOSTS`, and `TRUSTED_PROXY_COUNT=1`. `python deploy.py` checks the environment, runs the tests and writes example systemd and nginx files to `production_configs/`.

On Linux, run it with one worker and threads, because the YouTube sign-in state and the rate-limit counters live in process memory:

```bash
gunicorn --workers 1 --threads 4 --timeout 900 --bind 127.0.0.1:8000 'app_enhanced:create_app()'
```

Gunicorn does not run on Windows; use `python app_enhanced.py` there.

## Testing

```bash
python -m unittest discover -s tests -t .
```

The suite is offline and fast: it covers validation, the Flask routes (with the extractor and uploader mocked), the yt-dlp options, frame extraction and short rendering on a synthetic video, the YouTube OAuth and upload logic, and static checks on the templates. CI runs it on Ubuntu and Windows.

`python scripts/smoke_test.py` calls a running server and downloads a real video, so it is manual only (add `--create-short` to render one).

## Troubleshooting

| Symptom | Fix |
|---|---|
| A platform stops working | Upgrade yt-dlp first: `pip install -U yt-dlp`, then update the pin in `requirements.txt` |
| `No suitable extractor` | The link form is not supported (for example `v.douyin.com`); use the full video URL |
| `Invalid Host header` | You opened the app under another name; add it to `ALLOWED_HOSTS` |
| Instagram: login required / restricted | See [Platform authentication](#platform-authentication) |
| TikTok: format error | The video may be region-blocked or restricted |
| "The video was not downloaded" | It exceeds `MAX_VIDEO_DURATION` or `MAX_DOWNLOAD_MB`, or is a live stream |
| "Text overlay was skipped" | Install ImageMagick (see [Quick start](#quick-start)) |
| YouTube sign-in fails | Check that `client_secrets.json` exists, your account is a test user, and the redirect URI matches `http://localhost:5000/oauth2callback` |
| YouTube upload is private | Expected for API projects that have not passed Google's audit |
| `ModuleNotFoundError: google_auth_oauthlib` | Run `pip install -r requirements.txt`; the app starts without it but cannot sign in to YouTube |

Logs are in `logs/app.log`.

## Security notes

Implemented: loopback-only binding and a `Host` allow-list; exact host matching for video URLs (no lookalike domains, embedded credentials or ports); a fixed extractor allow-list so yt-dlp cannot fetch arbitrary URLs; size, duration and timeout limits; client-supplied file names resolved strictly inside the output folders; uploads by file name only; JSON error responses with no internal details; per-route rate limits; a Content-Security-Policy and other security headers; no data interpolated into HTML; YouTube credentials stored as JSON with an OAuth `state` check; browser cookies opt-in.

Not implemented, by design for a local tool: **user accounts or login** and **CSRF tokens** (there are no cookie sessions to attack, but add both if you ever add login). The CSP still allows inline scripts because the pages use them. Do not expose the app to a network without an authenticating proxy.

Secrets (`.env`, `client_secrets.json`, `youtube_credentials.json`, `instagram_cookies.txt`) are git-ignored; never commit them. To report a vulnerability, open a private security advisory on GitHub.

## Responsible use

This is a personal tool. Downloading a video does not give you the right to use it.

- Only process videos you **own or have permission to use**, and respect copyright, privacy and other people's likenesses.
- Platform terms restrict downloading and automated access outside their official features. See the [YouTube Terms of Service](https://www.youtube.com/t/terms), the [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies) (which prohibit downloading or caching YouTube content through the API), the [TikTok Terms of Service](https://www.tiktok.com/legal/page/row/terms-of-service/en) and Meta's [Automated Data Collection Terms](https://www.facebook.com/apps/site_scraping_tos_terms.php). Breaking them can get your accounts restricted, and you are responsible for how you use this tool.
- The app does not and must not be used to bypass DRM, paywalls, age or region restrictions, or access controls.
- Prefer official routes where they exist: download your own videos from YouTube Studio, use the platforms' APIs or embeds, or work from files you already have.
- Do not republish other people's content without a licence or their permission; the app adds no attribution for you.

This section is general information, not legal advice.

## History and roadmap

- **2.1** (current): hardened for local use (loopback binding, Host check, strict URL and path handling, download limits, safe errors, CSP), a working create-short page, a real YouTube OAuth callback with JSON credential storage, request logging into the dashboard, a larger offline test suite, CI, and a single README. The legacy monolithic `app.py` was removed.
- **2.0**: modular architecture with an application factory, SQLite analytics, structured logging, rate limiting and YouTube upload.
- **1.x**: the original single-file app.

Ideas, not promises: a background job queue with progress, a Redis-backed rate limiter, a Dockerfile, upgrading Flask/Werkzeug/Pillow to current releases, and an upload option for your own video files instead of links.

## Contributing

Issues and pull requests are welcome. Keep changes small, add tests (`python -m unittest discover -s tests -t .` must pass), and do not commit credentials, cookies or downloaded media.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Acknowledgments

[yt-dlp](https://github.com/yt-dlp/yt-dlp), [OpenCV](https://opencv.org/), [MoviePy](https://zulko.github.io/moviepy/), [Flask](https://flask.palletsprojects.com/), [Flask-Limiter](https://flask-limiter.readthedocs.io/), the Google API client libraries, [Bootstrap](https://getbootstrap.com/) and [Font Awesome](https://fontawesome.com/).
