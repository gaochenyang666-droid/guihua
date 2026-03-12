/**
 * 公共脚本：escapeHtml、formatUserId、handle401，供 index/studio/profile 共用
 */
(function () {
    'use strict';

    window.escapeHtml = function (s) {
        if (s == null || s === undefined) return '';
        var str = String(s);
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    window.handle401 = function (res) {
        if (res && res.status === 401) {
            try { localStorage.removeItem('token'); } catch (e) {}
            try { localStorage.removeItem('login_at'); } catch (e) {}
            if (typeof window.currentUser !== 'undefined') window.currentUser = null;
            window.location.href = '/';
            return true;
        }
        return false;
    };

    window.formatUserId = function (userId) {
        var idStr = String(userId);
        if (idStr.length < 10) {
            return '<span class="user-id-badge" style="color:#9ca3af;">💀 ' + window.escapeHtml(idStr) + '</span>';
        }
        var year = idStr.substring(0, 4);
        var type = idStr.substring(4, 5);
        var yearColors = { '2025': { color: '#FF00FF', emoji: '🕯️' }, '2026': { color: '#00FFCC', emoji: '👻' } };
        var typeConfigs = { '1': { color: '#A855F7', emoji: '🔮' }, '9': { color: '#FFD700', emoji: '👁️' } };
        var res = typeConfigs[type] || yearColors[year] || { color: '#FFFFFF', emoji: '💀' };
        return '<span class="user-id-badge" style="color:' + res.color + '">' + res.emoji + ' ' + window.escapeHtml(idStr) + '</span>';
    };

    window.openLoginPage = function (nextPath) {
        var fallback = '/';
        var target = (typeof nextPath === 'string' && nextPath.trim()) ? nextPath.trim() : (window.location.pathname + window.location.search + window.location.hash);
        var safeTarget = fallback;
        try {
            var parsed = new URL(target, window.location.origin);
            if (parsed.origin === window.location.origin) {
                safeTarget = (parsed.pathname || '/') + (parsed.search || '') + (parsed.hash || '');
            }
        } catch (e) {}
        var loginUrl = '/login?next=' + encodeURIComponent(safeTarget);
        if (typeof window.navigateWithTransition === 'function') {
            window.navigateWithTransition(loginUrl);
        } else {
            window.location.href = loginUrl;
        }
    };

    var PAGE_TRANSITION_MS = 260;
    var isNavigating = false;
    var PAGE_STATE_INIT_KEY = 'pageStateInit';

    function resetPageVisualState() {
        var body = document.body;
        if (!body) return;
        body.classList.remove('page-leaving');
        body.classList.add('page-motion');
        body.classList.add('page-ready');
        isNavigating = false;
    }

    window.navigateWithTransition = function (url) {
        if (!url || isNavigating) {
            return;
        }
        isNavigating = true;
        var body = document.body;
        if (!body || body.classList.contains('reduce-motion')) {
            window.location.href = url;
            return;
        }
        body.classList.add('page-motion', 'page-leaving');
        body.classList.remove('page-ready');
        window.setTimeout(function () {
            window.location.href = url;
        }, PAGE_TRANSITION_MS);
    };

    function setupPageTransitions() {
        var body = document.body;
        if (!body) return;
        if (body.dataset[PAGE_STATE_INIT_KEY] === '1') {
            resetPageVisualState();
            return;
        }
        body.dataset[PAGE_STATE_INIT_KEY] = '1';
        try {
            if (window.history && 'scrollRestoration' in window.history) {
                // Allow browser-native restoration; do not force global scroll-to-top.
                window.history.scrollRestoration = 'auto';
            }
        } catch (e) {}
        if (!body.classList.contains('reduce-motion')) {
            body.classList.add('page-motion');
            window.requestAnimationFrame(function () {
                body.classList.add('page-ready');
            });
        }

        document.addEventListener('click', function (e) {
            if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
            var target = e.target;
            if (!target || !target.closest) return;
            var anchor = target.closest('a[href]');
            if (!anchor) return;
            if (anchor.hasAttribute('download')) return;
            if (anchor.target && anchor.target !== '_self') return;
            if (anchor.getAttribute('data-no-transition') === '1') return;
            var href = anchor.getAttribute('href') || '';
            if (!href || href.charAt(0) === '#') return;
            if (href.indexOf('javascript:') === 0) return;
            var targetUrl;
            try {
                targetUrl = new URL(anchor.href, window.location.href);
            } catch (err) {
                return;
            }
            if (targetUrl.origin !== window.location.origin) return;
            if (targetUrl.href === window.location.href) return;
            e.preventDefault();
            window.navigateWithTransition(targetUrl.href);
        }, true);
    }

    window.addEventListener('pageshow', function () {
        resetPageVisualState();
    });

    window.addEventListener('popstate', function () {
        resetPageVisualState();
    });

    window.addEventListener('load', function () {
        resetPageVisualState();
    });

    // Ignore known wallet-extension noise that appears as unhandled rejection in page console.
    window.addEventListener('unhandledrejection', function (evt) {
        try {
            var reason = evt && evt.reason;
            var message = String((reason && reason.message) || reason || '');
            var stack = String((reason && reason.stack) || '');
            if (/Origin not allowed/i.test(message) && /inpage\.js/i.test(stack)) {
                evt.preventDefault();
            }
        } catch (e) {}
    });

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', setupPageTransitions);
    } else {
        setupPageTransitions();
    }
})();
