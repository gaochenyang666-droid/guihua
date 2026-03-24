(function () {
    'use strict';

    window.GHAdminFactory = function GHAdminFactory(deps) {
        var API_BASE = deps.API_BASE;
        var fetchJsonSafe = deps.fetchJsonSafe;
        var parseJsonSafe = deps.parseJsonSafe;
        var Toast = deps.Toast;
        var Modal = deps.Modal;
        var getSiteNotice = deps.getSiteNotice;
        var getGroupLinks = deps.getGroupLinks;
        var apiJson = window.apiJson;
        var delegatedBound = false;
        var stateCopy = window.STATE_COPY || {};

        function renderErrorState(message) {
            return '<div class="state-error">' + escapeHtml(message || stateCopy.error || '加载失败') + '</div>';
        }

        function renderEmptyState(message) {
            return '<div class="state-empty">' + escapeHtml(message || stateCopy.empty || '暂无内容') + '</div>';
        }

        function renderStatsCard(title, rows) {
            return '<div class="sidebar-card glass admin-stats-card">' +
                '<div class="admin-card-title">' + escapeHtml(title || '') + '</div>' +
                rows.join('') +
            '</div>';
        }

        function renderStatsRow(label, value, extraClass) {
            return '<div class="admin-stats-row">' +
                '<span>' + escapeHtml(label || '') + '</span>' +
                '<span class="' + (extraClass || '') + '">' + value + '</span>' +
            '</div>';
        }

        function renderRedisStatus(redis) {
            redis = redis || {};
            var readinessOk = redis.readiness === 'ready';
            var messageClass = redis.status === 'ok' ? 'admin-text-green' : 'admin-text-orange';
            var readinessClass = readinessOk ? 'admin-text-green' : 'admin-text-orange';
            var recommendation = redis.recommendation
                ? '<div class="admin-item-note admin-item-note-spaced">' + escapeHtml(redis.recommendation) + '</div>'
                : '';
            return '' +
                renderStatsRow('状态', '<span class="' + messageClass + '">' + escapeHtml(redis.message || '未知') + '</span>') +
                renderStatsRow('生产 readiness', '<span class="' + readinessClass + '">' + (readinessOk ? '生产就绪' : '生产待补齐') + '</span>') +
                recommendation;
        }

        function bindDelegatedActions(Admin) {
            if (delegatedBound) return;
            delegatedBound = true;
            document.addEventListener('click', function (e) {
                var target = e.target;
                if (!target || !target.closest) return;
                var btn = target.closest('[data-admin-action]');
                if (!btn) return;
                var action = btn.getAttribute('data-admin-action') || '';
                if (!action) return;
                e.preventDefault();
                if (action === 'resolve-report') {
                    Admin.resolveReport(Number(btn.getAttribute('data-report-id')), btn.getAttribute('data-status'));
                    return;
                }
                if (action === 'toggle-ban') {
                    Admin.toggleBan(Number(btn.getAttribute('data-user-id')), btn.getAttribute('data-is-banned') === 'true');
                    return;
                }
                if (action === 'toggle-announcement') {
                    Admin.toggleAnnouncementActive(Number(btn.getAttribute('data-announcement-id')), btn.getAttribute('data-active') === 'true');
                    return;
                }
                if (action === 'delete-announcement') {
                    Admin.deleteAnnouncement(Number(btn.getAttribute('data-announcement-id')));
                    return;
                }
                if (action === 'filter-pending') {
                    Admin.openPendingPublications();
                    return;
                }
                if (action === 'run-pending-batch') {
                    Admin.runPendingBatchRetry();
                    return;
                }
                if (action === 'retry-pending') {
                    Admin.retryPendingPublication(Number(btn.getAttribute('data-pending-id')));
                    return;
                }
                if (action === 'delete-pending') {
                    Admin.deletePendingPublication(Number(btn.getAttribute('data-pending-id')));
                    return;
                }
                if (action === 'filter-flow-events') {
                    Admin.loadFlowEvents(btn.getAttribute('data-severity') || '');
                }
            }, true);
        }

        var Admin = {
            async confirmHighRisk(actionLabel, options) {
                options = options || {};
                var needsPhrase = options.needsPhrase !== false;
                var phrase = options.phrase || '确认';
                if (needsPhrase) {
                    var answer = prompt(actionLabel + '\n\n请输入「' + phrase + '」继续');
                    if (answer == null) return false;
                    if (String(answer).trim() !== phrase) {
                        Toast.error('确认内容不匹配，已取消操作');
                        return false;
                    }
                    return true;
                }
                return window.confirm(actionLabel);
            },
            async openStats() {
                Modal.open('adminStatsModal');
                var body = document.getElementById('adminStatsBody');
                if (!body) return;
                body.innerHTML = '加载中...';

                try {
                    var result = await fetchJsonSafe(API_BASE + '/admin/stats', {}, { fallback: {}, errorMessage: '加载统计失败' });

                    if (!result.res.ok || result.data.error) throw new Error(result.data.error || '加载失败');

                    body.innerHTML = '' +
                        '<div class="sidebar-card glass admin-stats-card admin-stats-card-wide admin-stats-highlight">' +
                            '<div class="admin-card-title">总营收 (估算)</div>' +
                            '<div class="admin-stats-amount">' + ((result.data.revenue.total_usdt != null ? result.data.revenue.total_usdt : 0).toFixed(2)) + ' USDT</div>' +
                            '<div class="admin-stats-subtext">单篇费用: ' + (result.data.revenue.fee_per_post_usdt != null ? result.data.revenue.fee_per_post_usdt : 0) + ' USDT</div>' +
                        '</div>' +
                        renderStatsCard('用户统计', [
                            renderStatsRow('总用户:', '<b>' + result.data.users.total + '</b>'),
                            renderStatsRow('Web3 (钱包):', '<span class="admin-text-purple">' + result.data.users.web3 + '</span>'),
                            renderStatsRow('Web2 (仅注册):', '<span>' + result.data.users.web2 + '</span>')
                        ]) +
                        renderStatsCard('帖子统计', [
                            renderStatsRow('总帖子:', '<b>' + result.data.posts.total + '</b>'),
                            renderStatsRow('Web3 (永存):', '<span class="admin-text-gold">' + result.data.posts.web3 + '</span>'),
                            renderStatsRow('Web2 (普通):', '<span>' + result.data.posts.web2 + '</span>')
                        ]) +
                        renderStatsCard('运维状态', [
                            renderRedisStatus(result.data.redis)
                        ]);
                } catch (e) {
                    body.innerHTML = renderErrorState('加载失败: ' + (e.message || '未知错误'));
                }
            },

            async openReports() {
                Modal.open('adminReportsModal');
                var body = document.getElementById('adminReportsBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/reports', { check401: false });
                    var list = result.data;
                    if (result.res.status !== 200 || !Array.isArray(list)) {
                        body.innerHTML = renderErrorState(list.error || '加载失败');
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = renderEmptyState('暂无举报');
                        return;
                    }
                    body.innerHTML = list.map(function (r) {
                        var statusClass = r.status === 'pending' ? 'admin-text-red' : (r.status === 'resolved' ? 'admin-text-green' : 'admin-text-muted');
                        var statusText = r.status === 'pending' ? '待处理' : (r.status === 'resolved' ? '已处理' : '已忽略');
                        return '<div class="glass admin-item-card">' +
                            '<div class="admin-item-meta"><span class="admin-text-muted">#' + r.id + '</span> <span class="' + statusClass + '">' + statusText + '</span></div>' +
                            '<div class="admin-item-summary">举报人: ' + escapeHtml(r.reporter_nickname || '') + ' · 被举报: ' + escapeHtml(r.reported_nickname || '') + (r.post_title ? (' · 帖子: ' + escapeHtml(r.post_title)) : '') + '</div>' +
                            '<div class="admin-item-reason">' + escapeHtml(r.reason || '') + '</div>' +
                            (r.admin_notes ? ('<div class="admin-item-note">备注: ' + escapeHtml(r.admin_notes) + '</div>') : '') +
                            (r.status === 'pending' ? '<div class="admin-item-actions"><button class="btn btn-primary btn-sm" type="button" data-admin-action="resolve-report" data-report-id="' + r.id + '" data-status="resolved">已处理</button><button class="btn btn-ghost btn-sm" type="button" data-admin-action="resolve-report" data-report-id="' + r.id + '" data-status="dismissed">忽略</button></div>' : '') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async resolveReport(reportId, status) {
                var actionText = status === 'resolved' ? '将这条举报标记为已处理' : '将这条举报标记为忽略';
                if (!await this.confirmHighRisk(actionText, { phrase: '处理举报' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/reports/' + reportId, {
                        method: 'PUT',
                        body: { status: status },
                        check401: false
                    });
                    if (result.res.ok) {
                        Toast.success(result.data.message || '已更新');
                        this.openReports();
                    } else Toast.error(result.data.error || '操作失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async openUsers() {
                Modal.open('adminUsersModal');
                var body = document.getElementById('adminUsersBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/users', { check401: false });
                    var list = result.data;
                    if (result.res.status !== 200 || !Array.isArray(list)) {
                        body.innerHTML = renderErrorState(list.error || '加载失败');
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = renderEmptyState('暂无用户');
                        return;
                    }
                    body.innerHTML = list.map(function (u) {
                        return '<div class="glass admin-user-card">' +
                            '<div class="admin-user-info"><div class="admin-user-name">' + escapeHtml(u.nickname || u.username || '') + '</div><div class="admin-item-note">ID: ' + u.id + ' · ' + (u.type === 'web3' ? '钱包' : 'Web2') + '</div></div>' +
                            (!u.is_admin ? ('<button class="btn btn-ghost btn-sm admin-danger-action" type="button" data-admin-action="toggle-ban" data-user-id="' + u.id + '" data-is-banned="' + (u.is_banned ? 'true' : 'false') + '">' + (u.is_banned ? '解除封禁' : '封禁') + '</button>') : '<span class="admin-role-badge">管理员</span>') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async toggleBan(userId, currentlyBanned) {
                var actionText = currentlyBanned ? '解除该用户的封禁状态' : '封禁该用户';
                if (!await this.confirmHighRisk(actionText, { phrase: currentlyBanned ? '解除封禁' : '封禁用户' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/users/' + userId + '/ban', {
                        method: 'POST',
                        check401: false
                    });
                    if (result.res.ok) {
                        Toast.success(result.data.message || (currentlyBanned ? '已解除封禁' : '已封禁'));
                        this.openUsers();
                    } else Toast.error(result.data.error || '操作失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async openAnnouncements() {
                Modal.open('adminAnnouncementsModal');
                var body = document.getElementById('adminAnnouncementsBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/announcements', { check401: false });
                    var data = result.data;
                    var list = data.announcements || [];
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    if (!list.length) {
                        body.innerHTML = renderEmptyState('暂无公告');
                        return;
                    }
                    body.innerHTML = list.map(function (a) {
                        return '<div class="glass admin-item-card">' +
                            '<div class="admin-item-header"><b>' + (a.entry_type === 'activity' ? '🎉 ' : '📣 ') + escapeHtml(a.title || '') + '</b><span class="' + (a.is_active ? 'admin-text-green' : 'admin-text-muted') + '">' + (a.is_active ? '生效中' : '未生效') + '</span></div>' +
                            '<div class="admin-item-body">' + escapeHtml(a.content || '') + '</div>' +
                            '<div class="admin-item-note">类型: ' + escapeHtml(a.entry_type || 'announcement') + (a.starts_at ? (' · 开始: ' + new Date(a.starts_at).toLocaleString()) : '') + (a.expires_at ? (' · 结束: ' + new Date(a.expires_at).toLocaleString()) : '') + '</div>' +
                            '<div class="admin-item-actions"><button class="btn btn-ghost btn-sm" type="button" data-admin-action="toggle-announcement" data-announcement-id="' + a.id + '" data-active="' + (a.is_active ? 'false' : 'true') + '">' + (a.is_active ? '停用' : '启用') + '</button><button class="btn btn-ghost btn-sm admin-danger-action" type="button" data-admin-action="delete-announcement" data-announcement-id="' + a.id + '">删除</button></div>' +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async createAnnouncement() {
                var title = prompt('公告标题（120字内）');
                if (!title || !title.trim()) return;
                var content = prompt('公告内容（1000字内）');
                if (!content || !content.trim()) return;
                var entryType = (((prompt('类型：announcement(公告) / activity(活动)', 'announcement') || 'announcement').trim().toLowerCase()) === 'activity') ? 'activity' : 'announcement';
                var level = (prompt('级别：info / warning / critical', 'info') || 'info').trim().toLowerCase();
                var startsAt = (prompt('开始时间（可空，格式 YYYY-MM-DDTHH:mm:ss）', '') || '').trim();
                var expiresAt = (prompt('结束时间（可空，格式 YYYY-MM-DDTHH:mm:ss）', '') || '').trim();
                try {
                    var result = await apiJson(API_BASE + '/admin/announcements', {
                        method: 'POST',
                        body: { title: title.trim(), content: content.trim(), entry_type: entryType, level: level, starts_at: startsAt || null, expires_at: expiresAt || null, activate: true },
                        check401: false
                    });
                    if (result.res.ok) {
                        Toast.success(result.data.message || '已创建');
                        var siteNotice = getSiteNotice();
                        if (siteNotice && typeof siteNotice.load === 'function') siteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(result.data.error || '创建失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async toggleAnnouncementActive(id, isActive) {
                try {
                    var result = await apiJson(API_BASE + '/admin/announcements/' + id, {
                        method: 'PUT',
                        body: { is_active: isActive },
                        check401: false
                    });
                    if (result.res.ok) {
                        Toast.success('状态已更新');
                        var siteNotice = getSiteNotice();
                        if (siteNotice && typeof siteNotice.load === 'function') siteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(result.data.error || '操作失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async deleteAnnouncement(id) {
                if (!await this.confirmHighRisk('删除这条公告', { phrase: '删除公告' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/announcements/' + id, {
                        method: 'DELETE',
                        check401: false
                    });
                    if (result.res.ok) {
                        Toast.success('已删除');
                        var siteNotice = getSiteNotice();
                        if (siteNotice && typeof siteNotice.load === 'function') siteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(result.data.error || '删除失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async openAuditLogs() {
                Modal.open('adminAuditModal');
                var body = document.getElementById('adminAuditBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/audit-logs?limit=200', { check401: false });
                    var data = result.data;
                    var logs = data.logs || [];
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    if (!logs.length) {
                        body.innerHTML = renderEmptyState('暂无日志');
                        return;
                    }
                    body.innerHTML = logs.map(function (l) {
                        return '<div class="admin-log-row">' +
                            '<div class="admin-item-note">' + new Date(l.created_at).toLocaleString() + ' · Admin#' + l.admin_id + '</div>' +
                            '<div class="admin-log-title"><b>' + escapeHtml(l.action || '') + '</b> ' + escapeHtml(l.target_type || '') + '#' + escapeHtml(String(l.target_id || '')) + '</div>' +
                            (l.details ? ('<div class="admin-log-details">' + escapeHtml(l.details) + '</div>') : '') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async openPendingPublications() {
                Modal.open('adminPendingModal');
                var body = document.getElementById('adminPendingBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var statusFilterEl = document.getElementById('adminPendingStatusFilter');
                    var searchFilterEl = document.getElementById('adminPendingSearch');
                    var qs = [];
                    if (statusFilterEl && statusFilterEl.value) qs.push('status=' + encodeURIComponent(statusFilterEl.value));
                    if (searchFilterEl && searchFilterEl.value.trim()) qs.push('q=' + encodeURIComponent(searchFilterEl.value.trim()));
                    var queryString = qs.length ? ('?' + qs.join('&')) : '';
                    var result = await apiJson(API_BASE + '/admin/pending-publications' + queryString, { check401: false, fallback: {} });
                    var data = result.data || {};
                    var items = data.items || [];
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    var toolbar = '' +
                        '<div class="admin-toolbar">' +
                            '<div class="admin-toolbar-group">' +
                                '<select class="form-input admin-filter-select" id="adminPendingStatusFilter">' +
                                    '<option value="">全部状态</option>' +
                                    '<option value="awaiting_retry"' + ((statusFilterEl && statusFilterEl.value === 'awaiting_retry') ? ' selected' : '') + '>awaiting_retry</option>' +
                                    '<option value="storage_ready"' + ((statusFilterEl && statusFilterEl.value === 'storage_ready') ? ' selected' : '') + '>storage_ready</option>' +
                                    '<option value="payment_verified"' + ((statusFilterEl && statusFilterEl.value === 'payment_verified') ? ' selected' : '') + '>payment_verified</option>' +
                                    '<option value="initiated"' + ((statusFilterEl && statusFilterEl.value === 'initiated') ? ' selected' : '') + '>initiated</option>' +
                                '</select>' +
                                '<input class="form-input admin-filter-input" id="adminPendingSearch" type="text" placeholder="搜标题 / TX / 错误" value="' + escapeAttr((searchFilterEl && searchFilterEl.value) || '') + '">' +
                                '<button class="btn btn-ghost btn-sm" type="button" data-admin-action="filter-pending">筛选</button>' +
                            '</div>' +
                            '<button class="btn btn-ghost btn-sm" type="button" data-admin-action="run-pending-batch">运行一轮自动补偿</button>' +
                        '</div>';
                    if (!items.length) {
                        body.innerHTML = toolbar + renderEmptyState('当前没有待恢复发布记录');
                        return;
                    }
                    body.innerHTML = toolbar + items.map(function (row) {
                        var who = escapeHtml(row.nickname || row.username || ('用户#' + row.user_id));
                        var statusClass = row.status === 'awaiting_retry' ? 'admin-text-orange' : (row.status === 'storage_ready' ? 'admin-text-green' : 'admin-text-purple');
                        var jumpLinks = '' +
                            (row.profile_url ? '<a class="btn btn-ghost btn-sm" href="' + escapeAttr(row.profile_url) + '">查看用户</a>' : '') +
                            (row.post_url ? '<a class="btn btn-ghost btn-sm" href="' + escapeAttr(row.post_url) + '">打开帖子</a>' : '');
                        return '<div class="glass admin-item-card admin-pending-card">' +
                            '<div class="admin-item-header">' +
                                '<div><b>' + escapeHtml(row.title || '未命名帖子') + '</b><div class="admin-item-note admin-item-note-spaced">' + who + ' · ' + escapeHtml(row.tx_hash || '') + '</div></div>' +
                                '<span class="' + statusClass + '">' + escapeHtml(row.status || 'pending') + '</span>' +
                            '</div>' +
                            (row.last_error ? ('<div class="admin-log-details admin-log-details-spaced">' + escapeHtml(row.last_error) + '</div>') : '') +
                            '<div class="admin-item-note admin-item-note-spaced">更新时间: ' + (row.updated_at ? new Date(row.updated_at).toLocaleString() : '-') + '</div>' +
                            '<div class="admin-item-actions">' +
                                jumpLinks +
                                '<button class="btn btn-primary btn-sm" type="button" data-admin-action="retry-pending" data-pending-id="' + row.id + '">补偿重试</button>' +
                                '<button class="btn btn-ghost btn-sm admin-danger-action" type="button" data-admin-action="delete-pending" data-pending-id="' + row.id + '">删除记录</button>' +
                            '</div>' +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async runPendingBatchRetry() {
                if (!await this.confirmHighRisk('运行一轮待发布自动补偿', { phrase: '批量补偿' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/pending-publications/retry-batch', {
                        method: 'POST',
                        check401: false,
                        fallback: {}
                    });
                    if (result.res.ok) {
                        var summary = result.data && result.data.result ? result.data.result : {};
                        Toast.success('补偿完成：恢复 ' + (summary.recovered || 0) + '，跳过 ' + (summary.skipped || 0));
                        this.openPendingPublications();
                    } else {
                        Toast.error(result.data.error || '执行补偿失败');
                    }
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async retryPendingPublication(pendingId) {
                if (!await this.confirmHighRisk('对这条待发布记录执行补偿重试', { phrase: '补偿重试' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/pending-publications/' + pendingId + '/retry', {
                        method: 'POST',
                        check401: false,
                        fallback: {}
                    });
                    if (result.res.ok) {
                        Toast.success(result.data.message || '补偿完成');
                        this.openPendingPublications();
                    } else {
                        Toast.error((result.data && (result.data.error || (result.data.pending && result.data.pending.last_error))) || '补偿失败');
                    }
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async deletePendingPublication(pendingId) {
                if (!await this.confirmHighRisk('删除这条待恢复发布记录', { phrase: '删除记录' })) return;
                try {
                    var result = await apiJson(API_BASE + '/admin/pending-publications/' + pendingId, {
                        method: 'DELETE',
                        check401: false,
                        fallback: {}
                    });
                    if (result.res.ok) {
                        Toast.success(result.data.message || '已删除');
                        this.openPendingPublications();
                    } else {
                        Toast.error(result.data.error || '删除失败');
                    }
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async openOpsSummary() {
                Modal.open('adminOpsModal');
                var body = document.getElementById('adminOpsBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/ops/summary', { check401: false, fallback: {} });
                    var data = result.data || {};
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    var alerts = Array.isArray(data.alerts) ? data.alerts : [];
                    var latest = (((data.events || {}).latest) || []);
                    var pending = data.pending || {};
                    var lastHour = (data.events || {}).last_hour || {};
                    var worker = data.worker || {};
                    var redis = data.redis || {};
                    body.innerHTML = '' +
                        '<div class="glass admin-ops-summary-card">' +
                            '<div class="admin-ops-summary-grid">' +
                                '<div><div class="admin-ops-summary-label">待发布总数</div><div class="admin-ops-summary-value">' + escapeHtml(String(pending.total || 0)) + '</div></div>' +
                                '<div><div class="admin-ops-summary-label">最近一小时错误</div><div class="admin-ops-summary-value admin-text-red">' + escapeHtml(String(lastHour.error || 0)) + '</div></div>' +
                                '<div><div class="admin-ops-summary-label">最近一小时警告</div><div class="admin-ops-summary-value admin-text-orange">' + escapeHtml(String(lastHour.warn || 0)) + '</div></div>' +
                                '<div><div class="admin-ops-summary-label">自动补偿</div><div class="admin-ops-worker-status ' + (worker.enabled ? 'admin-text-green' : 'admin-text-muted') + '">' + (worker.enabled ? ('运行中 / ' + escapeHtml(String(worker.interval_seconds || 0)) + 's') : '未启用') + '</div></div>' +
                                '<div><div class="admin-ops-summary-label">Redis / 状态存储</div><div class="admin-ops-worker-status ' + (redis.status === 'ok' ? 'admin-text-green' : 'admin-text-orange') + '">' + escapeHtml(redis.readiness === 'ready' ? '生产就绪' : '生产待补齐') + '</div></div>' +
                            '</div>' +
                            (redis.recommendation ? ('<div class="admin-alert-message admin-item-note-spaced">' + escapeHtml(redis.recommendation) + '</div>') : '') +
                        '</div>' +
                        '<div class="admin-alert-stack">' +
                            alerts.map(function (alert) {
                                var alertClass = alert.severity === 'error' ? 'is-error' : (alert.severity === 'warn' ? 'is-warn' : 'is-ok');
                                return '<div class="glass admin-alert-card ' + alertClass + '">' +
                                    '<div class="admin-alert-title">' + escapeHtml(alert.title || '警告') + '</div>' +
                                    '<div class="admin-alert-message">' + escapeHtml(alert.message || '') + '</div>' +
                                '</div>';
                            }).join('') +
                        '</div>' +
                        '<div class="glass admin-events-card">' +
                            '<div class="admin-events-toolbar">' +
                                '<div class="admin-events-title">最近事件</div>' +
                                '<div class="admin-toolbar-group">' +
                                    '<button class="btn btn-ghost btn-sm" type="button" data-admin-action="filter-flow-events" data-severity="">全部</button>' +
                                    '<button class="btn btn-ghost btn-sm" type="button" data-admin-action="filter-flow-events" data-severity="error">仅错误</button>' +
                                    '<button class="btn btn-ghost btn-sm" type="button" data-admin-action="filter-flow-events" data-severity="warn">仅警告</button>' +
                                '</div>' +
                            '</div>' +
                            '<div id="adminFlowEventsList">' +
                            (latest.length ? latest.map(function (ev) {
                                var payload = ev.payload || {};
                                return '<div class="admin-event-row">' +
                                    '<div class="admin-item-note">' + new Date(ev.created_at).toLocaleString() + ' · ' + escapeHtml(ev.severity || 'info') + '</div>' +
                                    '<div class="admin-log-title">' + escapeHtml(ev.event || '') + '</div>' +
                                    '<div class="admin-log-details">' + escapeHtml(JSON.stringify(payload).slice(0, 220)) + '</div>' +
                                '</div>';
                            }).join('') : renderEmptyState('暂无事件')) +
                            '</div>' +
                        '</div>';
                } catch (e) {
                    body.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async loadFlowEvents(severity) {
                var container = document.getElementById('adminFlowEventsList');
                if (!container) return;
                container.innerHTML = '加载中...';
                try {
                    var qs = severity ? ('?severity=' + encodeURIComponent(severity) + '&limit=80') : '?limit=80';
                    var result = await apiJson(API_BASE + '/admin/flow-events' + qs, { check401: false, fallback: {} });
                    var data = result.data || {};
                    var items = data.items || [];
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    container.innerHTML = items.length ? items.map(function (ev) {
                        var payload = ev.payload || {};
                        return '<div class="admin-event-row">' +
                            '<div class="admin-item-note">' + new Date(ev.created_at).toLocaleString() + ' · ' + escapeHtml(ev.severity || 'info') + '</div>' +
                            '<div class="admin-log-title">' + escapeHtml(ev.event || '') + '</div>' +
                            '<div class="admin-log-details admin-log-details-prewrap">' + escapeHtml(JSON.stringify(payload, null, 2)) + '</div>' +
                        '</div>';
                    }).join('') : renderEmptyState('没有匹配的事件');
                } catch (e) {
                    container.innerHTML = renderErrorState(e.message || '加载失败');
                }
            },

            async editGroupLinks() {
                try {
                    var result = await apiJson(API_BASE + '/admin/group-links', { check401: false });
                    if (!result.res.ok) {
                        var data = result.data || {};
                        Toast.error(data.error || '读取群链接失败');
                        return;
                    }
                    var data = result.data || {};
                    var currentCo = data.co_create_url || '';
                    var currentCore = data.core_url || '';
                    var co = prompt('设置「共创群」Telegram 链接（留空=清空）', currentCo);
                    if (co === null) return;
                    var core = prompt('设置「核心群」Telegram 链接（留空=清空）', currentCore);
                    if (core === null) return;
                    var saveResult = await apiJson(API_BASE + '/admin/group-links', {
                        method: 'PUT',
                        body: {
                            co_create_url: (co || '').trim(),
                            core_url: (core || '').trim()
                        },
                        check401: false
                    });
                    if (!saveResult.res.ok) {
                        Toast.error(saveResult.data.error || '保存失败');
                        return;
                    }
                    Toast.success(saveResult.data.message || '群链接已更新');
                    var groupLinks = getGroupLinks();
                    if (groupLinks && typeof groupLinks.load === 'function') groupLinks.load();
                } catch (_) {
                    Toast.error('网络错误');
                }
            }
        };

        bindDelegatedActions(Admin);
        return Admin;
    };
})();
