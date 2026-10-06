# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Local Flask web app (loopback-only, no login) that downloads videos (YouTube, TikTok, Instagram, Facebook, Douyin) with `yt-dlp`, extracts frames at given timestamps with OpenCV, renders 9:16 short clips with MoviePy, and can upload them to the user's own YouTube channel. Windows/PowerShell is the primary dev environment; dependencies are managed with uv (`pyproject.toml` + `uv.lock`, environment in `.venv`). `README.md` is the single user-facing document.

## Commands

```powershell
uv sync                                                 # create/update .venv from uv.lock (never use pip install)
uv add <pkg> / uv remove <pkg>                          # change dependencies; commit pyproject.toml + uv.lock
uv lock --upgrade-package yt-dlp                        # upgrade one package (then update its pin in pyproject.toml)

uv run python app_enhanced.py                           # http://localhost:5000
uv run python -m unittest discover -s tests -t .        # offline suite (~8 s)
uv run python -m unittest tests.test_validators.TestTimestamps   # one class (or add .test_name)
uv run python scripts/smoke_test.py [--create-short]    # manual: needs a running server and the network
uv run --frozen --no-dev python deploy.py               # Linux production helper (gunicorn: 1 worker + threads)
```

## Architecture

`app_enhanced.py` is the only app (`create_app()` factory); the old monolithic `app.py` was removed. Modules, each with a module-level singleton created at import time where noted:

