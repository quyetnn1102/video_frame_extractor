(function () {
    'use strict';

    const MAX_RECENT = 6;
    const $ = (id) => document.getElementById(id);

    // Titles come from other sites: everything is built with textContent, never HTML strings.
    const { element, notice, relativeTime } = ui;
    const HINTS = {
        checking: 'Analyzing the link...',
        invalid: 'This link cannot be used: see above.',
        ready: 'Choose what to make from it.',
        unreadable: 'Choose what to make from it.',
    };
    const START_HINT = 'Paste a link from YouTube, TikTok, Instagram, Facebook or Douyin to start.';

    // ---- paste a link; the actions open once it has been analyzed ------------------

    // aria-disabled, not disabled: the buttons stay reachable, and pressing one says what is missing
    function syncButtons(state) {
        const usable = state.status === 'ready' || state.status === 'unreadable';
        ['launchShort', 'launchFrames'].forEach((id) => {
            if (usable) $(id).removeAttribute('aria-disabled');
            else $(id).setAttribute('aria-disabled', 'true');
        });
        $('launchHint').textContent = HINTS[state.status] || START_HINT;
    }

    const source = videoSource.attach({ input: $('launchUrl'), panel: $('launchPreview'), onChange: syncButtons });

    function openTool(path) {
        if (source.isUsable()) {
            window.location.href = path + '?url=' + encodeURIComponent(source.state().url);
        } else if (source.state().status !== 'checking') {
            source.analyze();  // says why the link cannot be used yet (empty, incomplete, invalid)
            $('launchUrl').focus();
        }
    }

    $('launchForm').addEventListener('submit', (event) => {
        event.preventDefault();
        openTool('/create-short');
    });
    $('launchFrames').addEventListener('click', () => openTool('/extract'));

    // ---- recent shorts, from the shorts saved on disk ---------------------------

    function recentCard(item) {
        const thumb = element('div', 'recent-thumb');
        if (typeof item.poster === 'string' && item.poster.startsWith('/shorts/posters/')) {
            // A small still made by the server: far lighter than loading the video itself
            const poster = element('img');
            poster.src = item.poster;
            poster.alt = '';  // the title is right below
            poster.loading = 'lazy';
            thumb.append(poster);
        } else if (typeof item.url === 'string' && item.url.startsWith('/shorts/')) {
            const video = element('video');
            video.preload = 'metadata';
            video.muted = true;
            video.playsInline = true;
            video.src = item.url + '#t=0.1';  // shows the first moment as the cover
            video.setAttribute('aria-hidden', 'true');  // a still inside the link, which has the title
            thumb.append(video);
        }
        thumb.append(element('span', 'tag', 'Short'));
        const length = item.duration > 0 ? ui.formatClock(item.duration) : '';
        if (length) thumb.append(element('span', 'chip', length));

        const body = element('div', 'recent-body');
        body.append(element('p', 'recent-title clamp', item.title), element('p', 'recent-meta', relativeTime(item.created)));

        const card = element('a', 'card card-flush recent-card');
        // Opens this short in Your shorts (shorts.js points it out), not just the list
        card.href = '/shorts?short=' + encodeURIComponent(item.filename);
        card.append(thumb, body);

        const entry = element('li');
        entry.append(card);
        return entry;
    }

    // A failed load is said as such: "No shorts yet" would wrongly suggest they are gone
    function showLoadError() {
        const message = notice('error', 'Could not load your shorts.', 'They are still on disk.');
        const retry = element('button', 'btn btn-sm notice-action', 'Try again');
        retry.type = 'button';
        retry.addEventListener('click', loadRecent);
        message.append(retry);
        $('recentStatus').replaceChildren(message);
    }

    async function loadRecent() {
        $('recentStatus').replaceChildren();
        try {
            const response = await fetch('/api/shorts?limit=' + MAX_RECENT);
            const data = await response.json();
            if (!response.ok || !data.success) throw new Error(data.error || 'Request failed');
            const items = data.shorts.slice(0, MAX_RECENT);
            $('recentShorts').replaceChildren(...items.map(recentCard));
            $('recentEmpty').hidden = items.length > 0;
            $('startSection').hidden = items.length > 0;  // the steps are for a first visit
        } catch (error) {
            console.error('Could not load the recent shorts:', error);
            showLoadError();
        }
    }

    loadRecent();
})();
