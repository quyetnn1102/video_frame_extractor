/* Background jobs (download, then extract frames or render a short): start one, follow it in a
   progress card with its step, progress, elapsed time and a Cancel button, and pick it up again
   when the page is opened later. Needs ui.js. Text only ever goes in through textContent. */
(function () {
    'use strict';

    const POLL_MS = 1000;
    const ACTIVE_STATES = ['queued', 'running'];
    const SECONDS_PER_MINUTE = 60;
    const RESTARTED_ERROR = 'The app was restarted, so this job stopped. Start it again.';
    const LOST_CONTACT_ERROR = 'Lost contact with the app. Refresh the page to see how the job is doing.';
    const MAX_FAILED_POLLS = 30;  // about half a minute of the app not answering
    const followers = new WeakMap();  // container -> stop() of the job shown in it
    const { element } = ui;

    function isActive(job) {
        return ACTIVE_STATES.includes(job.state);
    }

    function formatElapsed(totalSeconds) {
        const seconds = Math.max(0, Math.floor(Number(totalSeconds) || 0));
        return `${Math.floor(seconds / SECONDS_PER_MINUTE)}:${String(seconds % SECONDS_PER_MINUTE).padStart(2, '0')}`;
    }

    /** POSTs the request; resolves to the new job, or throws an Error whose message can be shown. */
    async function start(path, body) {
        const { ok, data, parsed } = await ui.postJson(path, body);
        if (!parsed) throw new Error('The app did not answer. Try again in a moment.');
        if (!ok || !data.success) throw new Error(data.error || 'Could not start.');
        return data.job;
    }

    /** The newest job of this kind from the last hour, or null. */
    async function latest(kind) {
        try {
            const response = await fetch('/api/jobs');
            const data = await response.json();
            if (!response.ok || !data.success) return null;
            return data.jobs.find((job) => job.kind === kind) || null;
        } catch (error) {
            console.error('Could not list the jobs:', error);
            return null;
        }
    }

    function buildCard(title) {
        const elapsed = element('span', 'job-elapsed time');
        const head = element('div', 'job-head');
        head.append(element('h2', undefined, title), elapsed);

        const step = element('p', 'job-step');
        const bar = element('progress', 'job-bar');
        bar.max = 1;
        bar.setAttribute('aria-label', title);
        const percent = element('span', 'job-percent time');
        const meter = element('div', 'job-meter');
        meter.append(bar, percent);

        const cancel = element('button', 'btn btn-sm', 'Cancel');
        cancel.type = 'button';
        const foot = element('div', 'job-foot');
        foot.append(element('p', 'job-note', 'You can leave this page. The work goes on and shows up here again.'),
                    cancel);

        // Read out when the step changes, not on every percent
        const announcer = element('p', 'visually-hidden');
        announcer.setAttribute('role', 'status');

        const root = element('section', 'job-card');
        root.setAttribute('aria-label', title);
        root.append(head, step, meter, foot, announcer);
        return { root, step, bar, percent, elapsed, cancel, announcer };
    }

    function stepText(job) {
        if (job.state === 'queued' || !job.stage_index) return job.message;  // "Starting" or "Waiting..."
        return `Step ${job.stage_index} of ${job.stage_count}: ${job.message}`;
    }

    /**
     * Shows `job` in `container` and polls it until it ends, then empties the container.
     * @param {object} job as returned by the API
     * @param {HTMLElement} container
     * @param {{title: string, onFinish: function(object): void}} options onFinish gets the final job
     */
    function follow(job, container, options) {
        const previous = followers.get(container);
        if (previous) previous();  // one job per container: the old poll loop must not keep running
        const card = buildCard(options.title);
        container.replaceChildren(card.root);
        let lastStep = '';
        let finished = false;
        let failedPolls = 0;
        followers.set(container, () => { finished = true; });

        function render(current) {
            const text = stepText(current);
            card.step.textContent = text;
            if (text !== lastStep) {
                card.announcer.textContent = text;
                lastStep = text;
            }
            if (current.progress === null || current.progress === undefined) {
                card.bar.removeAttribute('value');  // indeterminate: the size is not known yet
                card.percent.textContent = '';
            } else {
                card.bar.value = current.progress;
                card.percent.textContent = Math.round(current.progress * 100) + '%';
            }
            card.elapsed.textContent = formatElapsed(current.elapsed_seconds);
        }

        function finish(final) {
            if (finished) return;
            finished = true;
            followers.delete(container);
            container.replaceChildren();
            options.onFinish(final);
        }

        async function poll() {
            if (finished) return;
            try {
                const response = await fetch('/api/jobs/' + encodeURIComponent(job.id));
                if (response.status === 404) {
                    finish({ ...job, state: 'failed', error: RESTARTED_ERROR });
                    return;
                }
                const data = await response.json();
                if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');
                failedPolls = 0;
                render(data.job);
                if (!isActive(data.job)) {
                    finish(data.job);
                    return;
                }
            } catch (error) {
                failedPolls += 1;
                if (failedPolls >= MAX_FAILED_POLLS) {
                    console.error('Could not check the job:', error);
                    finish({ ...job, state: 'failed', error: LOST_CONTACT_ERROR });
                    return;
                }
            }
            setTimeout(poll, POLL_MS);
        }

        // Stays "Cancelling..." until the job reports that it stopped and the card goes away
        card.cancel.addEventListener('click', async () => {
            if (card.cancel.getAttribute('aria-disabled') === 'true') return;
            card.cancel.setAttribute('aria-disabled', 'true');
            card.cancel.textContent = 'Cancelling...';
            const { ok, data } = await ui.postJson('/api/jobs/' + encodeURIComponent(job.id) + '/cancel', {})
                .catch(() => ({ ok: false, data: {} }));
            if (!ok || !data.success) {
                card.cancel.removeAttribute('aria-disabled');
                card.cancel.textContent = 'Cancel';
                card.announcer.textContent = 'Could not cancel. Try again.';
            }
        });

        render(job);
        if (isActive(job)) setTimeout(poll, POLL_MS);
        else finish(job);
    }

    window.jobs = { start, latest, follow, isActive };
})();
