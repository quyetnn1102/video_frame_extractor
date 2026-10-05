/* Shared, accessible UI pieces: the busy overlay, form errors and timecode checks.
   Everything is built with textContent; messages may contain text from the server. */
(function () {
    'use strict';

    // Same formats as TIMESTAMP_PATTERNS in validators.py: seconds, m:ss or h:mm:ss
    const TIMECODE_PATTERNS = [
        [/^(\d{1,6})$/, (m) => Number(m[1])],
        [/^(\d{1,3}):([0-5]\d)$/, (m) => Number(m[1]) * 60 + Number(m[2])],
        [/^(\d{1,2}):([0-5]\d):([0-5]\d)$/, (m) => Number(m[1]) * 3600 + Number(m[2]) * 60 + Number(m[3])],
    ];

    const RELATIVE_UNITS = [['day', 86400], ['hour', 3600], ['minute', 60]];

    let focusBeforeBusy = null;

    // ---- building DOM: titles and messages come from other sites and the server,
    //      so text only ever goes in through textContent ---------------------------

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    }

    /** @param {'ok'|'warn'|'error'|'info'} kind */
    function notice(kind, lead, message) {
        const node = element('div', 'notice notice-' + kind);
        if (lead) node.append(element('strong', undefined, lead + ' '));
        node.append(document.createTextNode(message));
        return node;
    }

    function scrollBehavior() {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth';
    }

    function relativeTime(isoDate) {
        const seconds = (new Date(isoDate).getTime() - Date.now()) / 1000;
        const formatter = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
        for (const [unit, size] of RELATIVE_UNITS) {
            if (Math.abs(seconds) >= size) return formatter.format(Math.round(seconds / size), unit);
        }
        return 'just now';
    }

    /**
     * @returns {Promise<{ok: boolean, data: object, parsed: boolean}>}
     *     parsed is false (and data {}) when the reply is not JSON, e.g. a proxy or server error page
     */
    async function postJson(url, body) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        let data = {};
        let parsed = true;
        try {
            data = await response.json();
        } catch (error) {
            parsed = false;  // callers report this through their own generic message
        }
        return { ok: response.ok, data, parsed };
    }

    /** @returns {number|null} whole seconds, or null when the text is not a timecode */
    function parseTimecode(text) {
        const value = String(text).trim();
        for (const [pattern, toSeconds] of TIMECODE_PATTERNS) {
            const match = pattern.exec(value);
            if (match) return toSeconds(match);
        }
        return null;
    }

    function isLink(value) {
        try {
            const url = new URL(value);
            return (url.protocol === 'https:' || url.protocol === 'http:') && url.hostname.includes('.');
        } catch (error) {
            return false;
        }
    }

    // ---- busy overlay: a modal for keyboard and screen reader users too ----------

    function announce(message) {
        const status = document.getElementById('busyStatus');
        if (status) status.textContent = message;
    }

    function showBusy(message) {
        const overlay = document.getElementById('loadingOverlay');
        document.getElementById('loadingMessage').textContent = message;
        announce(message);
        if (overlay.style.display === 'flex') {
            // Already open: only the message changes, unless the focused button was just hidden
            if (!overlay.contains(document.activeElement)) overlay.querySelector('h2').focus();
            return;
        }

        focusBeforeBusy = document.activeElement;
        document.querySelector('.app').inert = true;
        overlay.style.display = 'flex';
        overlay.querySelector('h2').focus();
    }

    /**
     * @param {HTMLElement} [focusTarget] where focus goes next, for example the results heading;
     *     by default it returns to where it was before the overlay opened
     */
    function hideBusy(focusTarget) {
        const overlay = document.getElementById('loadingOverlay');
        overlay.style.display = 'none';
        // Focus can only move once the page is no longer inert
        document.querySelector('.app').inert = false;
        announce('');
        let target = focusTarget || (focusBeforeBusy && focusBeforeBusy.isConnected ? focusBeforeBusy : null);
        if (!target) {
            target = document.getElementById('main');
            target.tabIndex = -1;  // <main> is not focusable by default
        }
        focusBeforeBusy = null;
        target.focus({ preventScroll: true });
    }

    // ---- form errors (GOV.UK pattern: a summary on top, a message at each field) ----

    function errorId(input) {
        return input.id + 'Error';
    }

    function setFieldError(input, message) {
        const field = input.closest('.field');
        let error = document.getElementById(errorId(input));
        if (!error) {
            error = element('p', 'field-error');
            error.id = errorId(input);
            field.querySelector('label, .label').after(error);
        }
        error.textContent = message;
        field.classList.add('has-error');
        input.setAttribute('aria-invalid', 'true');
        const described = (input.getAttribute('aria-describedby') || '').split(' ').filter(Boolean);
        if (!described.includes(error.id)) input.setAttribute('aria-describedby', [error.id, ...described].join(' '));
    }

    function clearFieldError(input) {
        const error = document.getElementById(errorId(input));
        if (error) error.remove();
        const field = input.closest('.field');
        if (field) field.classList.remove('has-error');
        input.removeAttribute('aria-invalid');
        const described = (input.getAttribute('aria-describedby') || '').split(' ')
            .filter((id) => id && id !== errorId(input));
        if (described.length) input.setAttribute('aria-describedby', described.join(' '));
        else input.removeAttribute('aria-describedby');
    }

    /**
     * Shows every problem at once, then moves focus to the summary so it is read out.
     * @param {HTMLElement} summary an empty container at the top of the form
     * @param {{input: HTMLElement, message: string}[]} errors
     */
    function showErrors(summary, errors) {
        errors.forEach(({ input, message }) => setFieldError(input, message));
        const list = element('ul');
        errors.forEach(({ input, message }) => {
            const link = element('a', undefined, message);
            link.href = '#' + input.id;
            link.addEventListener('click', (event) => {
                event.preventDefault();
                input.focus();
            });
            const item = element('li');
            item.append(link);
            list.append(item);
        });
        summary.replaceChildren(element('h2', undefined, 'There is a problem'), list);
        summary.hidden = false;
        summary.focus();
    }

    function clearErrors(summary, inputs) {
        inputs.forEach(clearFieldError);
        summary.replaceChildren();
        summary.hidden = true;
    }

    /**
     * Re-checks a field while the user corrects it, so its error goes away as soon as it is fixed.
     * @param {HTMLElement} input
     * @param {() => (string|null)} check returns the error message, or null when the value is fine
     */
    function revalidateOnInput(input, check) {
        input.addEventListener('input', () => {
            if (input.getAttribute('aria-invalid') !== 'true') return;
            const message = check();
            if (message) setFieldError(input, message);
            else clearFieldError(input);
        });
    }

    // ---- a button that shows it is working, without losing keyboard focus ----------

    async function whileWorking(button, workingLabel, task) {
        if (button.getAttribute('aria-disabled') === 'true') return;
        const label = button.textContent;
        button.setAttribute('aria-disabled', 'true');
        button.textContent = workingLabel;
        try {
            await task();
        } finally {
            button.textContent = label;
            button.removeAttribute('aria-disabled');
        }
    }

    // ---- "Check link": the same check and the same message on every page ------------

    /**
     * Wires a Check link button: asks the server whether the link can be used, then says so.
     * @param {HTMLButtonElement} button
     * @param {HTMLInputElement} input the link field
     * @param {HTMLElement} status where the result is shown
     */
    function attachLinkCheck(button, input, status) {
        button.addEventListener('click', () => whileWorking(button, 'Checking...', async () => {
            const url = input.value.trim();
            if (!url) {
                status.replaceChildren(notice('error', 'No link yet.', 'Paste a video link first.'));
                return;
            }
            try {
                const { ok, data, parsed } = await postJson('/api/test-platform', { url });
                // A broken reply says nothing about the link itself
                if (!parsed) throw new Error('The server did not answer with JSON');
                const info = data.info || {};
                if (!ok || !data.valid) {
                    status.replaceChildren(notice('error', 'This link cannot be used.',
                        info.notes || data.error || 'It is invalid or from an unsupported site.'));
                    return;
                }
                const result = notice('ok', 'This link works.',
                    `${data.platform}: ${info.status || 'ready'}. ${info.notes || ''}`.trim());
                if (Array.isArray(info.tips) && info.tips.length) {
                    result.append(element('span', 'tips', 'Tips: ' + info.tips.join(', ')));
                }
                status.replaceChildren(result);
            } catch (error) {
                console.error('Link check failed:', error);
                status.replaceChildren(notice('error', 'Could not check the link.', 'Try again in a moment.'));
            }
        }));
    }

    window.ui = {
        element, notice, scrollBehavior, relativeTime, postJson, attachLinkCheck,
        parseTimecode, isLink, showBusy, hideBusy,
        setFieldError, clearFieldError, showErrors, clearErrors, revalidateOnInput, whileWorking,
    };
})();
