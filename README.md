# Tallframe

**Turn videos into short clips and frames.**

A local web app (the repository is still called `video_frame_extractor`) that downloads a video from a link, extracts still frames at the timestamps you choose, and cuts short vertical clips (9:16) that you can download or upload to your own YouTube channel.

- **Frame extraction**: paste a link and a list of timestamps, get a JPEG per timestamp.
- **Short videos**: pick a start time and length (1-300 s), optionally crop to 9:16 and add a caption.
- **Vietnamese subtitles** (offline): a copy of a short with its speech subtitled in Vietnamese.
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
| Douyin | `douyin.com/video/<id>`, any `douyin.com` page with `?modal_id=<id>`, `v.douyin.com` share links | Often refused: Douyin needs browser cookies (see [Platform authentication](#platform-authentication)) and now checks signatures only its own pages make, so some videos cannot be downloaded at all |

Limits (all configurable, see [Configuration](#configuration)): the source video may be at most `MAX_VIDEO_DURATION` seconds (1 hour by default) and `MAX_DOWNLOAD_MB` megabytes (500; a running download is aborted when it passes this); playlists are never downloaded; a short is 1-300 seconds. The app asks for 720p or lower, but that is a preference: some sites only offer a single quality. This app checks uploads against the 60-second limit of classic YouTube Shorts.

Only the five platforms above are fetched: yt-dlp's generic extractor, which would download from arbitrary sites, is switched off.

## Quick start

Requires Python 3.10 or newer (CI runs 3.10 and 3.11) and [uv](https://docs.astral.sh/uv/getting-started/installation/), which manages the dependencies. FFmpeg is bundled with MoviePy (`imageio-ffmpeg`), so you do not need to install it. For YouTube, also install [Node.js](https://nodejs.org) (or Deno): yt-dlp runs YouTube's download challenges in it, and without one YouTube often stops downloads with "HTTP Error 403".

`uv sync` creates the project's own `.venv` from the exact versions in `uv.lock` (and downloads a matching Python if needed). Dependencies never go into your global Python, where the pinned versions could downgrade packages other tools rely on.

**Windows (PowerShell)**

```powershell
git clone https://github.com/quyetnn1102/video_frame_extractor.git
cd video_frame_extractor
uv sync
uv run python app_enhanced.py
```

**Linux / macOS**

```bash
git clone https://github.com/quyetnn1102/video_frame_extractor.git
cd video_frame_extractor
uv sync
uv run python app_enhanced.py
```

`uv run` always uses the project's `.venv`, so you never need to activate it; in an editor, select `.venv\Scripts\python.exe` (Windows) or `.venv/bin/python` as the interpreter. To change dependencies, use `uv add <package>` / `uv remove <package>` (they are declared in `pyproject.toml`) and commit both `pyproject.toml` and `uv.lock`.

Open <http://localhost:5000>. Downloads, frames and shorts are stored in `downloads/`, `extracted_frames/` and `generated_shorts/`; files older than `AUTO_CLEANUP_HOURS` are removed at startup (and by `POST /api/cleanup`).

**Optional extras**

- *Text overlay on shorts* needs [ImageMagick](https://imagemagick.org/). Without it the short is still created, just without the caption. If MoviePy cannot find ImageMagick, set the `IMAGEMAGICK_BINARY` environment variable to the path of `magick.exe` / `convert`.
- *Trending page* needs a YouTube Data API key in `.env`: `YOUTUBE_API_KEY=...`. Without one the page shows a single demo entry.

## Usage

**Home** (`/`): paste a link and choose **Create short** or **Extract frames**; the link is carried over to that page. Your most recent shorts and a short guide are shown below.

**Extract frames** (`/extract`): paste a video link and enter timestamps, one per line, as seconds (`90`), `MM:SS` (`1:30`) or `H:MM:SS` (`1:02:03`). Seconds must be 00-59 (and minutes too in `H:MM:SS`), a timestamp cannot exceed `MAX_VIDEO_DURATION`, and at most 50 are accepted. The video is deleted after the frames are extracted.

**Create a short** (`/create-short`): paste a link, choose the length and an optional start time (`90` or `1:30`; blank starts at the beginning), quality, vertical crop and caption. Wide or tall sources are cropped around the center to 9:16 and scaled to 1080x1920. The link is analyzed first, so a start time or length past the end of the video is caught before anything is downloaded.

**Your shorts** (`/shorts`): every short you have made, kept until you delete it. Search titles, sort them, show only Vietsub copies, play one, download it; **More** has Add Vietnamese subtitles, Upload to YouTube (or how to set it up), Copy file name and Delete. Badges say which shorts are Vietsub copies, in use (by subtitles or an upload) or already uploaded.

**Vietnamese subtitles**: in Your shorts, **More > Add Vietnamese subtitles** makes a copy (titled "... Vietsub") with the speech subtitled in Vietnamese; the original is kept. It works on this computer, without an online service: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) writes down the speech (Chinese, English or Vietnamese), the [Argos Translate](https://github.com/argosopentech/argos-translate) models translate it (Chinese through English), subtitles already burned into the picture (white text with a dark outline, as on Douyin and TikTok) are found and blurred while they show, and the Vietnamese lines are drawn in their place. The first run downloads the models into `models/` (about 500 MB for speech, 70 MB per translation model); after that it needs no network. A 1-minute short takes about 2 minutes on a laptop CPU. Machine translation is understandable but not polished, and names or wordplay come out literally.

**Trending** (`/trending`): browse popular YouTube videos by region and category, and send one to Create short or Extract frames. When the list is sample data, the page says why (no API key, a refused key, the daily quota, or YouTube not answering).

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
| `MAX_CONCURRENT_JOBS` | `2` | Downloads/renders that run at the same time; more wait in line |
| `WHISPER_MODEL` | `small` | Speech model for Vietnamese subtitles: `tiny`, `base`, `small`, `medium` or `large-v3` (larger hears better but is slower and a bigger download) |
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

**Douyin** answers only browsers, so yt-dlp needs cookies from one ("Fresh cookies are needed"). No login is required:

1. Open [douyin.com](https://www.douyin.com) in your browser and play any video, so the site sets its cookies.
2. Export the cookies for `douyin.com` in Netscape format (same kind of exporter as above) and save them as `douyin_cookies.txt` in the project root. The file is git-ignored; treat it like a password.
3. The app uses the file automatically. Export again when Douyin refuses: the cookies expire.

This may still fail. Since September 2026 Douyin also checks request signatures that only its own pages can create, which has broken most download tools. The app does not try to forge them.

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
- Credentials are saved to `youtube_credentials.json` (git-ignored). On Linux and macOS the file is owner-only; on Windows it inherits the permissions of the project folder, so keep the project in a folder only you can read. Delete the file to sign out. A `youtube_credentials.pickle` from an older version is ignored; sign in again.
- Quotas depend on your project, see the [quota page](https://developers.google.com/youtube/v3/determine_quota_cost).
- The app only uploads videos of up to 60 seconds that are vertical or square (the classic Shorts rules).

## API

All endpoints return JSON (errors as `{"success": false, "error": "..."}`) and require a `Host` header from `ALLOWED_HOSTS`. Request bodies must be JSON objects. The default rate limit is `RATE_LIMIT_PER_MINUTE` per IP.

| Method and path | Purpose | Limit |
|---|---|---|
| `GET /`, `/extract`, `/create-short`, `/shorts`, `/trending`, `/dashboard` | Pages | default |
| `POST /api/validate-url` `{url}` | Validate a link and fetch title/duration | 30/min |
| `POST /api/video-info` `{url}` | Video details without downloading (title, length, frame size, platform); a failure gives `reason` (`invalid` or `unreadable`) and the platform's tips | 20/min |
| `POST /api/test-platform` `{url}` | Platform guidance for a link | 30/min |
| `POST /api/extract` `{url, timestamps[]}` | Download, extract frames, delete the download | 10/min |
| `POST /api/create-short` `{url, start_time, duration, quality, vertical_format, text_overlay}` | Create a short | 5/min |
| `POST /api/clip-suggestions` `{url, duration}` | Up to 5 moments of a YouTube video worth a short, from its "Most replayed" heatmap and captions (read without downloading the video) | 10/min |
| `POST /api/jobs/extract` `{url, timestamps[]}` | Same as `/api/extract`, as a background job: answers `202` with the job at once | 10/min |
| `POST /api/jobs/create-short` (same body as `/api/create-short`) | Same as `/api/create-short`, as a background job | 5/min |
| `POST /api/jobs/subtitles` `{filename}` | Background job: a copy of a short in `generated_shorts/` with Vietnamese subtitles (old burned-in subtitles blurred) | 5/min |
| `GET /api/jobs` | Jobs of the last hour, newest first (`state`, `stage`, `progress`, `result` or `error`) | none (polled) |
| `GET /api/jobs/<id>` | One job; the pages poll it about once a second | none (polled) |
| `POST /api/jobs/<id>/cancel` | Stop a job; a partial download or render is deleted | 30/min |
| `GET /frames/<file>`, `GET /shorts/<file>` | Serve generated files | default |
| `GET /shorts/posters/<file>` | A short's thumbnail (made when the short is created, or at startup for older ones) | none (file) |
| `POST /api/frames/archive` `{filenames[]}` | The named frames (up to 50) as one `frames.zip` | 10/min |
| `GET /api/shorts?offset=&limit=` | A page of the shorts in `generated_shorts/`, newest first, with `total`; each short says whether a job or upload is using it (`busy`) and why YouTube would refuse it (`upload_problem`) | default |
| `POST /api/shorts/delete` `{filename}` | Delete a short by file name (`409` while it is in use) | 30/min |
| `POST /api/cleanup` | Delete files older than `AUTO_CLEANUP_HOURS` | 5/min |
| `GET /api/trending?region=&category=&max_results=` | Popular YouTube videos; `reason` says why when they are sample data (`no_key`, `bad_key`, `quota`, `unavailable`) or none (`empty`) | default |
| `GET /api/video-categories` | Category list | default |
| `GET /api/youtube-auth` | Sign-in state, and whether upload is set up (`configured`); safe to poll | 120/min |
| `POST /api/youtube-auth/start` | Begin sign-in; returns the Google consent URL | 20/min |
| `GET /oauth2callback` | Google redirects back here after sign-in | 10/min |
| `POST /api/upload-to-youtube` `{filename, title, description, tags, privacy}` | Upload a short from `generated_shorts/` by file name | 5/min |
| `GET /api/youtube-quota` | Pointer to the official quota rules | default |
| `GET /api/health`, `GET /api/dashboard-data` | Health and dashboard data | default |

The pages use the job routes, so a long download or render shows its stage, progress and elapsed time, can be cancelled, and keeps running if you leave the page (it shows up again when you come back). Jobs are kept in memory for an hour; restarting the app forgets them, but the files they produced stay.

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
subtitles.py         Vietnamese subtitles: speech to text, burned-in subtitle detection and blur, drawing
translation.py       Offline translation with the Argos models (downloaded once into models/)
trending.py          YouTube trending via the Data API
youtube_uploader.py  OAuth sign-in and upload
database.py          SQLite request log used by the dashboard (app_data.db)
logger.py            Logging
deploy.py            Production helper (Linux): checks, systemd and nginx config
templates/           index (home), extract, create_short, trending, dashboard pages; partials/ holds the shared sidebar and top bar
static/              Shared stylesheet (css/app.css), scripts (js/) and the self-hosted font (fonts/, SIL OFL)
assets/fonts/        Be Vietnam Pro, the subtitle font (every Vietnamese accent; SIL OFL)
tests/               Offline unit tests
scripts/smoke_test.py  Manual check against a running server
```

Flow: the browser calls the JSON API; the app validates the request, yt-dlp downloads the video into `downloads/` (a platform extractor only, with size, duration and timeout limits), OpenCV extracts frames or MoviePy renders a short, the source download is deleted, and the result is served from `extracted_frames/` or `generated_shorts/`.

The pages run this as a background job (`jobs.py`, `MAX_CONCURRENT_JOBS` at a time, more wait in line) and poll it for progress, so a long clip no longer holds a request open; `/api/extract` and `/api/create-short` still do the same work inside the request for scripts. Jobs live in process memory: one app process, and a restart forgets them (partial renders are removed at the next start).

## Deployment

The app is meant for localhost. If you must expose it, put it behind a reverse proxy that **adds authentication** (the app has none) and TLS, set `FLASK_ENV=production`, a strong `SECRET_KEY`, `ALLOWED_HOSTS`, and `TRUSTED_PROXY_COUNT=1`. Install exactly the locked versions, without the dev tools, with `uv sync --frozen --no-dev`. Then `uv run --frozen --no-dev python deploy.py` checks the environment, runs the tests and writes example systemd and nginx files to `production_configs/`.

On Linux, run it with one worker and threads, because the YouTube sign-in state and the rate-limit counters live in process memory:

```bash
gunicorn --workers 1 --threads 4 --timeout 900 --bind 127.0.0.1:8000 'app_enhanced:create_app()'
```

Gunicorn does not run on Windows; use `python app_enhanced.py` there.

## Testing

```bash
uv run python -m unittest discover -s tests -t .
```

The suite is offline and fast: it covers validation, the Flask routes (with the extractor and uploader mocked), the yt-dlp options, frame extraction and short rendering on a synthetic video, the YouTube OAuth and upload logic, and static checks on the templates. CI runs it on Ubuntu and Windows.

`python scripts/smoke_test.py` calls a running server and downloads a real video, so it is manual only (add `--create-short` to render one).

## Troubleshooting

| Symptom | Fix |
|---|---|
| A platform stops working | Upgrade yt-dlp first: `uv lock --upgrade-package yt-dlp`, then set the new version in the `yt-dlp==` pin in `pyproject.toml` and run `uv sync` |
| `No suitable extractor` | The link form is not supported; use the full video URL |
| Douyin: "Douyin only answers browsers" | Export your douyin.com cookies to `douyin_cookies.txt` (see [Platform authentication](#platform-authentication)). It may still fail: Douyin has blocked most download tools since September 2026 |
| `Invalid Host header` | You opened the app under another name; add it to `ALLOWED_HOSTS` |
| Instagram: login required / restricted | See [Platform authentication](#platform-authentication) |
| TikTok: "did not send the video page" | Run `uv sync` (it installs `curl-cffi`, which lets yt-dlp present itself as a browser), restart the app, or wait a few minutes if TikTok is rate limiting you |
| TikTok: format error | The video may be region-blocked or restricted |
| "The video was not downloaded" | It exceeds `MAX_VIDEO_DURATION` or `MAX_DOWNLOAD_MB`, or is a live stream |
| "Text overlay was skipped" | Install ImageMagick (see [Quick start](#quick-start)) |
| YouTube download stops with "HTTP Error 403: Forbidden" | Install [Node.js](https://nodejs.org) (or Deno) and restart the app: yt-dlp runs YouTube's download challenges in it. If it is installed, update yt-dlp (`uv lock --upgrade-package yt-dlp`) |
| YouTube sign-in fails | Check that `client_secrets.json` exists, your account is a test user, and the redirect URI matches `http://localhost:5000/oauth2callback` |
| Trending shows a single demo entry | `logs/app.log` says why: `HTTP 400, API_KEY_INVALID` is a wrong or deleted key, `HTTP 403, API_KEY_HTTP_REFERRER_BLOCKED` or `API_KEY_IP_ADDRESS_BLOCKED` is a key restriction (use *None* or an IP restriction, not a website restriction, because the server sends the request), `SERVICE_DISABLED` means enable *YouTube Data API v3* in the Google Cloud project, `quotaExceeded` means the daily quota is used up |
| YouTube upload is private | Expected for API projects that have not passed Google's audit |
| pip prints dependency conflicts for tools like `fastmcp` or `dbt` | Something was installed into a shared Python. Use `uv sync` / `uv run` as in [Quick start](#quick-start) so the project only touches its own `.venv`; to repair the shared one, reinstall the versions it had before |
| `Fatal error in launcher: Unable to create process` or `uv sync` says access denied on `.venv` | A virtual environment was moved or is in use. Close editors and terminals that use it (VS Code language servers keep `.venv\Scripts\python.exe` open), delete `.venv`, run `uv sync`, and select the new interpreter in your editor |
| `ModuleNotFoundError: google_auth_oauthlib` (or any other package) | You are not running in the project's environment: start the app with `uv run python app_enhanced.py`, or run `uv sync` first. Without that package the app starts but cannot sign in to YouTube |

Logs are in `logs/app.log`.

## Security notes

Implemented:

- **Network:** loopback-only binding, a strict `Host` allow-list (blocks DNS rebinding), and `/api/*` refuses requests the browser marks cross-site (`Sec-Fetch-Site`) or whose `Origin` is not this app, so another website cannot drive the API from your browser. Requests are capped at 1 MB.
- **Downloads:** exact host matching for video URLs (no lookalike domains, embedded credentials or ports, 2048-character limit); a fixed extractor allow-list so yt-dlp cannot fetch arbitrary URLs; size, duration and timeout limits; remote video titles never become part of a file name or a yt-dlp output template.
- **Files:** client-supplied file names are resolved strictly inside the output folders; uploads take a file name only.
- **Output:** JSON error responses with no exception text or server paths; a Content-Security-Policy and other security headers; pages that load nothing from a CDN (any future third-party asset must carry a Subresource Integrity hash); no data interpolated into HTML; control characters stripped from log messages.
- **YouTube:** OAuth with `state` and PKCE, credentials stored as JSON (never pickle) and written atomically, upload scope only.
- **Defaults:** browser cookies are opt-in, the debugger is opt-in, and a mistyped `FLASK_ENV` is an error.

Not implemented, by design for a local tool: **user accounts or login** and **CSRF tokens**. The cross-site checks above cover the browser-based attacks on `localhost`, but other users of the same machine can reach the app, and any process on the host can call it. Add authentication before sharing it. The CSP still allows inline scripts because the pages use them. Do not expose the app to a network without an authenticating proxy.

Secrets (`.env`, `client_secrets.json`, `youtube_credentials.json`, `instagram_cookies.txt`) are git-ignored; never commit them. To report a vulnerability, open a private security advisory on GitHub.

## Responsible use

This is a personal tool. Downloading a video does not give you the right to use it.

- Only process videos you **own or have permission to use**, and respect copyright, privacy and other people's likenesses.
- Platform terms restrict downloading and automated access outside their official features. See the [YouTube Terms of Service](https://www.youtube.com/t/terms), the [YouTube API Services Developer Policies](https://developers.google.com/youtube/terms/developer-policies) (which prohibit downloading or caching YouTube content through the API), the [TikTok Terms of Service](https://www.tiktok.com/legal/page/row/terms-of-service/en) and Meta's [Automated Data Collection Terms](https://www.facebook.com/apps/site_scraping_tos_terms.php). Breaking them can get your accounts restricted, and you are responsible for how you use this tool.
- The app does not and must not be used to bypass DRM, paywalls, age or region restrictions, or access controls.
- Prefer official routes where they exist: download your own videos from YouTube Studio, use the platforms' APIs or embeds, or work from files you already have.
- Do not republish other people's content without a licence or their permission; the app adds no attribution for you.
- "Suggest moments" reads a YouTube video's public "Most replayed" data and captions to rank moments. It picks *where* to cut; it does not change who owns the video or what you may do with it.
- A subtitled copy ("Vietsub") is still the original creator's video: translating it does not give you the right to publish it. The translation is made by a machine and can be wrong; check it before you share it.

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

[yt-dlp](https://github.com/yt-dlp/yt-dlp), [OpenCV](https://opencv.org/), [MoviePy](https://zulko.github.io/moviepy/), [Flask](https://flask.palletsprojects.com/), [Flask-Limiter](https://flask-limiter.readthedocs.io/), the Google API client libraries, [faster-whisper](https://github.com/SYSTRAN/faster-whisper) and [CTranslate2](https://github.com/OpenNMT/CTranslate2), the [Argos Translate](https://github.com/argosopentech/argos-translate) packages of the [OPUS-MT](https://github.com/Helsinki-NLP/Opus-MT) translation models by Jörg Tiedemann and Santhosh Thottingal (CC BY 4.0), and the typefaces [Inter](https://rsms.me/inter/) and [Be Vietnam Pro](https://github.com/bettergui/BeVietnamPro) (SIL Open Font License, copies in `static/fonts/` and `assets/fonts/`).
