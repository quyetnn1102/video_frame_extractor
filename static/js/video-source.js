/* The video a page works on: the link field, an "Analyze video" button and a panel that shows
   what the link points to. Home, Create short and Extract frames all use it, so the check, the
   wording and the errors are the same everywhere, and a page can check a start time or a
   timecode against the video's length before anything is downloaded.

   Data comes from POST /api/video-info and is untrusted: it is only ever set with textContent.
   Needs ui.js. */
(function () {
    'use strict';

    const LOOKUP_DELAY_MS = 700;
    const { element, notice, formatClock, isLink, postJson } = ui;

    /*
     * What the page knows about the link (state.status):
     *   empty       nothing typed
     *   incomplete  typed, but not a full link yet (nothing is shown while typing)
     *   checking    asking the server
     *   ready       the video was read: state.video has its length and frame size
     *   unreadable  the link is supported but its details could not be read; it may still work
     *   invalid     the link cannot be used (unsupported site, malformed)
     */
    const USABLE = new Set(['ready', 'unreadable']);

    function httpsUrl(value) {
        try {
            const url = new URL(value);
            return url.protocol === 'https:' ? url.href : '';
        } catch (error) {
            return '';
        }
    }

    function frameSize(video) {
        const width = Number(video.width);
        const height = Number(video.height);
        if (!(width > 0 && height > 0)) return '';
        const shape = height > width ? 'vertical' : height === width ? 'square' : 'wide';
        return `${width} × ${height} (${shape})`;
    }

    function card(video) {
        const text = element('div', 'preview-text');
        text.append(element('strong', 'preview-title clamp', video.title || 'Untitled video'));

        const facts = element('div', 'preview-facts');
        [video.platform_name || video.platform, video.uploader].forEach((fact) => {
            if (fact) facts.append(element('span', undefined, String(fact)));
        });
        const length = formatClock(video.duration);
        if (length) facts.append(element('span', 'time', length));
        const size = frameSize(video);
        if (size) facts.append(element('span', undefined, size));
        text.append(facts);

        const preview = element('div', 'preview');
        const thumbnail = httpsUrl(video.thumbnail);
        if (thumbnail) {
            const image = element('img', 'preview-thumb');
            image.src = thumbnail;
            image.alt = '';
            preview.append(image);
        }
        preview.append(text);
        return preview;
    }

    function withTips(message, tips) {
        if (Array.isArray(tips) && tips.length) {
            const list = element('ul', 'tips');
            tips.forEach((tip) => list.append(element('li', undefined, String(tip))));
            message.append(list);
        }
        return message;
    }

    /**
     * @param {{input: HTMLInputElement, button?: HTMLButtonElement, panel: HTMLElement,
     *          onChange?: function(object): void}} options onChange gets the new state
     * @returns {{state: function(): object, analyze: function(): Promise<void>, isUsable: function(): boolean}}
     */
    function attach(options) {
        const { input, button, panel } = options;
        let state = { status: 'empty', url: '' };
        let timer = null;
        let latest = 0;   // a slow answer for an older link must not replace a newer one

        function set(next) {
            state = next;
            if (options.onChange) options.onChange(state);
        }

        function retryButton() {
            const retry = element('button', 'btn btn-sm notice-action', 'Try again');
            retry.type = 'button';
            retry.addEventListener('click', () => analyze());
            return retry;
        }

        function show(status, url, data) {
            if (status === 'ready') {
                panel.replaceChildren(card(data.video_info));
                set({ status, url, video: data.video_info });
                return;
            }
            if (status === 'invalid') {
                panel.replaceChildren(withTips(notice('error', 'This link cannot be used.',
                    data.error || 'It is not a video link from a supported site.'), data.tips));
                set({ status, url, message: data.error });
                return;
            }
            // Supported but not readable: often a private, region-locked or login-only video
            const message = withTips(notice('warn', "Could not read this video's details.",
                (data.error ? data.error + ' ' : '') + 'You can still try it, but its length cannot be checked first.'),
                data.tips);
            message.append(retryButton());
            panel.replaceChildren(message);
            set({ status, url, message: data.error });
        }

        async function analyze() {
            clearTimeout(timer);
            const url = input.value.trim();
            if (!url) {  // only reached when asked: typing never analyzes an empty field
                latest += 1;
                panel.replaceChildren(notice('error', 'No link yet.', 'Paste a video link first.'));
                set({ status: 'empty', url });
                return;
            }
            if (!isLink(url)) {
                latest += 1;
                show('invalid', url, { error: 'Enter a full link, starting with https://' });
                return;
            }
            const mine = ++latest;
            const scanner = element('span', 'mark is-scanning');
            scanner.setAttribute('aria-hidden', 'true');
            const loading = element('p', 'inline-loading');
            loading.append(scanner, document.createTextNode('Analyzing the video...'));
            panel.replaceChildren(loading);
            set({ status: 'checking', url });

            const { ok, data, parsed } = await postJson('/api/video-info', { url })
                .catch(() => ({ ok: false, data: {}, parsed: false }));
            if (mine !== latest) return;
            if (ok && data.success && data.video_info) show('ready', url, data);
            else if (parsed && data.reason === 'invalid') show('invalid', url, data);
            else show('unreadable', url, parsed ? data : { error: 'The app did not answer.' });
        }

        // While typing, a link is analyzed once it has stayed unchanged for a moment
        function schedule() {
            clearTimeout(timer);
            const url = input.value.trim();
            if (url === state.url && state.status !== 'incomplete') return;
            if (!isLink(url)) {
                latest += 1;
                panel.replaceChildren();
                set({ status: url ? 'incomplete' : 'empty', url });
                return;
            }
            timer = setTimeout(analyze, LOOKUP_DELAY_MS);
        }

        input.addEventListener('input', schedule);
        if (button) button.addEventListener('click', () => ui.whileWorking(button, 'Analyzing...', analyze));
        schedule();

        return {
            state: () => state,
            analyze,
            isUsable: () => USABLE.has(state.status),
        };
    }

    window.videoSource = { attach };
})();
