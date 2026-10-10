(function () {
    'use strict';

    window.GHHomeNoticesFactory = function GHHomeNoticesFactory(deps) {
        var API_BASE = deps.API_BASE;
        var getCurrentUser = deps.getCurrentUser;
        var fetchJsonSafe = deps.fetchJsonSafe;
        var Modal = deps.Modal;
        var navigateWithTransition = deps.navigateWithTransition;
        var apiJson = window.apiJson;
        var notificationDelegated = false;

        function bindNotificationDelegation(Notification) {
            if (notificationDelegated) return;
            notificationDelegated = true;
            document.addEventListener('click', function (e) {
                var target = e.target;
                if (!target || !target.closest) return;
                var row = target.closest('[data-notification-id]');
                if (!row) return;
                e.preventDefault();
                var notificationId = Number(row.getAttribute('data-notification-id'));
                var postIdRaw = row.getAttribute('data-notification-post-id');
                var postId = postIdRaw === '' || postIdRaw == null ? null : Number(postIdRaw);
                Notification.read(notificationId, Number.isFinite(postId) ? postId : null);
            }, true);
        }

        var Notification = {
            async load() {
                if (!getCurrentUser()) return;
                var result = await fetchJsonSafe(API_BASE + '/notifications', {}, { fallback: {}, checkUnauthorized: true, errorMessage: '加载通知失败' });
                if (!result.res.ok) return;

                var list = document.getElementById('notificationList');
                if (!list) return;
                if (result.data.notifications && result.data.notifications.length > 0) {
                    var badgeEl = document.getElementById('notifBadge');
                    if (badgeEl) badgeEl.hidden = !result.data.notifications.some(function (n) { return !n.is_read; });
                    var typeText = function (n) {
                        if (n && n.content) return n.content;
                        if (!n) return '有新动态';
                        if (n.type === 'like') return '点赞了你的帖子';
                        if (n.type === 'reply') return '回复了你的评论';
                        if (n.type === 'comment') return '评论了你的帖子';
                        if (n.type === 'mention') return '提到了你';
                        if (n.type === 'report_result') return '你的举报有了处理结果';
                        if (n.type === 'tip') return '打赏了你的帖子';
                        return '有新动态';
                    };
                    list.innerHTML = result.data.notifications.map(function (n) {
                        return '<div class="home-notice-item' + (!n.is_read ? ' is-unread' : '') + '" data-notification-id="' + n.id + '" data-notification-post-id="' + (n.post_id != null ? n.post_id : '') + '">' +
                            '<div class="home-notice-title"><b>' + escapeHtml((n.sender && n.sender.nickname) || '系统') + '</b> ' + escapeHtml(typeText(n)) + '</div>' +
                            '<div class="home-notice-post">' + escapeHtml(n.post_title || '') + '</div>' +
                            '<div class="home-notice-time">' + new Date(n.created_at).toLocaleString() + '</div>' +
                        '</div>';
                    }).join('');
                } else {
                    list.innerHTML = '<div class="list-page-empty">暂无消息</div>';
                    var badge = document.getElementById('notifBadge');
                    if (badge) badge.hidden = true;
                }
            },

            async read(id, postId) {
                await apiJson(API_BASE + '/notifications/' + id + '/read', {
                    method: 'PUT',
                    check401: false
                });
                this.load();
                if (postId != null && postId !== undefined) Modal.openDetail(postId);
            },

            async readAll() {
                await apiJson(API_BASE + '/notifications/read_all', {
                    method: 'PUT',
                    check401: false
                });
                this.load();
            }
        };

        var SiteNotice = {
            async load() {
                try {
                    var result = await apiJson(API_BASE + '/announcements/active', { auth: false, fallback: {} });
                    var res = result.res;
                    var data = result.data;
                    var bar = document.getElementById('siteAnnouncementBar');
                    var titleEl = document.getElementById('siteAnnouncementTitle');
                    var contentEl = document.getElementById('siteAnnouncementContent');
                    if (!bar || !titleEl || !contentEl) return;
                    var ann = data && data.announcement;
                    if (!res.ok || !ann) {
                        bar.hidden = true;
                        bar.onclick = null;
                        bar.style.cursor = '';
                        return;
                    }
                    var levelMap = { info: '📣 公告', warning: '⚠️ 提醒', critical: '🚨 紧急' };
                    var levelClassMap = { info: 'is-info', warning: 'is-warning', critical: 'is-critical' };
                    bar.classList.remove('is-info', 'is-warning', 'is-critical');
                    bar.classList.add(levelClassMap[ann.level] || 'is-info');
                    titleEl.textContent = levelMap[ann.level] || '📣 公告';
                    contentEl.textContent = ann.title + '：' + ann.content;
                    bar.style.cursor = 'pointer';
                    bar.onclick = function () {
                        var t = ann.entry_type === 'activity' ? 'activity' : 'announcement';
                        var next = '/notices?type=' + encodeURIComponent(t);
                        if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                        else window.location.href = next;
                    };
                    bar.hidden = false;
                } catch (_) {}
            }
        };

        var NoticeCenter = {
            async open(type) {
                var safeType = type === 'activity' ? 'activity' : 'announcement';
                var next = '/notices?type=' + encodeURIComponent(safeType);
                if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                else window.location.href = next;
            }
        };

        bindNotificationDelegation(Notification);

        return {
            Notification: Notification,
            SiteNotice: SiteNotice,
            NoticeCenter: NoticeCenter
        };
    };
})();
