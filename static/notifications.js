(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var body = document.getElementById('notificationsBody');
    var readAllBtn = document.getElementById('readAllBtn');

    var apiJson = window.apiJson;

    function typeText(n) {
        if (!n) return '';
        if (n.type === 'comment') return '评论了你的帖子';
        if (n.type === 'like') return '点赞了你的帖子';
        if (n.type === 'repost') return '转发了你的帖子';
        if (n.type === 'tip') return '给你打赏了';
        if (n.type === 'report_result') return '举报处理结果';
        if (n.type === 'mention') return '提到了你';
        return n.content || '通知';
    }

    function goHomeLogin() {
        if (typeof navigateWithTransition === 'function') navigateWithTransition('/');
        else window.location.href = '/';
    }

    async function markRead(id, postId) {
        try {
            await apiJson(API_BASE + '/notifications/' + id + '/read', {
                method: 'PUT',
                fallback: {}
            });
            if (postId != null) {
                var next = '/post/' + Number(postId);
                if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                else window.location.href = next;
                return;
            }
            await loadNotifications();
        } catch (_) {
            if (window.Toast && Toast.error) Toast.error('操作失败');
        }
    }

    async function markAllRead() {
        try {
            var result = await apiJson(API_BASE + '/notifications/read_all', {
                method: 'PUT',
                fallback: {}
            });
            var res = result.res;
            if (!res.ok) {
                var data = result.data;
                throw new Error((data && data.error) || '操作失败');
            }
            if (window.Toast && Toast.success) Toast.success('已全部标记已读');
            await loadNotifications();
        } catch (e) {
            if (window.Toast && Toast.error) Toast.error((e && e.message) || '操作失败');
        }
    }

    function renderNotifications(items) {
        if (!body) return;
        if (!items || !items.length) {
            body.innerHTML = '<div class="list-page-empty">暂无通知</div>';
            return;
        }
        body.innerHTML = items.map(function (n) {
            var created = n && n.created_at ? new Date(n.created_at).toLocaleString() : '';
            return (
                '<button type="button" class="list-item-card glass notice-item-btn' + (!n.is_read ? ' is-unread' : '') + '" data-id="' + Number(n.id) + '" data-post-id="' + (n.post_id == null ? '' : Number(n.post_id)) + '">' +
                '<div class="list-item-head"><b>' + escapeHtml(((n.sender && n.sender.nickname) || '系统')) + ' ' + escapeHtml(typeText(n)) + '</b><span>' + escapeHtml(created) + '</span></div>' +
                '<div class="list-item-content">' + escapeHtml((n.post_title || n.content || '')) + '</div>' +
                '</button>'
            );
        }).join('');

        Array.prototype.forEach.call(body.querySelectorAll('.notice-item-btn'), function (btn) {
            btn.addEventListener('click', function () {
                var id = Number(btn.getAttribute('data-id'));
                var postRaw = btn.getAttribute('data-post-id');
                var postId = postRaw === '' ? null : Number(postRaw);
                markRead(id, Number.isFinite(postId) ? postId : null);
            });
        });
    }

    async function loadNotifications() {
        if (!body) return;
        if (!(window.authState && window.authState.hasSessionHint && window.authState.hasSessionHint())) {
            body.innerHTML = '<div class="list-page-empty">请先登录后查看通知</div><div style="margin-top:0.8rem;"><button class="btn btn-primary" id="goLoginBtn" type="button">前往首页登录</button></div>';
            var go = document.getElementById('goLoginBtn');
            if (go) go.addEventListener('click', goHomeLogin);
            return;
        }

        body.textContent = '加载中...';
        try {
            var result = await apiJson(API_BASE + '/notifications', {
                fallback: {},
                check401: false
            });
            var res = result.res;
            var data = result.data;
            if (typeof handle401 === 'function' && handle401(res)) return;
            if (!res.ok) {
                throw new Error((data && data.error) || '加载失败');
            }
            renderNotifications((data && data.notifications) || []);
        } catch (e) {
            body.innerHTML = '<div class="list-page-error">' + escapeHtml((e && e.message) || '加载失败') + '</div>';
        }
    }

    window.addEventListener('load', function () {
        if (readAllBtn) readAllBtn.addEventListener('click', markAllRead);
        loadNotifications();
    });
})();
