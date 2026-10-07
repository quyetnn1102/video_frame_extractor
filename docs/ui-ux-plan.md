# UI/UX fix plan

Response to `Review UI UX VideoExtract.md`. Every claim in the review was checked against the current code (master `d28c312`) and the running app (desktop 1440 px, phone 390 px, Lighthouse).

## 1. What the review got right, and what has changed since

The review was written from screenshots. Several of its P0 items are already done; a few of its suggestions would be wrong for this app.

| Review claim | Status now | Note |
|---|---|---|
| No job status after Create short / Extract | **Done** | Progress card with step, percentage, elapsed time and Cancel, which picks up again after a reload. Missing: **Retry**. |
| Delete has no confirmation | **Done** | A modal names the short, focus starts on "Keep it". The Delete button on the card is still a quiet text link. |
| No bulk frame download | **Done** | "Download all (.zip)". |
| No metadata after a link is pasted | **Partly done** | A preview (thumbnail, title, channel, duration) loads by itself. But "Check link" is a separate URL-pattern check that can say "This link works" for a private video, and **the duration is never used** to validate start time, length or timecodes. |
| Accessibility 6.5/10 | **Mostly done** | Lighthouse accessibility is 100 on Create short and Trending. Every text colour passes 4.5:1. Left: input focus looks the same as hover, disabled buttons give no reason, Trending card buttons are 35 px on touch screens, `<video>` has no name, Trending card titles use the wrong heading level. |
| Trending thumbnails use `contain` | **Fixed in CSS** (`cover`) | The bars come from YouTube's own image. The lead card upscales a 320 px image, so it looks soft. |
| Quality should show "Low — 720 × 1280" | **Would be wrong** | Quality changes only the bitrate (1/2/5 Mbit/s), never the resolution. Show the bitrate and an estimated size instead. |
| Real video player for preview, crop and frame capture | **Needs care** | The video is downloaded only when the job runs, so there is no player before then. A YouTube embed would need CSP and privacy changes. The plan uses the **thumbnail** as the canvas to position the crop, and keeps capture-from-player out of scope. |
| Dark mode, multi-select, subject tracking | Not now | The review itself ranks these as P2. |

Still true and worth fixing: everything about **validating against the source duration**, Your shorts card overload, YouTube upload offered when it cannot work, Trending's lead card and its refresh model, terminology, and the ImageMagick note inside the main form.

## 2. Defects the review missed (found in code and testing)

Correctness:
1. A start time plus length that runs past the end makes a **silently shorter** short, with no warning (`short_video.py`).
2. A start time past the end is rejected only **after the full download** (`short_video.py`, `media_jobs.py`).
3. The library returns **at most 24 shorts** and the counter counts the cards shown, so older shorts become invisible but still use disk (`library.py` `DEFAULT_LIMIT`).
4. `/api/shorts` opens every MP4 with OpenCV on every load or delete (`library.py`). That is fine at 24, slow at 200.
5. On Home, if loading shorts fails, the page shows "No shorts yet" (`home.js`).
6. The Trending server turns quota errors, bad keys **and empty results** into demo data, so the page cannot tell the user what happened (`trending.py`).
7. Trending Refresh is only `aria-disabled`, so clicking it during a load queues another API call that costs quota.
8. Delete stays enabled while that short is being subtitled or uploaded, which gives a 409 error on Windows.
9. YouTube upload is offered for shorts over 60 s or horizontal ones, and for setups without `client_secrets.json`; each fails only after the dialog and sign-in.

Clarity:

10. The "Vietsub" suffix is hidden by the 2-line title clamp, so a subtitled copy looks the same as its original. This is visible on the live page.
11. Duration shows as "161.8 s" in the library but "2:42" on Home.
12. "Suggest moments" stays clickable for non-YouTube links and only errors on the server.
13. Extract's hint says "m:ss or h:mm:ss", but plain seconds also work; Create short's hint says "1:30 or 90".
14. Duplicate timecodes produce duplicate frames.
15. Extract warnings repeat themselves ("Timestamp 125s: Could not extract frame at timestamp 125s").
16. Trending offers 6 of the 15 categories the server supports, uses h2 for card titles under an h2, puts a double ellipsis on descriptions, and its intro says "pull frames" although every card also offers Create short.
17. "Your shorts" in the sidebar is never highlighted as the current page.

## 3. Principles for the fixes

