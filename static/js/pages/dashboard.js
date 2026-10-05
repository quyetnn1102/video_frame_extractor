(function () {
    'use strict';

    const REFRESH_MS = 5000;
    const FIRST_UPDATE_MS = 1000;
    const HIGH_LOAD_PERCENT = 85;
    const $ = (id) => document.getElementById(id);
    const { element } = ui;
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

    // ---- recent requests: rebuilt on every update, times shown as "5 minutes ago" ----

    const MAX_TITLE_LENGTH = 50;
    const MAX_DETAILS_LENGTH = 120;
    const BYTES_PER_MB = 1024 * 1024;

    function shortened(text, length) {
        const value = String(text || '');
        return value.length > length ? value.slice(0, length) + '...' : value;
    }

    function timeCell(isoDate) {
        const time = element('time', undefined, ui.relativeTime(isoDate));
        time.dateTime = isoDate;
        time.title = new Date(isoDate).toLocaleString();
        const cell = element('td', 'when');
        cell.append(time);
        return cell;
    }

    function requestRow(request) {
        const state = element('span', 'state status-' + String(request.status).replace(/[^a-z]/g, ''), request.status);
        const status = element('td');
        status.append(state);
        const row = element('tr');
        row.append(element('td', 'platform', request.platform),
                   element('td', undefined, shortened(request.title, MAX_TITLE_LENGTH)),
                   status,
                   timeCell(request.created_at),
                   element('td', 'when', request.processing_time_ms ? request.processing_time_ms + 'ms' : '-'),
                   element('td', 'details', shortened(request.error, MAX_DETAILS_LENGTH)));
        return row;
    }

    function showRequests(requests) {
        if (!Array.isArray(requests) || requests.length === 0) return;  // keep the empty-state row
        $('requestRows').replaceChildren(...requests.map(requestRow));
    }

    // The first view comes from the server: make its times relative too
    document.querySelectorAll('#requestRows time').forEach((time) => {
        time.title = new Date(time.dateTime).toLocaleString();
        time.textContent = ui.relativeTime(time.dateTime);
    });

    // ---- storage, and deleting old files ----------------------------------------

    function formatSize(bytes) {
        const megabytes = (Number(bytes) || 0) / BYTES_PER_MB;
        return megabytes >= 1024 ? (megabytes / 1024).toFixed(1) + ' GB' : megabytes.toFixed(1) + ' MB';
    }

    function showStorage(storage) {
        [['storageShorts', 'shorts'], ['storageFrames', 'frames'], ['storageDownloads', 'downloads']]
            .forEach(([id, key]) => {
                const bytes = storage ? storage[key] : $(id).dataset.bytes;
                $(id).textContent = formatSize(bytes);
            });
    }

    async function deleteOldFiles() {
        try {
            const { ok, data } = await ui.postJson('/api/cleanup', {});
            $('cleanupStatus').replaceChildren(ok && data.success
                ? ui.notice('ok', 'Done.', data.files_deleted === 1 ? '1 file deleted.' : `${data.files_deleted} files deleted.`)
                : ui.notice('error', 'Could not delete the old files.', data.error || 'Try again in a moment.'));
        } catch (error) {
            $('cleanupStatus').replaceChildren(ui.notice('error', 'Could not delete the old files.', 'The app did not answer.'));
        }
        updateDashboard();
    }

    // Shorts are deleted too and cannot be brought back, so this asks first
    function confirmCleanup() {
        const hours = $('cleanupBtn').dataset.hours;
        const dialog = element('dialog', 'dialog');
        dialog.setAttribute('aria-labelledby', 'cleanupHeading');
        dialog.addEventListener('close', () => dialog.remove());
        const heading = element('h2', undefined, 'Delete old files?');
        heading.id = 'cleanupHeading';
        const note = element('p', undefined,
            `Shorts, frames and downloads older than ${hours} hours are deleted from this computer. This cannot be undone.`);
        const remove = element('button', 'btn btn-danger', 'Delete old files');
        remove.type = 'button';
        remove.addEventListener('click', () => {
            dialog.close();
            ui.whileWorking($('cleanupBtn'), 'Deleting...', deleteOldFiles);
        });
        const keep = element('button', 'btn', 'Keep them');
        keep.type = 'button';
        keep.addEventListener('click', () => dialog.close());
        const actions = element('div', 'actions');
        actions.append(remove, keep);
        dialog.append(heading, note, actions);
        document.body.append(dialog);
        dialog.showModal();
        keep.focus();  // the safe choice is the default
    }

    $('cleanupBtn').addEventListener('click', confirmCleanup);

    showStorage(null);

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
                showRequests(data.recent_requests);
                if (data.storage) showStorage(data.storage);
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

    // Not while the tab is in the background: nobody is looking, and it keeps the CPU meter honest
    function updateIfVisible() {
        if (!document.hidden) updateDashboard();
    }

    // Auto refresh toggle
    $('autoRefresh').addEventListener('change', function () {
        clearInterval(refreshInterval);
        if (this.checked) {
            refreshInterval = setInterval(updateIfVisible, REFRESH_MS);
        }
    });

    // Start auto refresh by default, with a first update shortly after load
    refreshInterval = setInterval(updateIfVisible, REFRESH_MS);
    setTimeout(updateDashboard, FIRST_UPDATE_MS);
})();
