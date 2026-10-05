(function () {
    'use strict';

    const MAX_DURATION_SECONDS = 300;
    const DEFAULT_DURATION = '30';
    const AUTH_TIMEOUT_MS = 300000;
    const AUTH_POLL_MS = 1000;
    const BYTES_PER_MB = 1024 * 1024;
    const $ = (id) => document.getElementById(id);
    let busy = false;
    let signedIn = false;          // set once the server confirms the YouTube sign-in
    let cancelRequested = false;   // set by the Cancel button while waiting for sign-in

    // Server text is untrusted for display purposes: everything below is built
    // with textContent / addEventListener instead of HTML strings.
    const { element, notice, scrollBehavior, relativeTime, postJson } = ui;

    function safeUrl(value, allowedPrefixes) {
        return allowedPrefixes.some((prefix) => typeof value === 'string' && value.startsWith(prefix))
            ? value : '';
    }

    function showLoading(message, cancellable) {
        $('cancelLoadingBtn').hidden = !cancellable;
        ui.showBusy(message);
        if (cancellable) $('cancelLoadingBtn').focus();
    }

    function hideLoading() {
        $('cancelLoadingBtn').hidden = true;
        ui.hideBusy();
    }

    $('cancelLoadingBtn').addEventListener('click', () => {
        cancelRequested = true;
    });

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
        option.addEventListener('click', () => selectDuration(option));
    });

    // ---- crop diagram -----------------------------------------------------

    function updateCropDiagram() {
        const vertical = $('verticalFormat').checked;
        $('cropFigure').classList.toggle('is-full', !vertical);
        $('cropCaption').textContent = vertical
            ? 'The outlined area is what you keep. Wide videos are cropped around the center.'
            : 'The whole picture is kept. Nothing is cropped.';
    }

    $('verticalFormat').addEventListener('change', updateCropDiagram);

    // ---- link check -------------------------------------------------------

    ui.attachLinkCheck($('validateShortBtn'), $('shortVideoUrl'), $('shortLinkStatus'));

    // ---- check the form before anything is downloaded ----------------------

    function linkError() {
        const url = $('shortVideoUrl').value.trim();
        if (!url) return 'Enter a video link to cut a short from';
        if (!ui.isLink(url)) return 'Enter a full link, starting with https://';
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
        if (!value || ui.parseTimecode(value) !== null || (Number.isFinite(asSeconds) && asSeconds >= 0)) return null;
        return 'Enter the start as m:ss, h:mm:ss or seconds, for example 1:30 or 90';
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

    // ---- create a short ---------------------------------------------------

    $('shortVideoForm').addEventListener('submit', async (event) => {
        event.preventDefault();
        if (busy) return;

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
        const overlayText = $('overlayText').value.trim();
        if (overlayText) body.text_overlay = { text: overlayText };

        busy = true;
        showLoading('Creating the short. Downloading and rendering can take a few minutes.');
        try {
            const { ok, data } = await postJson('/api/create-short', body);
            if (!ok || !data.success) {
                throw new Error(data.error || 'Short video creation failed');
            }
            await showNewShort(data);
        } catch (error) {
            console.error('Short video creation error:', error);
            status.replaceChildren(notice('error', 'Could not create the short.', error.message));
        } finally {
            busy = false;
            hideLoading();
        }
    });

    // ---- your shorts: kept on disk, listed again after a refresh ------------

    // Deleting cannot be undone, so it is confirmed in a dialog (no time limit to beat)
    function confirmDelete(item) {
        const dialog = element('dialog', 'dialog');
        dialog.setAttribute('aria-labelledby', 'deleteHeading');
        dialog.addEventListener('close', () => dialog.remove());

        const heading = element('h2', undefined, 'Delete this short?');
        heading.id = 'deleteHeading';
        const note = element('p', undefined, `"${item.title}" is removed from this computer. This cannot be undone.`);

        const remove = element('button', 'btn btn-danger', 'Delete short');
        remove.type = 'button';
        remove.addEventListener('click', () => {
            dialog.close();
            deleteShort(item);
        });
        const keep = element('button', 'btn', 'Keep it');
        keep.type = 'button';
        keep.addEventListener('click', () => dialog.close());

        const actions = element('div', 'actions');
        actions.append(remove, keep);
        dialog.append(heading, note, actions);
        document.body.append(dialog);
        dialog.showModal();
        keep.focus();  // the safe choice is the default
    }

    async function deleteShort(item) {
        try {
            const { ok, data } = await postJson('/api/shorts/delete', { filename: item.filename });
            if (!ok || !data.success) throw new Error(data.error || 'Could not delete the short');
            await loadLibrary();
            $('resultsStatus').replaceChildren(notice('ok', 'Short deleted.', `"${item.title}" was removed.`));
        } catch (error) {
            $('resultsStatus').replaceChildren(notice('error', 'Could not delete the short.', error.message));
        }
        // The deleted card took focus with it; continue from the list heading
        $('resultHeading').focus();
    }

    function shortCard(item, isNew) {
        const source = safeUrl(item.url, ['/shorts/']);

        const video = element('video', 'short-video');
        video.controls = true;
        video.preload = 'metadata';
        video.playsInline = true;
        if (source) video.src = source + '#t=0.1';  // shows the first moment as the cover

        const meta = element('p', 'short-meta');
        if (item.duration) meta.append(element('span', undefined, `${item.duration} s`));
        if (item.size) meta.append(element('span', undefined, (item.size / BYTES_PER_MB).toFixed(1) + ' MB'));
        meta.append(element('span', undefined, relativeTime(item.created)));

        // Every card has the same three buttons; the labels say which short they act on
        const download = element('a', 'btn btn-sm', 'Download');
        download.href = source;
        download.download = item.filename;
        download.setAttribute('aria-label', `Download ${item.title}`);

        const upload = element('button', 'btn btn-sm', 'Upload to YouTube');
        upload.type = 'button';
        upload.setAttribute('aria-label', `Upload ${item.title} to YouTube`);
        upload.addEventListener('click', () => startYouTubeUpload(item.filename, item.title));

        const remove = element('button', 'btn btn-sm btn-quiet', 'Delete');
        remove.type = 'button';
        remove.setAttribute('aria-label', `Delete ${item.title}`);
        remove.addEventListener('click', () => confirmDelete(item));

        const actions = element('div', 'short-actions');
        actions.append(download, upload, remove);

        const card = element('li', isNew ? 'card card-flush short-card is-new' : 'card card-flush short-card');
        const body = element('div', 'short-body');
        body.append(element('h3', 'short-title clamp', item.title), meta, actions);
        card.append(video, body);
        return card;
    }

    async function loadLibrary(newFilename) {
        try {
            const response = await fetch('/api/shorts');
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');

            const cards = data.shorts.map((item) => shortCard(item, item.filename === newFilename));
            $('resultsContent').replaceChildren(...cards);
            $('libraryLoading').hidden = true;
            $('libraryEmpty').hidden = cards.length > 0;
            $('libraryCount').textContent = cards.length === 1 ? '1 short' : cards.length ? `${cards.length} shorts` : '';
            return cards;
        } catch (error) {
            console.error('Could not load the shorts:', error);
            $('libraryLoading').hidden = true;
            $('resultsStatus').replaceChildren(
                notice('error', 'Could not load your earlier shorts.', 'Refresh the page to try again.'));
            return [];
        }
    }

    async function showNewShort(result) {
        $('resultsStatus').replaceChildren(
            notice('ok', 'Your short is ready.', 'It is first in the list below, and it stays there after you leave this page.'),
            ...(result.warnings || []).map((warning) => notice('warn', 'Note.', warning)));
        const cards = await loadLibrary(result.filename);
        if (cards.length) cards[0].scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
    }

    function resetForm() {
        $('shortVideoForm').reset();
        ui.clearErrors($('errorSummary'), checks.map(([input]) => input));
        $('formStatus').replaceChildren();
        $('shortLinkStatus').replaceChildren();
        $('shortLinkPreview').replaceChildren();
        selectDuration(document.querySelector(`.duration-option[data-duration="${DEFAULT_DURATION}"]`));
        updateCropDiagram();
        $('shortVideoUrl').focus();
    }

    $('resetFormBtn').addEventListener('click', resetForm);

    // ---- YouTube upload ---------------------------------------------------

    const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    async function isSignedInToYouTube() {
        const response = await fetch('/api/youtube-auth');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not check the YouTube sign-in');
        return data.authenticated === true;
    }

    // The popup must be opened synchronously inside the click handler (before any
    // asynchronous work), otherwise browsers treat it as unrequested and may block it.
    function openSignInWindow() {
        return window.open('', 'youtube_auth', 'width=600,height=700,scrollbars=yes,resizable=yes');
    }

    async function ensureSignedIn(popup) {
        if (await isSignedInToYouTube()) {
            signedIn = true;
            if (popup) popup.close();
            return true;
        }
        if (!popup) throw new Error('Allow pop-ups for this page and try again');

        const { ok, data } = await postJson('/api/youtube-auth/start', {});
        if (!ok || !data.auth_url) {
            popup.close();
            throw new Error(data.error || 'Could not start the YouTube sign-in');
        }
        popup.location.href = data.auth_url;
        showLoading('Waiting for you to sign in to YouTube in the other window...', true);

        // Poll the server rather than the popup state: Google's pages can sever the
        // link to the opener, which makes the popup's closed flag unreliable.
        const deadline = Date.now() + AUTH_TIMEOUT_MS;
        while (Date.now() < deadline) {
            await sleep(AUTH_POLL_MS);
            if (cancelRequested) {
                popup.close();
                return false;
            }
            if (await isSignedInToYouTube()) {
                signedIn = true;
                popup.close();
                return true;
            }
        }
        popup.close();
        throw new Error('Sign-in timed out');
    }

    function startYouTubeUpload(filename, title) {
        const popup = signedIn ? null : openSignInWindow();  // synchronous: see above
        uploadToYouTube(filename, title, popup);
    }

    async function uploadToYouTube(filename, title, popup) {
        if (busy) {
            if (popup) popup.close();
            return;
        }
        busy = true;
        cancelRequested = false;
        let uploaded = null;
        const status = $('resultsStatus');
        status.replaceChildren();
        showLoading('Signing in to YouTube...');
        try {
            if (!(await ensureSignedIn(popup))) {
                status.replaceChildren(notice('warn', 'Sign-in cancelled.', 'Nothing was uploaded.'));
                return;
            }
            showLoading('Uploading to YouTube...');
            const { ok, data } = await postJson('/api/upload-to-youtube', {
                filename: filename,
                title: title || 'Short video',
                description: 'Created with VideoExtract',
                tags: ['Shorts'],
                privacy: 'private',  // change it in YouTube Studio when you are ready
            });
            if (!ok || !data.success) throw new Error(data.error || 'Upload failed');
            uploaded = data;
        } catch (error) {
            console.error('YouTube upload failed:', error);
            status.replaceChildren(notice('error', 'Upload failed.', error.message));
        } finally {
            if (popup && !popup.closed) popup.close();
            busy = false;
            hideLoading();
        }
        // Opened only after the overlay is gone, so closing it returns focus to the Upload button
        if (uploaded) showYouTubeSuccess(uploaded);
    }

    function showYouTubeSuccess(result) {
        const dialog = element('dialog', 'dialog');
        dialog.setAttribute('aria-labelledby', 'uploadedHeading');
        dialog.addEventListener('close', () => dialog.remove());

        const heading = element('h2', undefined, 'Uploaded to YouTube');
        heading.id = 'uploadedHeading';
        const note = element('p', undefined,
            `Your video was uploaded as ${result.privacy}. You can change this in YouTube Studio.`);

        const actions = element('div', 'actions');
        const watchUrl = safeUrl(result.youtube_url, ['https://www.youtube.com/']);
        const studioUrl = safeUrl(result.studio_url, ['https://studio.youtube.com/']);
        [[watchUrl, 'btn btn-primary', 'View on YouTube'],
         [studioUrl, 'btn', 'Edit in YouTube Studio']].forEach(([href, classes, label]) => {
            if (!href) return;
            const link = element('a', classes, label);
            link.href = href;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            actions.append(link);
        });
        const close = element('button', 'btn', 'Close');
        close.type = 'button';
        close.addEventListener('click', () => dialog.close());
        actions.append(close);

        dialog.append(heading, note, actions);
        document.body.append(dialog);
        dialog.showModal();
    }

    $('libraryStart').addEventListener('click', () => $('shortVideoUrl').focus());

    // ---- prefill from ?url= -----------------------------------------------

    const prefill = new URLSearchParams(window.location.search).get('url');
    if (prefill) $('shortVideoUrl').value = prefill;
    window.attachLinkPreview($('shortVideoUrl'), $('shortLinkPreview'));
    updateCropDiagram();
    loadLibrary();
})();
