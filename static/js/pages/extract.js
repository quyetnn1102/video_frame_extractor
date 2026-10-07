(function () {
    'use strict';

    const STORAGE_KEY = 'videoextract.lastExtraction';
    const SHOWN_JOB_KEY = 'videoextract.shownExtractJob';  // the last job whose frames were shown
    const SAFE_FILE_NAME = /^[\w.-]+$/;
    const MAX_GHOST_FRAMES = 12;
    const MAX_TIMECODES = 50;  // MAX_TIMESTAMPS in validators.py
    const ARCHIVE_URL_LIFETIME_MS = 60000;  // the zip's object URL is released after the download starts
    const $ = (id) => document.getElementById(id);
    let hasResults = false;   // real frames replace the preview until the next extraction
    let shownFrames = [];     // the frames on screen, for "Download all"
    let busy = false;
    let source = null;        // the analyzed video link (video-source.js), set at the end

    // Server text (platform names, warnings, file names) is untrusted for display:
    // everything below is built with textContent / addEventListener, never HTML strings.
    const { element, notice, scrollBehavior } = ui;

    // ---- the film strip ---------------------------------------------------

    function frameItem(timecode, options) {
        const item = element('li', 'frame');
        const picture = element('div', 'frame-pic');
        const meta = element('div', 'frame-meta');
        meta.append(element('span', 'time frame-code', timecode));

        if (options.imageUrl) {
            const image = element('img');
            image.src = options.imageUrl;
            image.alt = 'Frame at ' + timecode;
            image.loading = 'lazy';
            // Old files are removed after a while; say so instead of showing a broken image
            image.addEventListener('error', () => {
                picture.replaceChildren(element('p', 'frame-gone', 'This frame is no longer on disk.'));
                meta.querySelector('a')?.remove();
            });
            picture.append(image);

            const save = element('a', undefined, 'Download');
            save.href = options.imageUrl;
            save.download = '';
            save.setAttribute('aria-label', 'Download frame at ' + timecode);
            meta.append(save);
            item.classList.add('is-new');
            item.style.setProperty('--i', String(options.index));
        } else {
            item.classList.add('is-ghost');
            meta.append(element('span', 'frame-note', options.note));
        }
        item.append(picture, meta);
        return item;
    }

    function timecodesFromInput() {
        return $('timestamps').value.split('\n').map((line) => line.trim()).filter(Boolean);
    }

    // Every typed line, checked on its own: { line, code, seconds } with seconds null when unreadable
    function checkedLines() {
        return $('timestamps').value.split('\n')
            .map((text, index) => ({ line: index + 1, code: text.trim() }))
            .filter((entry) => entry.code)
            .map((entry) => ({ ...entry, seconds: ui.parseTimecode(entry.code) }));
    }

    // "3 valid · 1 invalid · 1 past the end", under the field while typing
    function updateTimecodeSummary() {
        const lines = checkedLines();
        const total = sourceDuration();
        const invalid = lines.filter((entry) => entry.seconds === null).length;
        const late = total === null ? 0 : lines.filter((entry) => entry.seconds !== null && entry.seconds >= total).length;
        const parts = lines.length ? [`${lines.length - invalid - late} valid`] : [];
        if (invalid) parts.push(`${invalid} invalid`);
        if (late) parts.push(`${late} past the end`);
        $('timecodeSummary').textContent = parts.join(' \u00b7 ');
    }

    // Sorted, each moment once, written the same way; unreadable lines stay at the end to be fixed
    $('sortTimecodesBtn').addEventListener('click', () => {
        const lines = checkedLines();
        const seconds = [...new Set(lines.filter((entry) => entry.seconds !== null).map((entry) => entry.seconds))]
            .sort((a, b) => a - b);
        const unreadable = lines.filter((entry) => entry.seconds === null).map((entry) => entry.code);
        $('timestamps').value = [...seconds.map(ui.formatClock), ...unreadable].join('\n');
        $('timestamps').dispatchEvent(new Event('input'));
    });

    function renderPreview() {
        if (hasResults) return;
        const typed = timecodesFromInput();
        // Placeholders only: screen readers get the summary line instead of fake results
        $('framesContainer').setAttribute('aria-hidden', 'true');
        if (typed.length === 0) {
            // No example frames: they looked like results. Just where the frames will go.
            $('framesContainer').replaceChildren(element('li', 'strip-empty',
                'Extracted frames appear here, one for each timecode.'));
            $('stripSummary').textContent = '';
            return;
        }
        const codes = typed.slice(0, MAX_GHOST_FRAMES);
        $('framesContainer').replaceChildren(...codes.map((code, index) => frameItem(code, { note: 'Not extracted yet', index })));
        let summary = typed.length === 1 ? '1 frame to extract.' : typed.length + ' frames to extract.';
        if (typed.length > MAX_GHOST_FRAMES) summary += ' Showing the first ' + MAX_GHOST_FRAMES + '.';
        $('stripSummary').textContent = summary;
    }

    // The server reports whole seconds; show them the way they are typed (m:ss or h:mm:ss)
    const formatTimecode = (value) => ui.formatClock(value) || String(value);

    function displayResults(frames, warnings, options) {
        const restored = Boolean(options && options.restored);
        // Timestamps that could not be extracted (for example past the end of the video)
        $('extractWarnings').replaceChildren(...warnings.map((warning) => notice('warn', 'Skipped.', warning)));

        const items = frames.map((frame, index) => frameItem(formatTimecode(frame.timestamp), {
            imageUrl: '/frames/' + encodeURIComponent(frame.filename),
            index,
        }));
        $('framesContainer').replaceChildren(...items);
        $('framesContainer').removeAttribute('aria-hidden');
        hasResults = true;
        shownFrames = frames;
        $('resultActions').hidden = frames.length === 0;
        $('archiveStatus').replaceChildren();
        const count = frames.length === 1 ? '1 frame' : frames.length + ' frames';
        $('stripSummary').textContent = restored ? count + ' from your last extraction.' : count + ' extracted.';
        if (!restored) $('resultsSection').scrollIntoView({ behavior: scrollBehavior() });
    }

    // ---- remember the last extraction, so leaving or refreshing the page keeps it ----

    function saveExtraction(url, frames, warnings) {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify({ url, frames, warnings }));
        } catch (error) {
            // storage can be full or blocked; the frames are still on screen and on disk
        }
    }

    function savedExtraction() {
        try {
            const saved = JSON.parse(localStorage.getItem(STORAGE_KEY));
            const valid = saved && Array.isArray(saved.frames) && saved.frames.length > 0
                && saved.frames.every((frame) => frame && SAFE_FILE_NAME.test(String(frame.filename))
                                                 && frame.timestamp !== undefined);
            return valid ? saved : null;
        } catch (error) {
            return null;
        }
    }

    $('timestamps').addEventListener('input', () => {
        renderPreview();
        updateSubmitLabel();
        updateTimecodeSummary();
    });

    // ---- the video: analyzed once its link is pasted (video-source.js) ------------

    function sourceDuration() {
        const state = source ? source.state() : null;
        const seconds = state && state.status === 'ready' ? Number(state.video.duration) : NaN;
        return seconds > 0 ? seconds : null;
    }

    // "Extract 3 frames": the button says how many it will make
    function updateSubmitLabel() {
        if (busy) return;
        const count = timecodesFromInput().filter((code) => ui.parseTimecode(code) !== null).length;
        $('extractSubmit').textContent = count === 1 ? 'Extract 1 frame'
            : count > 1 ? `Extract ${Math.min(count, MAX_TIMECODES)} frames` : 'Extract frames';
    }

    // ---- check the form before anything is downloaded ----------------------

    function linkError() {
        const url = $('videoUrl').value.trim();
        if (!url) return 'Enter a video link';
        if (!ui.isLink(url)) return 'Enter a full link, starting with https://';
        if (source && source.state().status === 'invalid') {
            return 'This link cannot be used: ' + (source.state().message || 'see above');
        }
        return null;
    }

    function timecodesError() {
        const lines = checkedLines();
        if (lines.length === 0) return 'Enter at least one timecode';
        if (lines.length > MAX_TIMECODES) return `Enter ${MAX_TIMECODES} timecodes or fewer`;
        const wrong = lines.find((entry) => entry.seconds === null);
        if (wrong) return `Line ${wrong.line}: "${wrong.code}" is not a timecode. Use 90, 1:30 or 1:02:03`;
        // Known once the link is analyzed: a timecode past the end would give no frame
        const total = sourceDuration();
        const late = total === null ? undefined : lines.find((entry) => entry.seconds >= total);
        if (late) return `Line ${late.line}: ${late.code} is past the end of the video (${ui.formatClock(total)})`;
        return null;
    }

    const checks = [[$('videoUrl'), linkError], [$('timestamps'), timecodesError]];

    // An error shown for the previous link, or checked against its length, may no longer apply
    function recheckShownErrors() {
        checks.forEach(([input, check]) => {
            if (input.getAttribute('aria-invalid') !== 'true') return;
            const message = check();
            if (message) ui.setFieldError(input, message);
            else ui.clearFieldError(input);
        });
    }
    checks.forEach(([input, check]) => ui.revalidateOnInput(input, check));

    function formIsValid() {
        const errors = checks
            .map(([input, check]) => ({ input, message: check() }))
            .filter((error) => error.message);
        ui.clearErrors($('errorSummary'), checks.map(([input]) => input));
        if (errors.length) ui.showErrors($('errorSummary'), errors);
        return errors.length === 0;
    }

    // ---- the frames on screen: all of them as one zip, or start again ---------------

    async function downloadAll() {
        const status = $('archiveStatus');
        status.replaceChildren();
        let response;
        try {
            response = await fetch('/api/frames/archive', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ filenames: shownFrames.map((frame) => frame.filename) }),
            });
        } catch (error) {
            status.replaceChildren(notice('error', 'Could not make the zip file.', 'The app did not answer.'));
            return;
        }
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            status.replaceChildren(notice('error', 'Could not make the zip file.', data.error || 'Try again in a moment.'));
            return;
        }
        const link = element('a');
        link.href = URL.createObjectURL(await response.blob());
        link.download = 'frames.zip';
        document.body.append(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(link.href), ARCHIVE_URL_LIFETIME_MS);
        status.replaceChildren(notice('ok', 'Downloaded.', 'frames.zip has every frame shown here.'));
    }

    function startOver() {
        if (busy) return;  // an extraction is running; its frames would land in the cleared page
        try {
            localStorage.removeItem(STORAGE_KEY);
        } catch (error) {
            // storage can be blocked; the page is cleared anyway
        }
        $('extractForm').reset();
        ui.clearErrors($('errorSummary'), checks.map(([input]) => input));
        ['formStatus', 'linkPreview', 'archiveStatus', 'extractWarnings']
            .forEach((id) => $(id).replaceChildren());
        shownFrames = [];
        hasResults = false;
        $('resultActions').hidden = true;
        source.reset();  // reset() fires no input events: the link and its length are cleared here
        renderPreview();
        updateSubmitLabel();
        updateTimecodeSummary();
        $('videoUrl').focus();
    }

    $('downloadAllBtn').addEventListener('click', () => ui.whileWorking($('downloadAllBtn'), 'Preparing...', downloadAll));
    $('startOverBtn').addEventListener('click', startOver);

    // ---- extract: a background job, followed in a progress card ---------------

    function rememberShown(jobId) {
        try {
            localStorage.setItem(SHOWN_JOB_KEY, jobId);
        } catch (error) {
            // storage can be blocked; at worst the same result is shown again next time
        }
    }

    function wasShown(jobId) {
        try {
            return localStorage.getItem(SHOWN_JOB_KEY) === jobId;
        } catch (error) {
            return false;
        }
    }

    function setWorking(isWorking) {
        busy = isWorking;
        const submit = $('extractSubmit');
        submit.textContent = 'Extracting...';
        $('resultActions').hidden = isWorking || !hasResults;
        if (isWorking) submit.setAttribute('aria-disabled', 'true');
        else submit.removeAttribute('aria-disabled');
        updateSubmitLabel();
    }

    function showOutcome(job) {
        const status = $('formStatus');
        rememberShown(job.id);
        if (job.state === 'succeeded') {
            const warnings = Array.isArray(job.result.warnings) ? job.result.warnings : [];
            displayResults(job.result.frames, warnings);
            saveExtraction(job.result.url || '', job.result.frames, warnings);
            $('stripHeading').focus({ preventScroll: true });  // where the frames are
            return;
        }
        if (job.state === 'cancelled') {
            status.replaceChildren(notice('info', 'Cancelled.', 'Nothing was extracted.'));
        } else {
            status.replaceChildren(withRetry(notice('error', 'Extraction failed.', job.error || 'Try again in a moment.')));
        }
        $('extractSubmit').focus();  // the progress card, and the focus in it, is gone
    }

    function followJob(job) {
        setWorking(true);
        jobs.follow(job, $('jobPanel'), {
            title: 'Extracting frames',
            onFinish: (final) => {
                setWorking(false);
                showOutcome(final);
            },
        });
    }

    $('extractForm').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (busy) return;

        const status = $('formStatus');
        status.replaceChildren();
        if (!formIsValid()) return;
        startJob({ url: $('videoUrl').value.trim(), timestamps: timecodesFromInput(), format: $('frameFormat').value });
    });

    let lastRequest = null;   // what "Try again" sends

    async function startJob(body) {
        lastRequest = body;
        $('formStatus').replaceChildren();
        setWorking(true);
        try {
            followJob(await jobs.start('/api/jobs/extract', body));
        } catch (error) {
            setWorking(false);
            $('formStatus').replaceChildren(withRetry(notice('error', 'Could not start.', error.message)));
        }
    }

    // The same frames again, with the settings they were asked with
    function withRetry(message) {
        if (!lastRequest) return message;
        const retry = element('button', 'btn btn-sm notice-action', 'Try again');
        retry.type = 'button';
        retry.addEventListener('click', () => {
            if (!busy) startJob(lastRequest);
        });
        message.append(retry);
        return message;
    }

    // A job started before this page was (re)opened: follow it, or show what it found
    async function resumeLatestJob() {
        const job = await jobs.latest('extract');
        if (busy || !job || wasShown(job.id)) return;  // busy: a job was just started here
        if (jobs.isActive(job)) {
            followJob(job);
        } else if (job.state === 'succeeded') {
            rememberShown(job.id);
            displayResults(job.result.frames, job.result.warnings || [], { restored: true });
            saveExtraction(job.result.url || '', job.result.frames, job.result.warnings || []);
        }
    }

    // ---- prefill from ?url= (the Trending page links here) ----------------

    const prefill = new URLSearchParams(window.location.search).get('url');
    const saved = savedExtraction();
    if (prefill) {
        $('videoUrl').value = prefill;
        $('timestamps').focus();
    } else if (saved) {
        $('videoUrl').value = typeof saved.url === 'string' ? saved.url : '';
    }
    source = videoSource.attach({ input: $('videoUrl'), button: $('analyzeBtn'), panel: $('linkPreview'),
                                  onChange: () => {
                                      updateTimecodeSummary();
                                      recheckShownErrors();
                                  } });
    updateSubmitLabel();
    updateTimecodeSummary();

    if (saved && !prefill) {
        displayResults(saved.frames, Array.isArray(saved.warnings) ? saved.warnings.map(String) : [], { restored: true });
    } else {
        renderPreview();
    }
    resumeLatestJob();
})();
