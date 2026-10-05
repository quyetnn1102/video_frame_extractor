/* The YouTube sign-in result page: closes the popup once the user has seen the outcome. */
(function () {
    'use strict';

    const CLOSE_AFTER_MS = 2000;
    setTimeout(() => window.close(), CLOSE_AFTER_MS);
})();
