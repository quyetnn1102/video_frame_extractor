(function () {
    'use strict';

    const STORAGE_KEY = 'videoextract.lastExtraction';
    const SHOWN_JOB_KEY = 'videoextract.shownExtractJob';  // the last job whose frames were shown
    const SAFE_FILE_NAME = /^[\w.-]+$/;
    const MAX_GHOST_FRAMES = 12;
    const MAX_TIMECODES = 50;  // MAX_TIMESTAMPS in validators.py
    const ARCHIVE_URL_LIFETIME_MS = 60000;  // the zip's object URL is released after the download starts
    const SAMPLE_TIMECODES = ['0:05', '0:30', '1:15'];
    const $ = (id) => document.getElementById(id);
    let hasResults = false;   // real frames replace the preview until the next extraction
    let shownFrames = [];     // the frames on screen, for "Download all"
    let busy = false;

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

    function renderPreview() {
        if (hasResults) return;
        const typed = timecodesFromInput();
        const isSample = typed.length === 0;
        const codes = (isSample ? SAMPLE_TIMECODES : typed).slice(0, MAX_GHOST_FRAMES);
        const note = isSample ? 'Example' : 'Preview';
        $('framesContainer').replaceChildren(...codes.map((code, index) => frameItem(code, { note, index })));
        // Placeholders only: screen readers get the summary line instead of fake results
        $('framesContainer').setAttribute('aria-hidden', 'true');

        let summary = 'One frame for each timecode appears here.';
        if (!isSample) {
            summary = typed.length === 1 ? '1 frame to extract.' : typed.length + ' frames to extract.';
            if (typed.length > MAX_GHOST_FRAMES) summary += ' Showing the first ' + MAX_GHOST_FRAMES + '.';
        }
        $('stripSummary').textContent = summary;
    }

    // The server reports whole seconds; show them the way they are typed (m:ss or h:mm:ss)
    function formatTimecode(value) {
        const total = Number(value);
        if (!Number.isInteger(total) || total < 0) return String(value);
        const hours = Math.floor(total / 3600);
        const minutes = Math.floor((total % 3600) / 60);
        const seconds = String(total % 60).padStart(2, '0');
        return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${seconds}` : `${minutes}:${seconds}`;
    }

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

    $('timestamps').addEventListener('input', renderPreview);

    // ---- check the link ---------------------------------------------------

    ui.attachLinkCheck($('validateBtn'), $('videoUrl'), $('linkStatus'));

    // ---- check the form before anything is downloaded ----------------------

    function linkError() {
        const url = $('videoUrl').value.trim();
        if (!url) return 'Enter a video link';
        if (!ui.isLink(url)) return 'Enter a full link, starting with https://';
        return null;
    }

    function timecodesError() {
        const codes = timecodesFromInput();
        if (codes.length === 0) return 'Enter at least one timecode';
        if (codes.length > MAX_TIMECODES) return `Enter ${MAX_TIMECODES} timecodes or fewer`;
        const wrong = codes.find((code) => ui.parseTimecode(code) === null);
        if (wrong) return `"${wrong}" is not a timecode. Use m:ss or h:mm:ss, for example 1:05`;
        return null;
    }

    const checks = [[$('videoUrl'), linkError], [$('timestamps'), timecodesError]];
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
        ['formStatus', 'linkStatus', 'linkPreview', 'archiveStatus', 'extractWarnings']
            .forEach((id) => $(id).replaceChildren());
        shownFrames = [];
        hasResults = false;
        $('resultActions').hidden = true;
        renderPreview();
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
        submit.textContent = isWorking ? 'Extracting...' : 'Extract frames';
        $('resultActions').hidden = isWorking || !hasResults;
        if (isWorking) submit.setAttribute('aria-disabled', 'true');
        else submit.removeAttribute('aria-disabled');
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
        status.replaceChildren(job.state === 'cancelled'
            ? notice('info', 'Cancelled.', 'Nothing was extracted.')
            : notice('error', 'Extraction failed.', job.error || 'Try again in a moment.'));
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
        const url = $('videoUrl').value.trim();

        setWorking(true);
        try {
            followJob(await jobs.start('/api/jobs/extract', { url, timestamps: timecodesFromInput() }));
        } catch (error) {
            setWorking(false);
            status.replaceChildren(notice('error', 'Could not start.', error.message));
        }
    });

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
    window.attachLinkPreview($('videoUrl'), $('linkPreview'));

    if (saved && !prefill) {
        displayResults(saved.frames, Array.isArray(saved.warnings) ? saved.warnings.map(String) : [], { restored: true });
    } else {
        renderPreview();
    }
    resumeLatestJob();
})();
