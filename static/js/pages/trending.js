(function () {
    'use strict';

    const SUPPORTED_PLATFORMS = ['youtube'];
    const MAX_RESULTS = '12';
    const AUTO_REFRESH_MS = 300000;
    const MILLION = 1000000;
    const THOUSAND = 1000;
    const $ = (id) => document.getElementById(id);

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

    function statItem(text, className) {
        const wrapper = element('span');
        wrapper.append(element(className ? 'strong' : 'span', className, text));
        return wrapper;
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

        const stats = element('div', 'entry-stats');
        stats.append(statItem(formatViews(video.views), 'views'),
                     statItem(String(video.duration)),
                     statItem(String(video.published)),
                     statItem(String(video.category)));

        // Every entry has the same actions; the labels say which video they act on
        const extractButton = element('button', 'btn', 'Extract frames');
        extractButton.type = 'button';
        extractButton.setAttribute('aria-label', `Extract frames from ${video.title}`);
        extractButton.addEventListener('click', () => extractFromVideo(videoUrl));

        const actions = element('div', 'actions');
        actions.append(extractButton);
        if (videoUrl) {
            const watch = element('a', undefined, 'Watch on YouTube');
            watch.setAttribute('aria-label', `Watch ${video.title} on YouTube (opens a new tab)`);
            watch.href = videoUrl;
            watch.target = '_blank';
            watch.rel = 'noopener noreferrer';
            actions.append(watch);
        }

        const entry = element('li', index === 0 ? 'card card-flush entry is-lead' : 'card card-flush entry');
        entry.append(picture,
                     element('h2', 'entry-title clamp', video.title),
                     element('p', 'entry-channel', video.channel),
                     element('p', 'entry-desc clamp', video.description),
                     stats, actions);
        return entry;
    }

    function showMessage(kind, lead, text) {
        $('trendMessage').replaceChildren(notice(kind, lead, text));
    }

    function clearMessage() {
        $('trendMessage').replaceChildren();
    }

    function setLoading(isLoading) {
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

    function loadTrendingVideos() {
        const platform = $('platformSelect').value;
        if (!SUPPORTED_PLATFORMS.includes(platform)) {
            showMessage('warn', 'Not available yet.', `${platform} is not supported. Only YouTube is available.`);
            return;
        }

        setLoading(true);
        const params = new URLSearchParams({
            platform: platform,
            category: $('categorySelect').value,
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
            })
            .catch((error) => {
                console.error('Error loading trending videos:', error);
                setLoading(false);
                showMessage('error', 'Could not load trending videos.', error.message || 'Try again in a moment.');
            });
    }

    function extractFromVideo(videoUrl) {
        // The Extract frames page reads ?url= and fills in its link field
        const mainPageUrl = new URL('/extract', window.location.origin);
        mainPageUrl.searchParams.set('url', videoUrl);
        window.location.href = mainPageUrl.toString();
    }

    $('queryForm').addEventListener('submit', (event) => {
        event.preventDefault();
        if ($('refreshBtn').getAttribute('aria-disabled') === 'true') return;  // already loading
        loadTrendingVideos();
    });

    $('platformSelect').addEventListener('change', () => {
        if (SUPPORTED_PLATFORMS.includes($('platformSelect').value)) return;
        // A disabled option should not be selectable; switch back if it somehow is
        $('platformSelect').value = SUPPORTED_PLATFORMS[0];
        showMessage('warn', 'Not available yet.', 'That platform is not supported. Switched back to YouTube.');
    });

    $('showAllBtn').addEventListener('click', () => {
        $('categorySelect').value = '0';
        loadTrendingVideos();
    });

    loadTrendingVideos();

    // Auto-refresh, but not in a background tab (each refresh costs API quota)
    setInterval(() => {
        if (!document.hidden) loadTrendingVideos();
    }, AUTO_REFRESH_MS);
})();
