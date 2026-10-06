(function () {
    'use strict';

    const PAGE_SIZE = 24;        // cards shown at first, and added by "Show more"
    const FETCH_LIMIT = 100;     // MAX_LIMIT in library.py
    const BYTES_PER_MB = 1024 * 1024;
    const $ = (id) => document.getElementById(id);
    let allShorts = [];          // every short on disk, as /api/shorts lists them
    let shown = PAGE_SIZE;
    let highlighted = null;      // the short to point out (opened from Home, or just made)
    let subtitling = false;      // a subtitled copy is being made (one at a time)
    let youtube = { configured: true, authenticated: false };

    // Titles come from other sites and from file names: everything is built with textContent.
    const { element, notice, scrollBehavior, relativeTime, postJson } = ui;

    function safeUrl(value, allowedPrefixes) {
        return allowedPrefixes.some((prefix) => typeof value === 'string' && value.startsWith(prefix)) ? value : '';
    }

    // ---- the list: every short, then search, sort and filter in the page -------------

    async function fetchAll() {
        const shorts = [];
        let total = Infinity;
        while (shorts.length < total) {
            const response = await fetch(`/api/shorts?limit=${FETCH_LIMIT}&offset=${shorts.length}`);
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');
            shorts.push(...data.shorts);
            total = data.total;
            if (data.shorts.length === 0) break;  // the folder changed while paging
        }
        return shorts;
    }

    const SORTS = {
        newest: (a, b) => b.created.localeCompare(a.created),
        oldest: (a, b) => a.created.localeCompare(b.created),
        longest: (a, b) => (b.duration || 0) - (a.duration || 0),
        largest: (a, b) => (b.size || 0) - (a.size || 0),
    };

    function matchingShorts() {
        const query = $('librarySearch').value.trim().toLowerCase();
        const vietsubOnly = $('vietsubOnly').checked;
        return allShorts
            .filter((item) => !query || item.title.toLowerCase().includes(query))
            .filter((item) => !vietsubOnly || item.subtitled)
            .sort(SORTS[$('librarySort').value] || SORTS.newest);
    }

    function countText(onScreen, matching) {
        const all = allShorts.length === 1 ? '1 short' : `${allShorts.length} shorts`;
        if (allShorts.length === 0) return '';
        const which = matching === allShorts.length ? all : `${matching} of ${all} match`;
        return onScreen < matching ? `${which} · showing ${onScreen}` : which;
    }

    function render() {
        const matching = matchingShorts();
        const page = matching.slice(0, shown);
        $('resultsContent').replaceChildren(...page.map(shortCard));
        $('libraryLoading').hidden = true;
        $('libraryEmpty').hidden = allShorts.length > 0;
        $('noMatches').hidden = allShorts.length === 0 || matching.length > 0;
        $('showMoreBtn').hidden = matching.length <= shown;
        $('libraryCount').textContent = countText(page.length, matching.length);
    }

    async function refresh(newFilename) {
        try {
            allShorts = await fetchAll();
            if (newFilename !== undefined) highlighted = newFilename;
            render();
        } catch (error) {
            console.error('Could not load the shorts:', error);
            $('libraryLoading').hidden = true;
            const message = notice('error', 'Could not load your shorts.', 'They are still on disk.');
            const retry = element('button', 'btn btn-sm notice-action', 'Try again');
            retry.type = 'button';
            retry.addEventListener('click', () => refresh());
            message.append(retry);
            $('resultsStatus').replaceChildren(message);
        }
    }

    ['librarySearch', 'librarySort', 'vietsubOnly'].forEach((id) => {
        $(id).addEventListener(id === 'librarySearch' ? 'input' : 'change', () => {
            shown = PAGE_SIZE;
            render();
        });
    });
    $('libraryTools').addEventListener('submit', (event) => event.preventDefault());
    $('clearFilters').addEventListener('click', () => {
        $('libraryTools').reset();
        shown = PAGE_SIZE;
        render();
        $('librarySearch').focus();
    });
    $('showMoreBtn').addEventListener('click', () => {
        const before = shown;
        shown += PAGE_SIZE;
        render();
        // Continue where the new cards start, not at the top of the list
        const first = $('resultsContent').children[before];
        if (first) first.querySelector('.short-title').focus();
    });

    // ---- one card: the poster plays on demand; Download, and the rest under "More" ----------

    function media(item) {
        const source = safeUrl(item.url, ['/shorts/']);
        const poster = safeUrl(item.poster, ['/shorts/posters/']);
        const box = element('div', 'short-media');
        if (!poster) {
            const video = element('video', 'short-video');
            Object.assign(video, { controls: true, playsInline: true, preload: 'metadata' });
            video.setAttribute('aria-label', item.title);
            if (source) video.src = source + '#t=0.1';  // shows the first moment as the cover
            box.append(video);
            return box;
        }
        // No player controls until it is played: they would cover the picture and its subtitles
        const play = element('button', 'short-play');
        play.type = 'button';
        play.setAttribute('aria-label', `Play ${item.title}`);
        const image = element('img', 'short-video');
        image.src = poster;
        image.alt = '';
        play.append(image, element('span', 'play-mark'));
        play.addEventListener('click', () => {
            const video = element('video', 'short-video');
            Object.assign(video, { controls: true, playsInline: true, autoplay: true, src: source });
            video.setAttribute('aria-label', item.title);
            play.replaceWith(video);
            video.focus();
        });
        box.append(play);
        return box;
    }

    function badges(item) {
        const list = element('p', 'short-badges');
        if (item.subtitled) list.append(element('span', 'badge', 'Vietsub'));
        if (item.busy) list.append(element('span', 'badge is-busy', 'In use'));
        if (item.youtube_url) list.append(element('span', 'badge is-uploaded', 'Uploaded'));
        return list;
    }

    function meta(item) {
        const parts = [];
        if (item.duration > 0) parts.push(ui.formatClock(item.duration));
        if (item.size) parts.push((item.size / BYTES_PER_MB).toFixed(1) + ' MB');
        parts.push(relativeTime(item.created));
        return element('p', 'short-meta', parts.join(' · '));
    }

    function uploadItem(item) {
        if (!youtube.configured) {
            return { label: 'Set up YouTube upload', onSelect: () => youtubeUpload.explainSetup() };
        }
        const label = item.youtube_url ? 'Upload to YouTube again' : 'Upload to YouTube';
        if (item.upload_problem) return { label, disabledReason: item.upload_problem };
        return { label, onSelect: () => youtubeUpload.review(item, {
            status: $('resultsStatus'),
            onUploaded: () => refresh(item.filename),
        }) };
    }

    function menuItems(item) {
        const items = [];
        if (!item.subtitled) {
            items.push({
                label: 'Add Vietnamese subtitles',
                onSelect: () => addSubtitles(item),
                disabledReason: subtitling ? 'Another short is being subtitled' : undefined,
            });
        }
        items.push(uploadItem(item));
        const watch = safeUrl(item.youtube_url, ['https://www.youtube.com/']);
        if (watch) items.push({ label: 'Watch on YouTube', href: watch });
        items.push({ label: 'Copy file name', onSelect: () => copyName(item) });
        items.push({
            label: 'Delete',
            danger: true,
            onSelect: () => confirmDelete(item),
            disabledReason: item.busy ? 'In use right now: try when it finishes' : undefined,
        });
        return items;
    }

    function shortCard(item) {
        const download = element('a', 'btn btn-sm btn-primary', 'Download');
        download.href = safeUrl(item.url, ['/shorts/']);
        download.download = item.filename;
        download.setAttribute('aria-label', `Download ${item.title}`);

        const actions = element('div', 'short-actions');
        actions.append(download, ui.actionMenu('More', `More actions for ${item.title}`, menuItems(item)));

        const title = element('h3', 'short-title clamp', item.title);
        title.title = item.title;  // the whole title, which two lines may cut
        title.tabIndex = -1;       // focused when this short is opened from the Home page

        const body = element('div', 'short-body');
        body.append(badges(item), title, meta(item), actions);
        const isNew = item.filename === highlighted;
        const card = element('li', isNew ? 'card card-flush short-card is-new' : 'card card-flush short-card');
        card.dataset.filename = item.filename;
        card.append(media(item), body);
        return card;
    }

    async function copyName(item) {
        try {
            await navigator.clipboard.writeText(item.filename);
            $('resultsStatus').replaceChildren(notice('ok', 'Copied.', item.filename));
        } catch (error) {
            $('resultsStatus').replaceChildren(notice('error', 'Could not copy.', item.filename));
        }
    }

    // ---- delete: cannot be undone, so it is confirmed in a dialog ---------------------

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
            await refresh();
            $('resultsStatus').replaceChildren(notice('ok', 'Short deleted.', `"${item.title}" was removed.`));
        } catch (error) {
            $('resultsStatus').replaceChildren(notice('error', 'Could not delete the short.', error.message));
        }
        // The deleted card took focus with it; continue from the list heading
        $('resultHeading').focus();
    }

    // ---- Vietnamese subtitles: a copy of a short, made by a background job -------

    function setSubtitling(isSubtitling) {
        subtitling = isSubtitling;
        render();  // the menus say why subtitles cannot start meanwhile
    }

    async function showSubtitleOutcome(job) {
        if (job.state === 'succeeded') {
            const count = job.result.subtitle_count;
            await refresh(job.result.filename);
            $('resultsStatus').replaceChildren(
                notice('ok', 'Vietnamese subtitles added.', `${count} ${count === 1 ? 'line' : 'lines'} translated from ` +
                    `${job.result.language}. The copy is marked "Vietsub"; the original is unchanged.`),
                ...(job.result.warnings || []).map((warning) => notice('warn', 'Note.', warning)));
            pointOut(job.result.filename);
            return;
        }
        await refresh();  // the original is no longer in use
        $('resultsStatus').replaceChildren(job.state === 'cancelled'
            ? notice('info', 'Cancelled.', 'No subtitled copy was made.')
            : notice('error', 'Could not add subtitles.', job.error || 'Try again in a moment.'));
        $('resultHeading').focus();  // the progress card, and the focus in it, is gone
    }

    function followSubtitleJob(job) {
        setSubtitling(true);
        jobs.follow(job, $('subtitleJobPanel'), {
            title: 'Adding Vietnamese subtitles',
            onFinish: (final) => {
                setSubtitling(false);
                showSubtitleOutcome(final);
            },
        });
    }

    async function addSubtitles(item) {
        if (subtitling) return;
        $('resultsStatus').replaceChildren();
        try {
            followSubtitleJob(await jobs.start('/api/jobs/subtitles', { filename: item.filename }));
            refresh();  // the short is now marked "In use"
        } catch (error) {
            $('resultsStatus').replaceChildren(notice('error', 'Could not start.', error.message));
        }
    }

    // ---- opened for one short (?short=<file name> from Home or Create short) -------------

    function pointOut(filename) {
        const index = matchingShorts().findIndex((item) => item.filename === filename);
        if (index < 0) return;
        if (index >= shown) {
            shown = index + 1;
            render();
        }
        const card = [...$('resultsContent').children].find((entry) => entry.dataset.filename === filename);
        if (!card) return;
        card.scrollIntoView({ behavior: scrollBehavior(), block: 'center' });
        card.querySelector('.short-title').focus({ preventScroll: true });
    }

    async function start() {
        const requested = new URLSearchParams(window.location.search).get('short');
        youtube = await youtubeUpload.status().catch(() => youtube);
        await refresh(requested || null);
        if (requested) pointOut(requested);
        const job = await jobs.latest('subtitles');
        if (!subtitling && job && jobs.isActive(job)) followSubtitleJob(job);
    }

    start();
})();
