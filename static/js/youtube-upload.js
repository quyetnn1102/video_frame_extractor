/* Uploading a short to the user's own YouTube channel: review the details, sign in (in a popup)
   when needed, upload, then link to the video. Used by the Your shorts page; needs ui.js and the
   page's busy overlay (#loadingOverlay with #cancelLoadingBtn). Server text is untrusted for
   display: everything is built with textContent. */
(function () {
    'use strict';

    const AUTH_TIMEOUT_MS = 300000;
    const AUTH_POLL_MS = 1000;
    const TITLE_LIMIT = 100;          // TITLE_LIMIT in youtube_uploader.py
    const DESCRIPTION_LIMIT = 5000;   // DESCRIPTION_LIMIT
    const { element, notice, postJson } = ui;
    let signedIn = false;          // set once the server confirms the YouTube sign-in
    let cancelRequested = false;   // set by the Cancel button while waiting for sign-in
    let uploading = false;

    const sleep = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

    function safeUrl(value, allowedPrefixes) {
        return allowedPrefixes.some((prefix) => typeof value === 'string' && value.startsWith(prefix)) ? value : '';
    }

    function cancelButton() {
        return document.getElementById('cancelLoadingBtn');
    }

    function showLoading(message, cancellable) {
        const cancel = cancelButton();
        if (cancel) cancel.hidden = !cancellable;
        ui.showBusy(message);
        if (cancellable && cancel) cancel.focus();
    }

    function hideLoading() {
        const cancel = cancelButton();
        if (cancel) cancel.hidden = true;
        ui.hideBusy();
    }

    if (cancelButton()) cancelButton().addEventListener('click', () => { cancelRequested = true; });

    /** {authenticated, configured} from the server; configured: client_secrets.json is in place. */
    async function status() {
        const response = await fetch('/api/youtube-auth');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Could not check the YouTube sign-in');
        signedIn = data.authenticated === true;
        return { authenticated: signedIn, configured: data.configured !== false };
    }

    // The popup must be opened synchronously inside the click handler (before any
    // asynchronous work), otherwise browsers treat it as unrequested and may block it.
    function openSignInWindow() {
        return window.open('', 'youtube_auth', 'width=600,height=700,scrollbars=yes,resizable=yes');
    }

    async function ensureSignedIn(popup) {
        if ((await status()).authenticated) {
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
            if ((await status()).authenticated) {
                popup.close();
                return true;
            }
        }
        popup.close();
        throw new Error('Sign-in timed out');
    }

    function dialogShell(headingText, headingId) {
        const dialog = element('dialog', 'dialog upload-dialog');
        dialog.setAttribute('aria-labelledby', headingId);
        dialog.addEventListener('close', () => dialog.remove());
        const heading = element('h2', undefined, headingText);
        heading.id = headingId;
        dialog.append(heading);
        return dialog;
    }

    function closeButton(dialog, label) {
        const close = element('button', 'btn', label);
        close.type = 'button';
        close.addEventListener('click', () => dialog.close());
        return close;
    }

    /** Says what is missing instead of starting a sign-in that cannot work. */
    function explainSetup() {
        const dialog = dialogShell('YouTube upload is not set up', 'uploadSetupHeading');
        const steps = element('ol');
        ['Create an OAuth client for the YouTube Data API in Google Cloud.',
         'Save its file as client_secrets.json in the app folder.',
         'Restart the app, then upload again.'].forEach((step) => steps.append(element('li', undefined, step)));
        const actions = element('div', 'actions');
        const close = closeButton(dialog, 'Close');
        actions.append(close);
        dialog.append(element('p', undefined, 'Uploads go to your own channel through your own Google API access:'),
                      steps, element('p', 'hint', 'The README section "YouTube upload" has the details.'), actions);
        document.body.append(dialog);
        dialog.showModal();
        close.focus();
    }

    function field(label, control, hint) {
        const wrapper = element('div', 'field');
        const caption = element('label', undefined, label);
        caption.htmlFor = control.id;
        wrapper.append(caption, control);
        if (hint) wrapper.append(element('p', 'hint', hint));
        return wrapper;
    }

    /**
     * Review before anything is published: title, description and who can see it.
     * @param {{filename: string, title: string}} item a short from /api/shorts
     * @param {{status: HTMLElement, onUploaded: function(object): void}} options
     */
    function review(item, options) {
        const dialog = dialogShell('Upload to YouTube', 'uploadReviewHeading');
        const form = element('form', 'stack');
        form.noValidate = true;

        const title = element('input');
        Object.assign(title, { id: 'uploadTitle', type: 'text', maxLength: TITLE_LIMIT, value: item.title || '' });
        const description = element('textarea');
        Object.assign(description, { id: 'uploadDescription', rows: 3, maxLength: DESCRIPTION_LIMIT,
                                     value: 'Created with Tallframe' });
        const privacy = element('select');
        privacy.id = 'uploadPrivacy';
        [['private', 'Private: only you'], ['unlisted', 'Unlisted: anyone with the link'],
         ['public', 'Public: everyone']].forEach(([value, label]) => {
            const option = element('option', undefined, label);
            option.value = value;
            privacy.append(option);
        });

        const upload = element('button', 'btn btn-primary', 'Upload');
        upload.type = 'submit';
        const actions = element('div', 'actions');
        actions.append(upload, closeButton(dialog, 'Not now'));

        form.append(field('Title', title, `Up to ${TITLE_LIMIT} characters.`),
                    field('Description', description),
                    field('Who can watch it', privacy, 'You can change this later in YouTube Studio.'),
                    actions);
        title.addEventListener('input', () => ui.clearFieldError(title));
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            if (!title.value.trim()) {
                ui.setFieldError(title, 'Enter a title');
                title.focus();
                return;
            }
            const details = { title: title.value.trim(), description: description.value.trim(), privacy: privacy.value };
            dialog.close();
            // Still inside the click: the sign-in popup may open
            const popup = signedIn ? null : openSignInWindow();
            send(item.filename, details, popup, options);
        });

        dialog.append(form);
        document.body.append(dialog);
        dialog.showModal();
        title.focus();
    }

    async function send(filename, details, popup, options) {
        if (uploading) {
            if (popup) popup.close();
            return;
        }
        uploading = true;
        cancelRequested = false;
        let uploaded = null;
        options.status.replaceChildren();
        showLoading('Signing in to YouTube...');
        try {
            if (!(await ensureSignedIn(popup))) {
                options.status.replaceChildren(notice('warn', 'Sign-in cancelled.', 'Nothing was uploaded.'));
                return;
            }
            showLoading('Uploading to YouTube...');
            const { ok, data } = await postJson('/api/upload-to-youtube', {
                filename, title: details.title, description: details.description, tags: ['Shorts'],
                privacy: details.privacy,
            });
            if (!ok || !data.success) throw new Error(data.error || 'Upload failed');
            uploaded = data;
        } catch (error) {
            console.error('YouTube upload failed:', error);
            options.status.replaceChildren(notice('error', 'Upload failed.', error.message));
        } finally {
            if (popup && !popup.closed) popup.close();
            uploading = false;
            hideLoading();
        }
        // Opened only after the overlay is gone, so closing it returns focus to the page
        if (uploaded) {
            showSuccess(uploaded);
            if (options.onUploaded) options.onUploaded(uploaded);
        }
    }

    function showSuccess(result) {
        const dialog = dialogShell('Uploaded to YouTube', 'uploadedHeading');
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
        actions.append(closeButton(dialog, 'Close'));
        dialog.append(element('p', undefined,
            `Your video was uploaded as ${result.privacy}. You can change this in YouTube Studio.`), actions);
        document.body.append(dialog);
        dialog.showModal();
    }

    window.youtubeUpload = { status, review, explainSetup };
})();