- `config.py`: `Config` classes selected by `FLASK_ENV` through `get_config()` (unknown values raise). Everything is an env var; defaults are loopback, no debugger, random dev `SECRET_KEY`. Creates the working directories.
- `validators.py`: `validator` (`SecurityValidator`): URL/timestamp/filename validation with exact host matching, and `resolve_in_folder()` for any client-supplied file name.
- `video_processor.py`: `extractor`: yt-dlp download with limits and an extractor allow-list (no generic extractor), OpenCV frame extraction, cleanup. `link_resolver.py` resolves `fb.watch` links safely (only that host is fetched, redirects re-validated).
- `short_video.py`: request parsing (start time, duration, quality, overlay) and the MoviePy render. Renders go to `generated_shorts/.rendering/` and are moved in when complete, so the library never lists a partial file; `on_progress` reports frames (video pass only: MoviePy's audio writer leaks FFmpeg when interrupted).
- `jobs.py`: `JobRegistry` (in memory, thread pool of `MAX_CONCURRENT_JOBS`) runs the slow work in the background; work gets a `JobReporter` (`stage`, `progress`, which raises `JobCancelled` once the user cancels) and raises `JobFailed(message)` for showable errors. Anything that catches `Exception` on that path must re-raise `JobCancelled`.
- `media_jobs.py`: request parsing and the download -> extract / download -> render work, shared by `/api/extract`, `/api/create-short` (synchronous, `NullReporter`) and the `/api/jobs/*` routes the pages use. `app_enhanced.job_registry` is the per-process registry (`deploy.py` runs one worker).
- `clip_finder.py`: "Suggest moments" for YouTube links: reads the "Most replayed" heatmap and a json3 caption track through yt-dlp (no download; captions only from YouTube hosts, never machine translations), scores windows, snaps them to caption lines. `POST /api/clip-suggestions`.
- `library.py`: lists the shorts in `generated_shorts/` for `GET /api/shorts`, each with a poster (`generated_shorts/.posters/<stem>.jpg`, made after a render and by `sync_posters` at startup; `GET /shorts/posters/<file>` only serves existing ones). Tests that call `create_app()` must patch `run_startup_cleanup`, or they sweep the real folders. The Create short page is rebuilt from it on every visit, so never keep a result only in the DOM. Frames cannot be grouped by extraction on the server, so the home page remembers the last one in `localStorage`.
- `static/`: `css/app.css` (tokens at the top: colours, `--space-*`, type scale; then shared components such as `.card`/`.card-flush`, `.clamp`, `.empty-state`, `.inline-loading`, forms, notices, overlay, dialog), `css/shell.css` (sidebar, top bar, mobile drawer), `js/shell.js` (collapsible sidebar, mobile drawer), `js/ui.js` (`window.ui`: DOM helpers, `postJson`, busy overlay, form errors, timecode parsing, `attachLinkCheck`) and `js/link-preview.js` (the pasted-link preview, built with `textContent` only). Each page's own code is in `css/pages/<page>.css` and `js/pages/<page>.js`. The Inter font is self-hosted in `static/fonts/` because the CSP allows fonts from this origin only.
- Pages share the app shell (dark sidebar + top bar) through `templates/partials/` (`icons`, `sidebar`, `topbar`), included after each page sets `active_page` and `page_title`. There is no base template and no inheritance: `tests/test_templates.py` lists the five page files and checks that each includes the partials. `/` is the Home launcher, the frame extractor is `/extract`.
- `trending.py`: YouTube Data API trending (API key sent in a header, never logged).
- `youtube_uploader.py`: `youtube_uploader`: OAuth (state checked, JSON credentials, lazy `google_auth_oauthlib` import) and uploads.
- `database.py`: `db_manager`: SQLite `app_data.db`; extractions and shorts (direct or as jobs) write to it, the dashboard reads it. Request status is `completed`, `failed` or `cancelled`.
- `logger.py`: `app_logger`, `api_logger`, `video_logger`, `LogContext`.

`templates/` holds the five Jinja pages (`index`, `extract`, `create_short`, `trending`, `dashboard`).

## Rules that matter here

- Never accept a file path from a client. Use `resolve_in_folder(folder, name, extensions)`; uploads take the name of a short in `generated_shorts/`.
- Error responses use `json_error()`; never return `str(e)` or paths to the browser. Log details server-side.
- In templates build DOM with `textContent`/`addEventListener`; never interpolate data into `innerHTML` or inline handlers. `tests/test_templates.py` enforces this and that script ids exist in the page.
- The CSP has no `'unsafe-inline'`: no `<style>`, inline `<script>`, `style="..."` or `on...=` attributes in templates (set sizes from JS, e.g. `data-width`). Colours are tokens in `app.css`'s `:root`; page files use `var(--...)`. Use the shared helpers in `ui.js` and components in `app.css` instead of copying them into a page; the tests check all of this, and that every CSS/JS file stays under 800 lines.
- Adding a platform needs: host in `PLATFORM_HOSTS` and a path pattern in `validators.py`, its yt-dlp extractor name in `YTDLP_ALLOWED_EXTRACTORS`, and a `PlatformProcessor`.
- Changing an env var or route? Update the `README.md` tables: `tests/test_docs.py` fails when they drift from `config.py` and the URL map.
- `/api/*` rejects cross-site browser requests (`Sec-Fetch-Site`, `Origin`) and every request needs an allowed `Host`; new API routes get this for free, new GET routes with side effects should not exist.
- Never put remote text (titles) into a yt-dlp output template: yt-dlp expands `$VAR` and `%(field)s`. Files are named by a random id (`download_with_ytdlp`).
- Pin third-party assets with Subresource Integrity (`tests/test_templates.py` checks); compute hashes from the exact URL.
- Flask-Limiter holds only a weak reference to its `Limiter`; `create_app()` keeps a strong one in `app.extensions['rate_limiter']` (needed when `RATE_LIMIT_ENABLED=false`).
- Tests are offline. Renders use a synthetic video; ImageMagick is optional (the overlay is skipped without it); DB tests use a temp file.
- Download failures are usually fixed by upgrading `yt-dlp` (pinned in `pyproject.toml`, currently 2026.8.19; 2025.8.11 can no longer read YouTube). Exception: TikTok's "Unexpected response from webpage request" is not a version problem (the nightly fails too). TikTok serves a bot-check page to plain Python clients, so the pin carries the `curl-cffi` extra, which makes yt-dlp impersonate a browser automatically. If that error returns, first check `uv run python -c "import curl_cffi"`. Formats are selected as `bv*+ba/b`, merged to mp4 with the FFmpeg bundled by MoviePy: modern sites have no single "best" file.

## Notes

- Secrets/config live in `.env` (`SECRET_KEY`, `YOUTUBE_API_KEY`, ...), `client_secrets.json`, `youtube_credentials.json` and `instagram_cookies.txt`; all are git-ignored. Never print or commit them.
- Platform terms restrict downloading; keep the README's "Responsible use" section accurate when behaviour changes.
