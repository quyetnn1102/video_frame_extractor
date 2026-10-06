(function () {
    'use strict';

    const MAX_DURATION_SECONDS = 300;
    const $ = (id) => document.getElementById(id);
    let rendering = false;         // a short is being made (a background job)
    let source = null;             // the analyzed video link (video-source.js), set at the end

    // Server text is untrusted for display purposes: everything below is built
    // with textContent / addEventListener instead of HTML strings.
    const { element, notice, postJson } = ui;

    function safeUrl(value, allowedPrefixes) {
        return allowedPrefixes.some((prefix) => typeof value === 'string' && value.startsWith(prefix))
            ? value : '';
    }

    function safeUrl(value, allowedPrefixes) {
        return allowedPrefixes.some((prefix) => typeof value === 'string' && value.startsWith(prefix))
            ? value : '';
    }

    // ---- length presets ---------------------------------------------------

    function selectDuration(option) {
        document.querySelectorAll('.duration-option').forEach((item) => {
            item.setAttribute('aria-pressed', String(item === option));
        });
        const duration = option.dataset.duration;
        $('selectedDuration').value = duration;
        $('customDurationDiv').hidden = duration !== 'custom';
        if (duration === 'custom') $('customDuration').focus();
        else ui.clearFieldError($('customDuration'));
        updateTiming();
    }

    function getDuration() {
        const selected = $('selectedDuration').value;
        const value = selected === 'custom' ? Number($('customDuration').value) : Number(selected);
        if (!Number.isFinite(value) || value < 1 || value > MAX_DURATION_SECONDS) {
            throw new Error(`Length must be between 1 and ${MAX_DURATION_SECONDS} seconds.`);
        }
        return value;
    }

    document.querySelectorAll('.duration-option').forEach((option) => {
        // A preset longer than the video stays visible, with the reason, but cannot be chosen
        option.addEventListener('click', () => {
            if (option.getAttribute('aria-disabled') !== 'true') selectDuration(option);
        });
    });

    // ---- crop diagram -----------------------------------------------------

    // ---- crop: which part of a wide picture the 9:16 short keeps -------------------

    const CROP_STEP = 0.05;
    const CROP_PAGE_STEP = 0.25;
    let cropPosition = 0.5;   // 0 is the left edge, 1 the right (crop_position on the server)
    let croppedVideoUrl = '';

    function analyzedVideo() {
        const state = source ? source.state() : null;
        return state && state.status === 'ready' ? state.video : null;
    }

    // The share of the width a 9:16 window covers, or null when nothing is cut from the sides
    function cropShare(video) {
        const width = Number(video && video.width);
        const height = Number(video && video.height);
        if (!(width > 0 && height > 0)) return null;
        const share = (height * 9 / 16) / width;
        return share < 1 ? share : null;
    }

    function positionText() {
        const percent = Math.round(cropPosition * 100);
        const side = percent <= 33 ? 'Left' : percent >= 67 ? 'Right' : 'Center';
        return `${side} (${percent}% from the left)`;
    }

    function cropCaption(vertical, video, movable) {
        if (!vertical) return 'The whole picture is kept. Nothing is cropped.';
        if (movable) return 'Drag the outlined area, or use the arrow keys, to choose what the short keeps.';
        if (video && video.width && video.height) return 'This video is not wider than 9:16, so nothing is cut from the sides.';
        return 'The outlined area is what you keep. Analyze a link to choose which part of a wide video.';
    }

    function updateCropDiagram() {
        const vertical = $('verticalFormat').checked;
        const video = analyzedVideo();
        const share = vertical ? cropShare(video) : null;
        const movable = share !== null;
        const thumbnail = video && /^https:\/\//.test(video.thumbnail || '') ? video.thumbnail : '';

        $('cropFigure').classList.toggle('is-full', !vertical);
        $('cropFigure').classList.toggle('is-movable', movable);
        $('cropThumb').hidden = !thumbnail;
        if (thumbnail && $('cropThumb').src !== thumbnail) $('cropThumb').src = thumbnail;
        $('cropFrame').style.aspectRatio = video && video.width && video.height ? `${video.width} / ${video.height}` : '';

        const keep = $('cropKeep');
        keep.tabIndex = movable ? 0 : -1;
        if (movable) keep.removeAttribute('aria-disabled');
        else keep.setAttribute('aria-disabled', 'true');
        keep.style.width = movable ? `${share * 100}%` : '';
        keep.style.left = movable ? `${cropPosition * (1 - share) * 100}%` : '';
        keep.setAttribute('aria-valuenow', String(Math.round(cropPosition * 100)));
        keep.setAttribute('aria-valuetext', positionText());
        $('cropCaption').textContent = cropCaption(vertical, video, movable);
    }

    function moveCrop(position) {
        cropPosition = Math.min(1, Math.max(0, position));
        updateCropDiagram();
    }

    $('cropKeep').addEventListener('keydown', (event) => {
        if (!$('cropFigure').classList.contains('is-movable')) return;
        const moves = {
            ArrowLeft: cropPosition - CROP_STEP, ArrowDown: cropPosition - CROP_STEP,
            ArrowRight: cropPosition + CROP_STEP, ArrowUp: cropPosition + CROP_STEP,
            PageDown: cropPosition - CROP_PAGE_STEP, PageUp: cropPosition + CROP_PAGE_STEP, Home: 0, End: 1,
        };
        if (!(event.key in moves)) return;
        event.preventDefault();
        moveCrop(moves[event.key]);
    });

    // Dragging: the window follows the pointer, centred on it
    function cropFromPointer(event) {
        const share = cropShare(analyzedVideo());
        if (share === null) return;
        const frame = $('cropFrame').getBoundingClientRect();
        const keepWidth = share * frame.width;
        moveCrop((event.clientX - frame.left - keepWidth / 2) / (frame.width - keepWidth));
    }

    $('cropFrame').addEventListener('pointerdown', (event) => {
        if (!$('cropFigure').classList.contains('is-movable')) return;
        $('cropFrame').setPointerCapture(event.pointerId);
        cropFromPointer(event);
        $('cropKeep').focus({ preventScroll: true });
    });
    $('cropFrame').addEventListener('pointermove', (event) => {
        if ($('cropFrame').hasPointerCapture(event.pointerId)) cropFromPointer(event);
    });

    $('verticalFormat').addEventListener('change', updateCropDiagram);

    // ---- the video: analyzed once its link is pasted (video-source.js) ------------

    // Its length, once known: start, length and the presets are checked against it
    function sourceDuration() {
        const state = source ? source.state() : null;
        const seconds = state && state.status === 'ready' ? Number(state.video.duration) : NaN;
        return seconds > 0 ? seconds : null;
    }

    function startSeconds() {
        const value = $('startTime').value.trim();
        if (!value) return 0;
        const parsed = value.includes(':') ? ui.parseTimecode(value) : Number(value);
        return parsed !== null && Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
    }

    function chosenLength() {
        try {
            return getDuration();
        } catch (error) {
            return null;
        }
    }

    function updateLengthOptions(total) {
        document.querySelectorAll('.duration-option[data-note]').forEach((option) => {
            const tooLong = total !== null && Number(option.dataset.duration) > total;
            option.querySelector('small').textContent = tooLong ? 'Longer than the video' : option.dataset.note;
            if (tooLong) option.setAttribute('aria-disabled', 'true');
            else option.removeAttribute('aria-disabled');
        });
    }

    // "Ends at 2:15 of 3:33", or how much of the clip the video has room for
    function updateTiming() {
        const total = sourceDuration();
        const start = startSeconds();
        const length = chosenLength();
        updateLengthOptions(total);
        if (!rendering) $('createSubmit').textContent = length ? `Create ${Math.round(length)}-second short` : 'Create short';
        const hint = $('startHint');
        if (total === null || start === null || length === null) {
            hint.textContent = 'Leave blank to start from the beginning.';
        } else if (start >= total) {
            hint.textContent = `The video is ${ui.formatClock(total)} long: start before that.`;
        } else if (start + length > total) {
            hint.textContent = `Runs past the end of the video (${ui.formatClock(total)}): ` +
                `the short will be ${ui.formatClock(total - start)} long.`;
        } else {
            hint.textContent = `Ends at ${ui.formatClock(start + length)} of ${ui.formatClock(total)}.`;
        }
    }

    function updateSuggest(state) {
        const youtube = state.status === 'ready' && state.video.platform === 'youtube';
        if (youtube) $('suggestBtn').removeAttribute('aria-disabled');
        else $('suggestBtn').setAttribute('aria-disabled', 'true');
        $('suggestHint').textContent = state.status === 'ready' && !youtube
            ? 'Only for YouTube links: other sites do not share which parts people replay.'
            : 'For YouTube links: finds the parts people replay most, at the length above. Takes a few seconds.';
    }

    function onSourceChange(state) {
        if (state.url !== croppedVideoUrl) {  // another video: its crop starts in the center
            croppedVideoUrl = state.url;
            cropPosition = 0.5;
        }
        updateSuggest(state);
        updateTiming();
        updateCropDiagram();
    }

    $('startTime').addEventListener('input', updateTiming);
    $('customDuration').addEventListener('input', updateTiming);

    // ---- check the form before anything is downloaded ----------------------

    function linkError() {
        const url = $('shortVideoUrl').value.trim();
        if (!url) return 'Enter a video link to cut a short from';
        if (!ui.isLink(url)) return 'Enter a full link, starting with https://';
        if (source && source.state().status === 'invalid') {
            return 'This link cannot be used: ' + (source.state().message || 'see above');
        }
        return null;
    }

    function lengthError() {
        if ($('selectedDuration').value !== 'custom') return null;
        // As loose as the server (parse_duration): any number from 1 to 300, decimals too
        const value = Number($('customDuration').value.trim() || NaN);
        if (!Number.isFinite(value) || value < 1 || value > MAX_DURATION_SECONDS) {
            return `Enter a length from 1 to ${MAX_DURATION_SECONDS} seconds`;
        }
        return null;
    }

    function startTimeError() {
        const value = $('startTime').value.trim();
        // Seconds without a colon are read as a number by the server (parse_start_time)
        const asSeconds = value.includes(':') ? NaN : Number(value);
        if (value && ui.parseTimecode(value) === null && !(Number.isFinite(asSeconds) && asSeconds >= 0)) {
            return 'Enter the start as m:ss, h:mm:ss or seconds, for example 1:30 or 90';
        }
        const total = sourceDuration();
        if (total !== null && startSeconds() >= total) {
            return `Start before the end of the video (${ui.formatClock(total)})`;
        }
        return null;
    }

    const checks = [[$('shortVideoUrl'), linkError], [$('customDuration'), lengthError],
                    [$('startTime'), startTimeError]];
    checks.forEach(([input, check]) => ui.revalidateOnInput(input, check));

    function formIsValid() {
        const errors = checks
            .map(([input, check]) => ({ input, message: check() }))
            .filter((error) => error.message);
        ui.clearErrors($('errorSummary'), checks.map(([input]) => input));
        if (errors.length) ui.showErrors($('errorSummary'), errors);
        return errors.length === 0;
    }

    // ---- suggest moments: the parts of a YouTube video people replay most -------

    const PRESET_LENGTHS = [15, 30, 60];
    const LENGTH_MATCH_SECONDS = 0.5;

    const clock = (totalSeconds) => ui.formatClock(Math.floor(totalSeconds));

    // Fills in the start and length; a suggestion that ends on a line may be a little shorter
    function useSuggestion(clip) {
        $('startTime').value = clock(clip.start);
        ui.clearFieldError($('startTime'));
        const preset = PRESET_LENGTHS.find((length) => Math.abs(length - clip.duration) < LENGTH_MATCH_SECONDS);
        if (preset) {
            selectDuration(document.querySelector(`.duration-option[data-duration="${preset}"]`));
        } else {
            selectDuration(document.querySelector('.duration-option[data-duration="custom"]'));
            $('customDuration').value = String(clip.duration);
        }
        $('suggestStatus').replaceChildren(notice('ok', 'Moment chosen.',
            `Starts at ${clock(clip.start)}, ${Math.round(clip.duration)} seconds. Press Create short when ready.`));
        $('createSubmit').focus();
    }

    function suggestionItem(clip) {
        const time = element('span', 'suggestion-time',
            `${clock(clip.start)} to ${clock(clip.start + clip.duration)}`);
        const bar = element('span', 'suggestion-bar');
        bar.style.width = Math.round(Math.max(0.1, clip.score) * 100) + '%';
        bar.setAttribute('aria-hidden', 'true');  // the reason says the same in words
        const head = element('div');
        head.append(time, bar);

        const use = element('button', 'btn btn-sm', 'Use this');
        use.type = 'button';
        use.setAttribute('aria-label', `Use the moment from ${clock(clip.start)}`);
        use.addEventListener('click', () => useSuggestion(clip));

        const item = element('li', 'suggestion');
        item.append(head, use, element('p', 'suggestion-reason', clip.reason));
        if (clip.excerpt) item.append(element('p', 'suggestion-excerpt clamp', `"${clip.excerpt}"`));
        return item;
    }

    async function suggestMoments() {
        const status = $('suggestStatus');
        const url = source.state().url;
        $('suggestions').replaceChildren();
        let duration;
        try {
            duration = getDuration();
        } catch (error) {
            status.replaceChildren(notice('error', 'Check the length.', error.message));
            return;
        }
        const scanner = element('span', 'mark is-scanning');
        scanner.setAttribute('aria-hidden', 'true');
        const loading = element('p', 'inline-loading');
        loading.append(scanner, document.createTextNode("Reading the video's replay data..."));
        status.replaceChildren(loading);

        const { ok, data, parsed } = await postJson('/api/clip-suggestions', { url, duration })
            .catch(() => ({ ok: false, data: {}, parsed: false }));
        if (!ok || !data.success) {
            status.replaceChildren(notice('error', 'No suggestions.',
                parsed ? (data.error || 'Try again in a moment.') : 'The app did not answer. Try again in a moment.'));
            return;
        }
        const count = data.clips.length === 1 ? '1 moment' : `${data.clips.length} moments`;
        const signals = data.signals || {};
        const note = signals.captions ? ''
            : signals.captions_unreadable ? ' YouTube did not let the app read the captions this time, so a clip may start mid-sentence.'
                : ' This video has no captions, so a clip may start mid-sentence.';
        status.replaceChildren(notice('info', `${count}, best first.`, `Choose one to fill in the start and length.${note}`));
        $('suggestions').replaceChildren(...data.clips.map(suggestionItem));
    }

    $('suggestBtn').addEventListener('click', () => {
        if ($('suggestBtn').getAttribute('aria-disabled') === 'true') {
            $('suggestStatus').replaceChildren(notice('info', 'Analyze a YouTube link first.',
                'Paste it above; suggestions use its replay data.'));
            return;
        }
        ui.whileWorking($('suggestBtn'), 'Looking...', suggestMoments);
    });

    // ---- create a short: a background job, followed in a progress card ----------

    function setRendering(isRendering) {
        rendering = isRendering;
        const submit = $('createSubmit');
        submit.textContent = 'Creating...';
        if (!isRendering) updateTiming();
        if (isRendering) submit.setAttribute('aria-disabled', 'true');
        else submit.removeAttribute('aria-disabled');
    }

    // The finished short: downloaded from here, or found again in Your shorts
    function showNewShort(result) {
        const message = notice('ok', 'Your short is ready.', 'It is saved in Your shorts until you delete it.');
        const download = element('a', 'btn btn-sm btn-primary notice-action', 'Download');
        download.href = safeUrl(result.download_url, ['/shorts/']);
        download.download = result.filename;
        const open = element('a', 'btn btn-sm notice-action', 'Open in Your shorts');
        open.href = '/shorts?short=' + encodeURIComponent(result.filename);
        message.append(download, open);
        $('formStatus').replaceChildren(message,
            ...(result.warnings || []).map((warning) => notice('warn', 'Note.', warning)));
        download.focus();  // the progress card, and the focus in it, is gone
    }

    async function showOutcome(job) {
        const status = $('formStatus');
        if (job.state === 'succeeded') {
            showNewShort(job.result);
            return;
        }
        if (job.state === 'cancelled') {
            status.replaceChildren(notice('info', 'Cancelled.', 'No short was made.'));
        } else {
            status.replaceChildren(withRetry(notice('error', 'Could not create the short.',
                job.error || 'Try again in a moment.')));
        }
        $('createSubmit').focus();  // the progress card, and the focus in it, is gone
    }

    function followJob(job) {
        setRendering(true);
        jobs.follow(job, $('jobPanel'), {
            title: 'Creating your short',
            onFinish: (final) => {
                setRendering(false);
                showOutcome(final);
            },
        });
    }

    $('shortVideoForm').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (rendering) return;

        const status = $('formStatus');
        status.replaceChildren();
        if (!formIsValid()) return;

        const body = {
            url: $('shortVideoUrl').value.trim(),
            start_time: $('startTime').value.trim() || '0',
            duration: getDuration(),
            quality: $('quality').value,
            vertical_format: $('verticalFormat').checked,
        };
        // The field exists only where captions can be drawn (ImageMagick)
        const overlayText = $('overlayText') ? $('overlayText').value.trim() : '';
        if (overlayText) body.text_overlay = { text: overlayText };
        if (body.vertical_format) body.crop_position = Number(cropPosition.toFixed(3));
        startJob(body);
    });

    let lastRequest = null;   // what "Try again" sends

    async function startJob(body) {
        lastRequest = body;
        const status = $('formStatus');
        status.replaceChildren();
        setRendering(true);
        try {
            followJob(await jobs.start('/api/jobs/create-short', body));
        } catch (error) {
            setRendering(false);
            status.replaceChildren(withRetry(notice('error', 'Could not start.', error.message)));
        }
    }

    // The same short again, with the settings it was asked with
    function withRetry(message) {
        if (!lastRequest) return message;
        const retry = element('button', 'btn btn-sm notice-action', 'Try again');
        retry.type = 'button';
        retry.addEventListener('click', () => {
            if (!rendering) startJob(lastRequest);
        });
        message.append(retry);
        return message;
    }

    // A short still being made when this page was (re)opened: follow it. Finished ones are
    // in Your shorts, which is read from disk.
    async function resumeRunningJob() {
        const job = await jobs.latest('short');
        if (!rendering && job && jobs.isActive(job)) followJob(job);  // rendering: just started here
    }

    // ---- prefill from ?url= -----------------------------------------------

    const prefill = new URLSearchParams(window.location.search).get('url');
    if (prefill) $('shortVideoUrl').value = prefill;
    source = videoSource.attach({ input: $('shortVideoUrl'), button: $('analyzeShortBtn'),
                                  panel: $('shortLinkPreview'), onChange: onSourceChange });
    onSourceChange(source.state());  // the empty start reports no change, so apply it once
    updateCropDiagram();
    resumeRunningJob();
})();
