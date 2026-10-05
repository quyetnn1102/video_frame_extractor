/* Shows what a pasted video link points to (thumbnail, title, channel, length) before it is used.
   Data comes from POST /api/video-info and is untrusted: it is only ever set with textContent. */
(function () {
    'use strict';

    const LOOKUP_DELAY_MS = 700;
    const SECONDS_PER_MINUTE = 60;
    const SECONDS_PER_HOUR = 3600;

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    function httpsUrl(value) {
        try {
            const url = new URL(value);
            return url.protocol === 'https:' ? url.href : '';
        } catch (error) {
            return '';
        }
    }

    function looksLikeLink(value) {
        try {
            const url = new URL(value);
            return (url.protocol === 'https:' || url.protocol === 'http:') && url.hostname.includes('.');
        } catch (error) {
            return false;
        }
    }

    function formatLength(totalSeconds) {
        const seconds = Math.round(Number(totalSeconds));
        if (!Number.isFinite(seconds) || seconds <= 0) return '';
        const hours = Math.floor(seconds / SECONDS_PER_HOUR);
        const minutes = Math.floor((seconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE);
        const rest = String(seconds % SECONDS_PER_MINUTE).padStart(2, '0');
        return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
    }

    function note(text) {
        return element('p', 'preview-note', text);
    }

    function card(info) {
        const text = element('div', 'preview-text');
        text.append(element('strong', 'preview-title clamp', info.title || 'Untitled video'));

        const facts = element('div', 'preview-facts');
        [info.platform, info.uploader].forEach((fact) => {
            if (fact) facts.append(element('span', undefined, String(fact)));
        });
        const length = formatLength(info.duration);
        if (length) facts.append(element('span', 'time', length));
        text.append(facts);

        const preview = element('div', 'preview');
        const thumbnail = httpsUrl(info.thumbnail);
        if (thumbnail) {
            const image = element('img', 'preview-thumb');
            image.src = thumbnail;
            image.alt = '';
            preview.append(image);
        }
        preview.append(text);
        return preview;
    }

    /* Watches `input`; fills `container` once the link has stayed unchanged for a moment. */
    window.attachLinkPreview = function (input, container) {
        let timer = null;
        let latest = 0;   // a slow answer for an older link must not replace a newer one

        async function lookUp(url) {
            const mine = ++latest;
            container.replaceChildren(note('Looking up the video...'));
            try {
                const response = await fetch('/api/video-info', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ url }),
                });
                const data = await response.json();
                if (mine !== latest) return;
                if (response.ok && data.success && data.video_info) {
                    container.replaceChildren(card(data.video_info));
                } else {
                    container.replaceChildren(note(data.error || 'No preview for this link. You can still try it.'));
                }
            } catch (error) {
                if (mine !== latest) return;
                container.replaceChildren(note('No preview for this link. You can still try it.'));
            }
        }

        function schedule() {
            clearTimeout(timer);
            const url = input.value.trim();
            if (!looksLikeLink(url)) {
                latest += 1;
                container.replaceChildren();
                return;
            }
            timer = setTimeout(() => lookUp(url), LOOKUP_DELAY_MS);
        }

        input.addEventListener('input', schedule);
        schedule();
        return { refresh: schedule };
    };
})();