- **Fail before the download.** Anything the source's metadata can answer (duration, platform support) is checked in the browser, and again on the server, before a job starts.
- **One primary action per area.** Secondary actions use outline buttons; rare ones go in a "More" menu; destructive ones are last and red.
- **Say what it does.** "Analyze video", "Custom length", "Add Vietnamese subtitles", "Create 30-second short".
- **No dead ends.** An action that cannot work right now (upload without credentials, captions without ImageMagick) is hidden or explains why. It is not a disabled control with README instructions.
- **Keep the design language.** Tokens, cards, the shell and the job card stay. This is a refinement, not a redesign.

## 4. Phases

Each phase is one pull request, with tests (offline suite, `tests/test_templates.py` rules) and a browser check at 390, 768 and 1440 px. Each one should take a day or two.

### Phase 1 — Correctness and trust (small fixes, highest value)
Fixes defects 1–9 and 15.
- **Start and length past the end:**
  - the server rejects a start beyond the end before rendering;
  - a clip that would run past the end is shortened **with a warning** in the result ("Shortened to 42 s: the video ends there").
- **Library limit:** `GET /api/shorts?offset=&limit=` returns `total`; the page shows "Show more" and the real count. Durations are cached in the poster folder (one small `.json` per short, made with the poster) so listing does not open every MP4.
- **Home:** a failed load shows an error with Retry, not the empty state.
- **Trending errors:** `trending.py` returns explicit reasons (`no_key`, `quota`, `unavailable`, `empty`) next to any demo data. The page shows a specific message for each; the real empty state ("No videos in this category") becomes reachable.
- **Trending Refresh:** truly disabled while loading, and the submit handler ignores it.
- **Busy shorts:**
  - Delete and Subtitles are disabled on a short that a job is using, with the reason in the tooltip and label;
  - the server returns 409 with a clear message.
- **YouTube upload:**
  - `/api/youtube-auth` also reports `configured` (whether `client_secrets.json` exists);
  - the card shows **Upload to YouTube** only when configured, otherwise **Set up YouTube upload**, which links to the README section;
  - shorts over 60 s or not 9:16 are flagged in the upload dialog before sign-in.
- **Extract warnings:** one clear line per failed timecode ("1:25 is past the end of the video").

### Phase 2 — One "Analyze video" step shared by Home, Create short and Extract
Replaces the two separate mechanisms (the "Check link" pattern check and the automatic preview) with one component.
- `ui.attachVideoSource(input, panel)` in `static/js/video-source.js`:
  - **States:** idle → checking → ready / error.
  - **Analyze video:** the button, plus an automatic run after a paste or typing pause.
  - **Ready:** shows the preview card with thumbnail, title, channel, duration, **resolution** and a platform label in proper case.
  - **Error:** shows the platform-specific guidance (private, region, cookies needed) with Retry.
  - **Output:** emits `source-ready` with `{url, platform, duration, width, height}`.
- `/api/video-info` adds `width`, `height` and `is_vertical` (yt-dlp already has them). `/api/validate-url`, which no page uses, is removed or merged into it.
- **Home:**
  - "Create short" and "Extract frames" enable on **ready**, not on "looks like a URL";
  - Enter on an invalid link shows the error;
  - the h1 or intro becomes "Turn videos into short clips and frames".
- **Create short:**
  - start time and length are checked against the duration as you type ("Ends at 2:15 of 3:33");
  - lengths longer than the video are disabled with a reason;
  - **Suggest moments** is enabled only for YouTube sources that are ready.
- **Extract:** each timecode is checked against the duration.
- **Terminology:** "Check link" becomes **Analyze video**, "Other" becomes **Custom length**, and the submit button becomes **Create 30-second short** or **Extract 3 frames**.

### Phase 3 — Your shorts library
- **Card layout:**
  - 9:16 poster with a play overlay (no native controls until played, so subtitles are not covered);
  - title up to 2 lines plus a full-title tooltip, so "Vietsub" and every other title stays reachable;
  - one meta line `1:00 · 37 MB · 6 h ago` (the same m:ss format as Home).
- **Badges** from facts the server already knows:
  - **Vietsub** for subtitled copies (from the file name);
  - **Processing** while a job uses the short;
  - **Uploaded** once an upload has succeeded, recorded in `app_data.db`, with the video link.
- **Actions:**
  - primary **Download**;
  - a **More** menu (an accessible `<button aria-haspopup="menu">` with keyboard support) holding Add Vietnamese subtitles (hidden on Vietsub copies), Upload to YouTube or Set up YouTube upload, Copy file name, then **Delete** last in danger colour, which keeps the existing confirmation dialog.
