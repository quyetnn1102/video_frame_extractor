(function () {
    'use strict';

    const REFRESH_MS = 5000;
    const FIRST_UPDATE_MS = 1000;
    const HIGH_LOAD_PERCENT = 85;
    const $ = (id) => document.getElementById(id);
    let refreshInterval;

    // The server renders bar lengths as data-width (percent); style attributes are blocked by the CSP
    document.querySelectorAll('[data-width]').forEach((bar) => {
        bar.style.width = (Number(bar.dataset.width) || 0) + '%';
    });

    function setMeter(name, percent) {
        const value = Number(percent) || 0;
        const isHigh = value >= HIGH_LOAD_PERCENT;
        $(name + 'Percent').textContent = value.toFixed(1) + '%' + (isHigh ? ' (high)' : '');
        $(name + 'Meter').setAttribute('aria-valuenow', value.toFixed(1));
        const bar = $(name + 'ProgressBar');
        bar.style.width = value.toFixed(1) + '%';
        bar.classList.toggle('is-high', isHigh);
    }

    function platformRow(platform, count, busiest) {
        const name = document.createElement('span');
        name.className = 'name';
        name.textContent = platform;

        const fill = document.createElement('span');
        fill.className = 'fill';
        fill.style.width = (count / busiest * 100).toFixed(1) + '%';
        const track = document.createElement('span');
        track.className = 'track';
        track.append(fill);

        const total = document.createElement('span');
        total.className = 'count';
        total.textContent = count;

        const row = document.createElement('li');
        row.append(name, track, total);
        return row;
    }

    function showPlatforms(stats) {
        const entries = Object.entries(stats || {});
        if (entries.length === 0) {
            const empty = document.createElement('li');
            empty.className = 'muted';
            empty.textContent = 'No requests yet.';
            $('platformStats').replaceChildren(empty);
            return;
        }
        const busiest = Math.max(1, ...entries.map(([, count]) => Number(count) || 0));
        $('platformStats').replaceChildren(...entries.map(([platform, count]) => platformRow(platform, Number(count) || 0, busiest)));
    }

    function updateDashboard() {
        fetch('/api/dashboard-data')
            .then((response) => {
                if (!response.ok) throw new Error('HTTP ' + response.status);
                return response.json();
            })
            .then((data) => {
                if (data.analytics) {
                    $('totalRequests').textContent = data.analytics.total_requests || 0;
                    $('successRate').textContent = (data.analytics.success_rate || 0).toFixed(1) + '%';
                    $('recentRequests').textContent = data.analytics.recent_requests_24h || 0;
                    $('totalFrames').textContent = data.analytics.total_frames_extracted || 0;
                    $('avgProcessingTime').textContent = Math.round(data.analytics.avg_processing_time_ms || 0) + 'ms';
                    showPlatforms(data.analytics.platform_stats);
                }

                if (data.system_info) {
                    setMeter('cpu', data.system_info.cpu_percent);
                    setMeter('memory', data.system_info.memory_percent);
                    setMeter('disk', data.system_info.disk_usage);
                }
                $('lastUpdated').textContent = 'Updated at ' + new Date().toLocaleTimeString() + '.';
                $('refreshAlert').textContent = '';
            })
            .catch((error) => {
                console.error('Error updating dashboard:', error);
                const message = 'Could not update. Trying again in a few seconds.';
                $('lastUpdated').textContent = message;
                // Set once per outage, so the failure is announced but not repeated every 5 s
                if ($('refreshAlert').textContent !== message) $('refreshAlert').textContent = message;
            });
    }

    // Auto refresh toggle
    $('autoRefresh').addEventListener('change', function () {
        clearInterval(refreshInterval);
        if (this.checked) {
            refreshInterval = setInterval(updateDashboard, REFRESH_MS);
        }
    });

    // Start auto refresh by default, with a first update shortly after load
    refreshInterval = setInterval(updateDashboard, REFRESH_MS);
    setTimeout(updateDashboard, FIRST_UPDATE_MS);
})();
