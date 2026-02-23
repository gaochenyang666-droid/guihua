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
})();