- **Toolbar:** search by title, sort (Newest, Oldest, Longest, Largest), a "Vietsub only" filter and the real count. These run in the browser over the paged list, with search sent to the server once paging exists.
- **Card body:** a flex column, so action rows line up across a row.
- **Sidebar:** "Your shorts" is highlighted when the library is in view. Optionally it becomes its own page (`/shorts`), which also makes the Create short page shorter. That is a product decision, so it is listed under Decisions below.

### Phase 4 — Trending
- **Grid:** uniform cards (no 2-column lead), 3 columns at ≥ 1280 px. Title 2 lines, description 2 lines (no server-side "..."). One meta line: views · duration · age · category.
- **Actions:**
  - **Create short** (primary), **Extract frames** (secondary), and a More menu with Watch on YouTube and Copy link;
  - buttons stay 44 px on touch screens.
- **Filters:** they update automatically, the Refresh button becomes a small "Reload" next to "Updated 21:42 (your time)", and the helper text matches. All 15 categories are offered.
- **Copy and headings:** the intro says "Discover popular YouTube videos and turn them into clips or frames.", and card titles become h3.
- **Top bar:** the "New short" button is removed on Home (the launcher is right there) and on Trending (every card has one). The cross-link is kept on Create short and Extract.

### Phase 5 — Create short and Extract refinements
- **Crop position (Create short):**
  - after Analyze, the static diagram becomes the video's thumbnail with a draggable or arrow-key 9:16 window;
  - the position is sent as `crop_x` (0–1) and applied by `compute_vertical_crop`;
  - it is shown only for wide sources, since vertical sources need no crop.
- **Quality (Create short):** "Low — 1 Mbit/s, about 8 MB per minute" and so on, computed from the bitrates.
- **ImageMagick note:** the Caption field is hidden when ImageMagick is missing. The note moves to a **Setup** card on the Dashboard, which also reports Node.js/Deno for YouTube, YouTube upload credentials, Douyin cookies and the subtitle models.
- **YouTube note:** the aside card becomes part of the result (Phase 3 handles upload), so the aside holds only the crop.
- **Timecodes (Extract):**
  - live per-line validation with a summary ("3 valid · 1 invalid") and "Line 4: 12:75 is not a timecode";
  - **Sort and remove duplicates**;
  - one hint for every page: "90, 1:30 or 1:02:03".
- **Extract layout:** the submit button spans the form; the example frames become an empty state ("Frames appear here") so they cannot look like output.
- **Format option (Extract):** **JPG / PNG**, with a server parameter and the archive kept as it is.
- **Retry:** a failed job's notice gets **Retry** with the same settings (job-progress shared).

### Phase 6 — Accessibility and responsive polish
- Inputs and selects get a distinct `:focus-visible` (2 px focus colour plus ring), not the hover border.
- Disabled actions use `aria-disabled` with a visible reason, so they stay focusable and explain why.
- `<video>` elements get accessible names, and `btn-danger` gets a hover state.
- **Responsive pass at 375, 768, 1024, 1440 and 1920 px:**
  - library at 2 columns on phones;
  - the crop panel below the form on tablets;
  - the "Your shorts" link scrolls to the list after it loads.
- **Checks:** keyboard-only run through each flow, axe and Lighthouse, long Chinese and Vietnamese titles, and a 3-hour source.

## 5. Out of scope for now
Dark mode; multi-select and bulk actions; capture-from-player for frames (needs a downloaded or embedded player); subject tracking; saved presets; editing subtitles (`.srt` export could follow the subtitle feature separately).

## 6. Decisions (agreed with the owner)
1. **Name:** the product is called **Tallframe**, with the headline "Turn videos into short clips and frames". It covers both jobs: 9:16 "tall frames" and frame extraction. The rename covers what users see (brand, page titles, README); the repository and folders keep their names. It is done in Phase 1.
2. **Library:** Your shorts gets its own page, `/shorts` (Phase 3). Create short then ends with the form and the job card.
3. **Trending:** the 2-column lead card is removed (Phase 4).

## 7. Order and size

| Phase | Size | Depends on |
|---|---|---|
| 1 Correctness and trust | M | — |
| 2 Analyze video | M–L | — |
| 3 Library | L | 1 (paging, upload state) |
| 4 Trending | S–M | 1 (error reasons) |
| 5 Create/Extract refinements | M | 2 (duration, size) |
| 6 Accessibility/responsive | S–M | after 3–5 |

Recommended order: 1 → 2 → 3 → 4 → 5 → 6. Phases 1 and 2 remove the "fails after the download" problems, which are the main trust issue. Phase 3 is the most visible change.
