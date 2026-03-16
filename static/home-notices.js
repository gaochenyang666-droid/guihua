(function () {
    'use strict';

    window.GHHomeNoticesFactory = function GHHomeNoticesFactory(deps) {
        var API_BASE = deps.API_BASE;
        var getCurrentUser = deps.getCurrentUser;
        var fetchJsonSafe = deps.fetchJsonSafe;
        var Modal = deps.Modal;
        var navigateWithTransition = deps.navigateWithTransition;
        var apiJson = window.apiJson;

        var Notification = {
            async load() {
                if (!getCurrentUser()) return;
                var result = await fetchJsonSafe(API_BASE + '/notifications', {}, { fallback: {}, checkUnauthorized: true, errorMessage: '加载通知失败' });
                if (!result.res.ok) return;

                var list = document.getElementById('notificationList');
                if (!list) return;
                if (result.data.notifications && result.data.notifications.length > 0) {
                    var badgeEl = document.getElementById('notifBadge');
                    if (badgeEl) badgeEl.style.display = result.data.notifications.some(function (n) { return !n.is_read; }) ? 'block' : 'none';
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
                        return '<div style="padding:0.8rem; border-bottom:1px solid var(--border-color); ' + (!n.is_read ? 'background:rgba(124,58,237,0.1);' : '') + ' cursor:pointer;" onclick="Notification.read(' + n.id + ', ' + (n.post_id != null ? n.post_id : 'null') + ')">' +
                            '<div style="font-size:0.9rem; margin-bottom:0.2rem;"><b>' + escapeHtml((n.sender && n.sender.nickname) || '系统') + '</b> ' + escapeHtml(typeText(n)) + '</div>' +
                            '<div style="font-size:0.8rem; color:var(--text-muted);">' + escapeHtml(n.post_title || '') + '</div>' +
                            '<div style="font-size:0.7rem; color:var(--text-secondary); margin-top:0.3rem;">' + new Date(n.created_at).toLocaleString() + '</div>' +
                        '</div>';
                    }).join('');
                } else {
                    list.innerHTML = '<div style="padding:1rem; text-align:center; color:var(--text-muted);">暂无消息</div>';
                    var badge = document.getElementById('notifBadge');
                    if (badge) badge.style.display = 'none';
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

        return {
            Notification: Notification,
            SiteNotice: SiteNotice,
            NoticeCenter: NoticeCenter
        };
    };
})();
