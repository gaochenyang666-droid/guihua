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

    function escapeAttr(s) {
        if (s == null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/'/g, '&#39;');
    }

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

    function getBadgeLevel(user) {
        if (!user) return 1;
        if (user.is_admin || user.admin_infinite_level) return 9999;
        var lv = parseInt(user.level, 10);
        if (Number.isFinite(lv) && lv > 0) return lv;
        var label = String(user.level_label || '').trim();
        var m = label.match(/(\d+)/);
        if (m) return parseInt(m[1], 10) || 1;
        return 1;
    }

    function getLevelBadgeStyle(level, isAdmin) {
        if (isAdmin || level >= 9999) {
            return { color: '#facc15', bg: 'rgba(120, 53, 15, 0.26)', glow: 'rgba(250, 204, 21, 0.35)' };
        }
        if (level >= 10) {
            return { color: '#facc15', bg: 'rgba(113, 63, 18, 0.22)', glow: 'rgba(250, 204, 21, 0.28)' };
        }
        if (level >= 8) {
            return { color: '#a78bfa', bg: 'rgba(76, 29, 149, 0.2)', glow: 'rgba(167, 139, 250, 0.24)' };
        }
        if (level >= 5) {
            return { color: '#38bdf8', bg: 'rgba(8, 47, 73, 0.24)', glow: 'rgba(56, 189, 248, 0.24)' };
        }
        if (level >= 3) {
            return { color: '#34d399', bg: 'rgba(6, 78, 59, 0.24)', glow: 'rgba(52, 211, 153, 0.24)' };
        }
        return { color: '#9ca3af', bg: 'rgba(31, 41, 55, 0.26)', glow: 'rgba(156, 163, 175, 0.18)' };
    }

    function getAchievementEmoji(user, level) {
        var equipped = String((user && user.equipped_achievement_key) || '').trim();
        var emojiByAchievement = {
            report_privilege: '🚩',
            wearable_unlock: '🏅',
            co_create_group: '🛰️',
            core_group: '👁️',
            legacy_new_soul: '👻',
            legacy_chain_traveler: '⛓️',
            legacy_wallet_bound: '🔗',
            legacy_dual_identity: '🌓',
            legacy_contract_psychic: '🔮',
            legacy_first_post: '✍️',
            legacy_post_10: '📚',
            legacy_post_100: '🏮',
            legacy_post_1000: '👑',
            legacy_year_1: '🕯️',
            legacy_year_5: '🌙',
            legacy_year_10: '🗝️',
            legacy_admin_guardian: '👺'
        };
        if (equipped && emojiByAchievement[equipped]) return emojiByAchievement[equipped];
        if (user && (user.is_admin || user.admin_infinite_level)) return '👺';
        if (level >= 10) return '👁️';
        if (level >= 8) return '🌌';
        if (level >= 5) return '🛰️';
        if (level >= 3) return '🔮';
        if (level >= 2) return '🕯️';
        return '👻';
    }

    function getAchievementTitle(user) {
        var equipped = String((user && user.equipped_achievement_key) || '').trim();
        var titleMap = {
            report_privilege: '举报权限',
            wearable_unlock: '成就佩戴权限',
            co_create_group: '共创群资格',
            core_group: '核心群资格',
            legacy_new_soul: '新魂',
            legacy_chain_traveler: '链上旅人',
            legacy_wallet_bound: '钱包绑定',
            legacy_dual_identity: '双界行者',
            legacy_contract_psychic: '结契通灵者',
            legacy_first_post: '首帖达成',
            legacy_post_10: '十帖异闻录',
            legacy_post_100: '百帖引魂者',
            legacy_post_1000: '千帖通灵者',
            legacy_year_1: '一年见习者',
            legacy_year_5: '五年夜巡者',
            legacy_year_10: '十年守秘人',
            legacy_admin_guardian: '守夜人'
        };
        if (equipped && titleMap[equipped]) return titleMap[equipped];
        if (user && user.honor_title) return String(user.honor_title);
        if (user && (user.is_admin || user.admin_infinite_level)) return '守夜人';
        return '';
    }

    function getIdentityDescription(user, level, title) {
        if (user && (user.is_admin || user.admin_infinite_level)) {
            return '管理员身份，拥有完整站务权限与全部成就展示。';
        }
        if (title) {
            return '当前展示的是你佩戴中的身份或称号，会覆盖默认等级徽记。';
        }
        if (level >= 10) return '高等级身份，已解锁核心社群资格与更完整的站内身份展示。';
        if (level >= 5) return '中高等级身份，已经进入活跃创作者阶段。';
        if (level >= 3) return '已解锁成就佩戴能力，可在个人页安装墙切换身份。';
        return '初始身份阶段，继续签到、发帖和互动会逐步改变徽记颜色与默认象征。';
    }

    function ensureIdentityBadgeModal() {
        var modal = document.getElementById('identityBadgeModal');
        if (modal) return modal;
        modal = document.createElement('div');
        modal.id = 'identityBadgeModal';
        modal.className = 'modal-overlay';
        modal.innerHTML = '' +
            '<div class="modal glass identity-badge-modal" onclick="event.stopPropagation()">' +
                '<div class="modal-header">' +
                    '<h3>身份铭牌</h3>' +
                    '<button class="modal-close" type="button" id="identityBadgeCloseBtn">&times;</button>' +
                '</div>' +
                '<div id="identityBadgeBody"></div>' +
            '</div>';
        modal.addEventListener('click', function () {
            modal.classList.remove('active');
        });
        document.body.appendChild(modal);
        var closeBtn = document.getElementById('identityBadgeCloseBtn');
        if (closeBtn) {
            closeBtn.addEventListener('click', function () {
                modal.classList.remove('active');
            });
        }
        return modal;
    }

    function openIdentityBadgeFromElement(el) {
        if (!el) return;
        var modal = ensureIdentityBadgeModal();
        var body = document.getElementById('identityBadgeBody');
        if (!modal || !body) return;
        var badgeStyle = '' +
            '--badge-color:' + escapeAttr(el.getAttribute('data-badge-color') || '') + ';' +
            '--badge-bg:' + escapeAttr(el.getAttribute('data-badge-bg') || '') + ';' +
            '--badge-glow:' + escapeAttr(el.getAttribute('data-badge-glow') || '') + ';' +
            'color:' + escapeAttr(el.getAttribute('data-badge-color') || '');
        var badgeText = escapeHtml(el.getAttribute('data-badge-id') || '');
        var emoji = escapeHtml(el.getAttribute('data-badge-emoji') || '👻');
        var levelLabel = escapeHtml(el.getAttribute('data-level-label') || 'Lv.1');
        var title = escapeHtml(el.getAttribute('data-identity-title') || '未佩戴成就');
        var desc = escapeHtml(el.getAttribute('data-identity-desc') || '');
        body.innerHTML = '' +
            '<div class="identity-badge-preview">' +
                '<span class="user-id-badge" style="' + badgeStyle + '">' + emoji + ' ' + badgeText + '</span>' +
            '</div>' +
            '<div class="identity-badge-grid">' +
                '<div class="identity-badge-card"><div class="identity-badge-card-key">等级</div><div class="identity-badge-card-val">' + levelLabel + '</div></div>' +
                '<div class="identity-badge-card"><div class="identity-badge-card-key">当前身份</div><div class="identity-badge-card-val">' + title + '</div></div>' +
            '</div>' +
            '<div class="identity-badge-desc">' + desc + '</div>';
        modal.classList.add('active');
    }

    window.openIdentityBadge = function (el, ev) {
        if (ev) {
            ev.preventDefault();
            ev.stopPropagation();
        }
        openIdentityBadgeFromElement(el);
    };

    window.formatUserId = function (userId, user) {
        var idStr = String(userId);
        if (idStr.length < 10) {
            return '<span class="user-id-badge" style="color:#9ca3af;">💀 ' + window.escapeHtml(idStr) + '</span>';
        }
        var level = getBadgeLevel(user);
        var isAdmin = !!(user && (user.is_admin || user.admin_infinite_level));
        var style = getLevelBadgeStyle(level, isAdmin);
        var emoji = getAchievementEmoji(user, level);
        var title = getAchievementTitle(user) || '未佩戴成就';
        var desc = getIdentityDescription(user, level, getAchievementTitle(user));
        return '<span class="user-id-badge" data-user-card="1" data-badge-id="' + escapeAttr(idStr) + '" data-badge-emoji="' + escapeAttr(emoji) + '" data-badge-color="' + escapeAttr(style.color) + '" data-badge-bg="' + escapeAttr(style.bg) + '" data-badge-glow="' + escapeAttr(style.glow) + '" data-level-label="' + escapeAttr((user && user.level_label) || (isAdmin ? '∞' : ('Lv.' + level))) + '" data-identity-title="' + escapeAttr(title) + '" data-identity-desc="' + escapeAttr(desc) + '" style="--badge-color:' + style.color + '; --badge-bg:' + style.bg + '; --badge-glow:' + style.glow + '; color:' + style.color + '">' + emoji + ' ' + window.escapeHtml(idStr) + '</span>';
    };

    document.addEventListener('click', function (e) {
        var target = e.target;
        if (!target || !target.closest) return;
        var badge = target.closest('.user-id-badge[data-user-card="1"]');
        if (!badge) return;
        e.preventDefault();
        e.stopPropagation();
        openIdentityBadgeFromElement(badge);
    }, true);

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

    var PAGE_TRANSITION_MS = 240;
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
        try {
            if (window.matchMedia) {
                var mq = window.matchMedia('(prefers-reduced-motion: reduce)');
                var syncReduceMotion = function (evt) {
                    var shouldReduce = !!(evt && typeof evt.matches === 'boolean' ? evt.matches : mq.matches);
                    if (!document.body) return;
                    document.body.classList.toggle('reduce-motion', shouldReduce);
                };
                syncReduceMotion(mq);
                if (typeof mq.addEventListener === 'function') mq.addEventListener('change', syncReduceMotion);
                else if (typeof mq.addListener === 'function') mq.addListener(syncReduceMotion);
            }
        } catch (e) {}

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
