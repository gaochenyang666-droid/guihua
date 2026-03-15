(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var root = document.querySelector('.list-page-shell');
    var noticeType = (root && root.getAttribute('data-notice-type')) || 'announcement';
    if (noticeType !== 'activity') noticeType = 'announcement';
    var body = document.getElementById('noticeListBody');
    var apiJson = window.apiJson;

    function renderItems(items) {
        if (!body) return;
        if (!items || !items.length) {
            body.innerHTML = '<div class="list-page-empty">暂无内容</div>';
            return;
        }
        body.innerHTML = items.map(function (a) {
            var dateText = a && a.created_at ? new Date(a.created_at).toLocaleDateString() : '';
            return (
                '<article class="list-item-card glass">' +
                '<div class="list-item-head"><b>' + escapeHtml((a && a.title) || '') + '</b><span>' + escapeHtml(dateText) + '</span></div>' +
                '<div class="list-item-content">' + escapeHtml((a && a.content) || '') + '</div>' +
                '</article>'
            );
        }).join('');
    }

    async function loadNotices() {
        if (!body) return;
        body.textContent = '加载中...';
        try {
            var qs = new URLSearchParams({
                type: noticeType,
                is_active: '1',
                page: '1',
                per_page: '50'
            });
            var result = await apiJson(API_BASE + '/announcements?' + qs.toString(), {
                auth: false,
                fallback: {}
            });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                throw new Error((data && data.error) || '加载失败');
            }
            renderItems((data && data.announcements) || []);
        } catch (e) {
            body.innerHTML = '<div class="list-page-error">' + escapeHtml((e && e.message) || '加载失败') + '</div>';
        }
    }

    window.addEventListener('load', loadNotices);
})();
