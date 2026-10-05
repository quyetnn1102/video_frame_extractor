/* App shell: remembers whether the sidebar is collapsed, and runs the drawer on small screens. */
(function () {
    'use strict';

    const STORAGE_KEY = 'videoextract.sidebar';
    const COLLAPSED = 'collapsed';
    const root = document.documentElement;

    // Applied while the page is still loading, so the sidebar never flashes open
    try {
        if (localStorage.getItem(STORAGE_KEY) === COLLAPSED) root.classList.add('sidebar-collapsed');
    } catch (error) {
        // storage can be blocked; the sidebar then simply starts open
    }

    document.addEventListener('DOMContentLoaded', () => {
        const toggle = document.getElementById('sideToggle');
        const menuButton = document.getElementById('menuButton');
        const scrim = document.getElementById('scrim');

        function syncToggle() {
            const collapsed = root.classList.contains('sidebar-collapsed');
            toggle.setAttribute('aria-expanded', String(!collapsed));
            toggle.setAttribute('aria-label', collapsed ? 'Expand the sidebar' : 'Collapse the sidebar');
        }

        function setMenu(open) {
            root.classList.toggle('menu-open', open);
            menuButton.setAttribute('aria-expanded', String(open));
        }

        toggle.addEventListener('click', () => {
            const collapsed = root.classList.toggle('sidebar-collapsed');
            try {
                if (collapsed) localStorage.setItem(STORAGE_KEY, COLLAPSED);
                else localStorage.removeItem(STORAGE_KEY);
            } catch (error) {
                // the choice still applies for this visit
            }
            syncToggle();
        });

        menuButton.addEventListener('click', () => setMenu(!root.classList.contains('menu-open')));
        scrim.addEventListener('click', () => setMenu(false));
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape') setMenu(false);
        });
        document.querySelectorAll('#sidebar a').forEach((link) => link.addEventListener('click', () => setMenu(false)));

        syncToggle();
    });
})();
