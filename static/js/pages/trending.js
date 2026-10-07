(function () {
    'use strict';

    const MAX_RESULTS = '12';
    const MILLION = 1000000;
    const THOUSAND = 1000;
    const $ = (id) => document.getElementById(id);
    let loading = false;
    let reloadWhenDone = false;

    // Video titles, descriptions and channel names come from YouTube and are
    // untrusted. Everything below is built with textContent and addEventListener,
    // never by interpolating data into HTML or inline handlers.
    const { element, notice } = ui;

    function safeHttpsUrl(value) {
        try {
            const url = new URL(value);
            return url.protocol === 'https:' ? url.href : '';
        } catch (error) {
            return '';
        }
    }

    function formatViews(views) {
        const count = parseInt(views, 10);
        if (!Number.isFinite(count)) return 'Views unavailable';
        if (count >= MILLION) return (count / MILLION).toFixed(1) + 'M views';
        if (count >= THOUSAND) return (count / THOUSAND).toFixed(1) + 'K views';
        return count + (count === 1 ? ' view' : ' views');
    }

    function createEntry(video, index) {
        const videoUrl = safeHttpsUrl(video.url);

        const thumbnailUrl = safeHttpsUrl(video.thumbnail);
        const picture = element('div', 'thumb');
        if (thumbnailUrl) {
            const image = element('img');
            image.src = thumbnailUrl;
            image.alt = '';
            image.loading = 'lazy';
            picture.append(image);
        }
        picture.append(element('span', 'chip rank', String(index + 1)));

        // One line of facts: views · length · age · category
        const facts = [formatViews(video.views), video.duration, video.published, video.category]
            .filter(Boolean).map(String).join(' \u00b7 ');

        // Every entry has the same actions; the labels say which video they act on
        const shortButton = element('button', 'btn btn-sm btn-primary', 'Create short');
        shortButton.type = 'button';
        shortButton.setAttribute('aria-label', `Create a short from ${video.title}`);
        shortButton.addEventListener('click', () => openWith('/create-short', videoUrl));
        const extractButton = element('button', 'btn btn-sm', 'Extract frames');
        extractButton.type = 'button';
        extractButton.setAttribute('aria-label', `Extract frames from ${video.title}`);
        extractButton.addEventListener('click', () => openWith('/extract', videoUrl));

        const actions = element('div', 'actions');
        actions.append(shortButton, extractButton);
        if (videoUrl) {
            // "⋯" keeps the three actions on one row; the accessible name says what it is
            actions.append(ui.actionMenu('⋯', `More for ${video.title}`, [
                { label: 'Watch on YouTube', href: videoUrl },
                { label: 'Copy link', onSelect: () => copyLink(videoUrl) },
            ]));
        }

        const entry = element('li', 'card card-flush entry');
        entry.append(picture,
                     element('h3', 'entry-title clamp', video.title),
                     element('p', 'entry-channel', video.channel),
                     element('p', 'entry-desc clamp', video.description),
                     element('p', 'entry-stats', facts), actions);
        return entry;
    }

    async function copyLink(videoUrl) {
        try {
            await navigator.clipboard.writeText(videoUrl);
            showMessage('ok', 'Link copied.', videoUrl);
        } catch (error) {
            showMessage('error', 'Could not copy the link.', videoUrl);
        }
    }

    // A notice, with a "Try again" button when another attempt can help
    function showMessage(kind, lead, text, canRetry) {
        const message = notice(kind, lead, text);
        if (canRetry) {
            const retry = element('button', 'btn btn-sm notice-action', 'Try again');
            retry.type = 'button';
            retry.addEventListener('click', loadTrendingVideos);
            message.append(retry);
        }
        $('trendMessage').replaceChildren(message);
    }

    function clearMessage() {
        $('trendMessage').replaceChildren();
    }

    function selectedText(select) {
        return select.options[select.selectedIndex].textContent;
    }

    function setLoading(isLoading) {
        loading = isLoading;
        $('videosGrid').setAttribute('aria-busy', String(isLoading));
        // aria-disabled, not disabled: a disabled button drops keyboard focus to the page
        $('refreshBtn').setAttribute('aria-disabled', String(isLoading));
        if (!isLoading) {
            $('trendStatus').replaceChildren();
            return;
        }
        $('noResults').hidden = true;
        clearMessage();
        const scanner = element('span', 'mark is-scanning');
        scanner.setAttribute('aria-hidden', 'true');
        $('trendStatus').replaceChildren(scanner, document.createTextNode('Loading trending videos...'));
    }

    function displayVideos(videos) {
        $('videosGrid').replaceChildren(...videos.map(createEntry));
        $('noResults').hidden = videos.length > 0;
    }

    // Says what the list is, so a changed filter is never mistaken for the old list
    function describeList(data, requested) {
        const category = requested.category === '0' ? 'all categories' : requested.categoryText;
        $('chartHeading').textContent = data.sample
            ? 'Sample videos (not live)'
            : `Trending in ${requested.regionText}, ${category}`;
        // The browser's clock, so the time is this computer's
        $('updatedAt').textContent = data.sample ? ''
            : `Updated ${new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })} (your time)`;
    }

    // Why the list is not live (data.reason from the server), and what would fix it
    const SAMPLE_REASONS = {
        no_key: ['No YouTube API key.',
            'These are sample videos. Add YOUTUBE_API_KEY to the .env file (see the README) and restart the app.', false],
        bad_key: ['YouTube refused the API key.',
            'These are sample videos. Check YOUTUBE_API_KEY in the .env file and that the YouTube Data API is ' +
            'enabled for it, then restart the app.', false],
        quota: ["Today's YouTube API quota is used up.",
            'These are sample videos. The quota resets at midnight Pacific time; try again after that.', false],
        unavailable: ['YouTube did not answer.', 'These are sample videos, not what is trending now.', true],
    };

    function explainSample(data) {
        if (!data.sample) return;
        const [lead, text, canRetry] = SAMPLE_REASONS[data.reason] || SAMPLE_REASONS.unavailable;
        showMessage('warn', lead, text, canRetry);
    }

    function loadTrendingVideos() {
        if (loading) {
            reloadWhenDone = true;  // a filter changed mid-load: load again with the new choice
            return;
        }
        setLoading(true);
        // What this request is for, read now: the selects may change before the answer arrives
        const requested = {
            category: $('categorySelect').value,
            categoryText: selectedText($('categorySelect')),
            regionText: selectedText($('regionSelect')),
        };
        const params = new URLSearchParams({
            category: requested.category,
            region: $('regionSelect').value,
            max_results: MAX_RESULTS,
        });

        fetch(`/api/trending?${params.toString()}`)
            .then((response) => {
                if (response.ok) return response.json();
                return response.json().then((errorData) => {
                    throw new Error(errorData.message || errorData.error || `HTTP ${response.status}`);
                });
            })
            .then((data) => {
                setLoading(false);
                displayVideos(data.videos || []);
                describeList(data, requested);
                explainSample(data);
            })
            .catch((error) => {
                console.error('Error loading trending videos:', error);
                setLoading(false);
                // The list on screen is from earlier filters: the heading must not claim otherwise
                $('chartHeading').textContent = 'Trending on YouTube';
                $('updatedAt').textContent = '';
                showMessage('error', 'Could not load trending videos.', error.message || 'Try again in a moment.', true);
            })
            .finally(() => {
                if (!reloadWhenDone) return;
                reloadWhenDone = false;
                loadTrendingVideos();
            });
    }

    // Both pages read ?url= and fill in their link field
    function openWith(path, videoUrl) {
        const target = new URL(path, window.location.origin);
        target.searchParams.set('url', videoUrl);
        window.location.href = target.toString();
    }

    $('queryForm').addEventListener('submit', (event) => event.preventDefault());
    // Reload during a load would only ask YouTube (and spend quota) for the same list again
    $('refreshBtn').addEventListener('click', () => {
        if (!loading) loadTrendingVideos();
    });
    $('categorySelect').addEventListener('change', loadTrendingVideos);
    $('regionSelect').addEventListener('change', loadTrendingVideos);

    $('showAllBtn').addEventListener('click', () => {
        $('categorySelect').value = '0';
        loadTrendingVideos();
    });

    // Loaded once; "Reload" asks again (every request costs YouTube API quota)
    loadTrendingVideos();
})();
