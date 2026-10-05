(function () {
    'use strict';

    const MAX_RECENT = 4;
    const SECONDS_PER_MINUTE = 60;
    const $ = (id) => document.getElementById(id);

    // Titles come from other sites: everything is built with textContent, never HTML strings.
    const { element, relativeTime, isLink } = ui;

    // ---- paste a link, then choose what to do with it --------------------------

    function syncButtons() {
        const ready = isLink($('launchUrl').value.trim());
        $('launchShort').disabled = !ready;
        $('launchFrames').disabled = !ready;
    }

    function openTool(path) {
        const url = $('launchUrl').value.trim();
        if (!isLink(url)) return;
        window.location.href = path + '?url=' + encodeURIComponent(url);
    }

    $('launchUrl').addEventListener('input', syncButtons);
    $('launchForm').addEventListener('submit', (event) => {
        event.preventDefault();
        openTool('/create-short');
    });
    $('launchFrames').addEventListener('click', () => openTool('/extract'));
    window.attachLinkPreview($('launchUrl'), $('launchPreview'));
    syncButtons();

    // ---- recent shorts, from the shorts saved on disk ---------------------------

    function formatLength(totalSeconds) {
        const seconds = Math.round(Number(totalSeconds));
        if (!Number.isFinite(seconds) || seconds <= 0) return '';
        return `${Math.floor(seconds / SECONDS_PER_MINUTE)}:${String(seconds % SECONDS_PER_MINUTE).padStart(2, '0')}`;
    }

    function recentCard(item) {
        const thumb = element('div', 'recent-thumb');
        if (typeof item.url === 'string' && item.url.startsWith('/shorts/')) {
            const video = element('video');
            video.preload = 'metadata';
            video.muted = true;
            video.playsInline = true;
            video.src = item.url + '#t=0.1';  // shows the first moment as the cover
            thumb.append(video);
        }
        thumb.append(element('span', 'tag', 'Short'));
        const length = formatLength(item.duration);
        if (length) thumb.append(element('span', 'chip', length));

        const body = element('div', 'recent-body');
        body.append(element('p', 'recent-title clamp', item.title), element('p', 'recent-meta', relativeTime(item.created)));

        const card = element('a', 'card card-flush recent-card');
        card.href = '/create-short#resultsSection';
        card.append(thumb, body);

        const entry = element('li');
        entry.append(card);
        return entry;
    }

    async function loadRecent() {
        try {
            const response = await fetch('/api/shorts');
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');
            const items = data.shorts.slice(0, MAX_RECENT);
            $('recentShorts').replaceChildren(...items.map(recentCard));
            $('recentEmpty').hidden = items.length > 0;
        } catch (error) {
            console.error('Could not load the recent shorts:', error);
            $('recentEmpty').hidden = false;
        }
    }

    loadRecent();
})();
