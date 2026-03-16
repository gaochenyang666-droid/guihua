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

        return {
            async openStats() {
                Modal.open('adminStatsModal');
                var body = document.getElementById('adminStatsBody');
                if (!body) return;
                body.innerHTML = '加载中...';

                try {
                    var result = await fetchJsonSafe(API_BASE + '/admin/stats', {
                        headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') }
                    }, { fallback: {}, errorMessage: '加载统计失败' });

                    if (!result.res.ok || result.data.error) throw new Error(result.data.error || '加载失败');

                    body.innerHTML = '' +
                        '<div class="sidebar-card glass" style="grid-column: span 2; text-align: center;">' +
                            '<div style="font-size: 0.9rem; color: var(--text-secondary);">总营收 (估算)</div>' +
                            '<div style="font-size: 2rem; font-weight: bold; color: var(--accent-gold);">' + ((result.data.revenue.total_usdt != null ? result.data.revenue.total_usdt : 0).toFixed(2)) + ' USDT</div>' +
                            '<div style="font-size: 0.8rem; color: var(--text-muted);">单篇费用: ' + (result.data.revenue.fee_per_post_usdt != null ? result.data.revenue.fee_per_post_usdt : 0) + ' USDT</div>' +
                        '</div>' +
                        '<div class="sidebar-card glass">' +
                            '<div style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 0.5rem;">用户统计</div>' +
                            '<div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;"><span>总用户:</span> <b>' + result.data.users.total + '</b></div>' +
                            '<div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;"><span>Web3 (钱包):</span> <span style="color: var(--accent-purple);">' + result.data.users.web3 + '</span></div>' +
                            '<div style="display: flex; justify-content: space-between;"><span>Web2 (仅注册):</span> <span>' + result.data.users.web2 + '</span></div>' +
                        '</div>' +
                        '<div class="sidebar-card glass">' +
                            '<div style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 0.5rem;">帖子统计</div>' +
                            '<div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;"><span>总帖子:</span> <b>' + result.data.posts.total + '</b></div>' +
                            '<div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;"><span>Web3 (永存):</span> <span style="color: var(--accent-gold);">' + result.data.posts.web3 + '</span></div>' +
                            '<div style="display: flex; justify-content: space-between;"><span>Web2 (普通):</span> <span>' + result.data.posts.web2 + '</span></div>' +
                        '</div>';
                } catch (e) {
                    body.innerHTML = '<div style="color: var(--accent-red);">加载失败: ' + escapeHtml(e.message || '未知错误') + '</div>';
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
                        body.innerHTML = '<div style="color: var(--accent-red);">' + escapeHtml(list.error || '加载失败') + '</div>';
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">暂无举报</div>';
                        return;
                    }
                    body.innerHTML = list.map(function (r) {
                        return '<div class="glass" style="padding: 0.75rem; margin-bottom: 0.75rem; border-radius: 8px;">' +
                            '<div style="font-size: 0.85rem; margin-bottom: 0.4rem;"><span style="color: var(--text-muted);">#' + r.id + '</span> ' + (r.status === 'pending' ? '<span style="color: var(--accent-red);">待处理</span>' : r.status === 'resolved' ? '<span style="color: var(--accent-green);">已处理</span>' : '<span style="color: var(--text-muted);">已忽略</span>') + '</div>' +
                            '<div style="margin-bottom: 0.4rem;">举报人: ' + escapeHtml(r.reporter_nickname || '') + ' · 被举报: ' + escapeHtml(r.reported_nickname || '') + (r.post_title ? (' · 帖子: ' + escapeHtml(r.post_title)) : '') + '</div>' +
                            '<div style="font-size: 0.9rem; color: var(--text-primary); margin-bottom: 0.5rem;">' + escapeHtml(r.reason || '') + '</div>' +
                            (r.admin_notes ? ('<div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;">备注: ' + escapeHtml(r.admin_notes) + '</div>') : '') +
                            (r.status === 'pending' ? '<div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;"><button class="btn btn-primary btn-sm" onclick="Admin.resolveReport(' + r.id + ', \'resolved\')">已处理</button><button class="btn btn-ghost btn-sm" onclick="Admin.resolveReport(' + r.id + ', \'dismissed\')">忽略</button></div>' : '') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = '<div style="color: var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
                }
            },

            async resolveReport(reportId, status) {
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
                        body.innerHTML = '<div style="color: var(--accent-red);">' + escapeHtml(list.error || '加载失败') + '</div>';
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">暂无用户</div>';
                        return;
                    }
                    body.innerHTML = list.map(function (u) {
                        return '<div class="glass" style="padding: 0.75rem; margin-bottom: 0.75rem; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">' +
                            '<div><div style="font-weight: 600;">' + escapeHtml(u.nickname || u.username || '') + '</div><div style="font-size: 0.8rem; color: var(--text-muted);">ID: ' + u.id + ' · ' + (u.type === 'web3' ? '钱包' : 'Web2') + '</div></div>' +
                            (!u.is_admin ? ('<button class="btn btn-ghost btn-sm" style="color: var(--accent-red);" onclick="Admin.toggleBan(' + u.id + ', ' + u.is_banned + ')">' + (u.is_banned ? '解除封禁' : '封禁') + '</button>') : '<span style="font-size: 0.8rem; color: var(--accent-gold);">管理员</span>') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = '<div style="color: var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
                }
            },

            async toggleBan(userId, currentlyBanned) {
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
                        body.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem;">暂无公告</div>';
                        return;
                    }
                    body.innerHTML = list.map(function (a) {
                        return '<div class="glass" style="padding:0.7rem; margin-bottom:0.7rem; border-radius:8px;">' +
                            '<div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:center;"><b>' + (a.entry_type === 'activity' ? '🎉 ' : '📣 ') + escapeHtml(a.title || '') + '</b><span style="font-size:0.78rem; color:' + (a.is_active ? 'var(--accent-green)' : 'var(--text-muted)') + ';">' + (a.is_active ? '生效中' : '未生效') + '</span></div>' +
                            '<div style="font-size:0.86rem; margin:0.45rem 0;">' + escapeHtml(a.content || '') + '</div>' +
                            '<div style="font-size:0.74rem; color:var(--text-muted); margin-bottom:0.45rem;">类型: ' + escapeHtml(a.entry_type || 'announcement') + (a.starts_at ? (' · 开始: ' + new Date(a.starts_at).toLocaleString()) : '') + (a.expires_at ? (' · 结束: ' + new Date(a.expires_at).toLocaleString()) : '') + '</div>' +
                            '<div style="display:flex; gap:0.45rem; flex-wrap:wrap;"><button class="btn btn-ghost btn-sm" onclick="Admin.toggleAnnouncementActive(' + a.id + ', ' + (a.is_active ? 'false' : 'true') + ')">' + (a.is_active ? '停用' : '启用') + '</button><button class="btn btn-ghost btn-sm" style="color:var(--accent-red);" onclick="Admin.deleteAnnouncement(' + a.id + ')">删除</button></div>' +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = '<div style="color:var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
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
                if (!confirm('确定删除此公告？')) return;
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
                        body.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem;">暂无日志</div>';
                        return;
                    }
                    body.innerHTML = logs.map(function (l) {
                        return '<div style="padding:0.45rem 0; border-bottom:1px dashed var(--border-color);">' +
                            '<div style="font-size:0.82rem; color:var(--text-muted);">' + new Date(l.created_at).toLocaleString() + ' · Admin#' + l.admin_id + '</div>' +
                            '<div style="font-size:0.9rem;"><b>' + escapeHtml(l.action || '') + '</b> ' + escapeHtml(l.target_type || '') + '#' + escapeHtml(String(l.target_id || '')) + '</div>' +
                            (l.details ? ('<div style="font-size:0.8rem; color:var(--text-secondary);">' + escapeHtml(l.details) + '</div>') : '') +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = '<div style="color:var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
                }
            },

            async openPendingPublications() {
                Modal.open('adminPendingModal');
                var body = document.getElementById('adminPendingBody');
                if (!body) return;
                body.innerHTML = '加载中...';
                try {
                    var result = await apiJson(API_BASE + '/admin/pending-publications', { check401: false, fallback: {} });
                    var data = result.data || {};
                    var items = data.items || [];
                    if (!result.res.ok) throw new Error(data.error || '加载失败');
                    if (!items.length) {
                        body.innerHTML = '<div style="display:flex; justify-content:flex-end; margin-bottom:0.75rem;"><button class="btn btn-ghost btn-sm" onclick="Admin.runPendingBatchRetry()">运行一轮自动补偿</button></div><div style="color:var(--text-muted); text-align:center; padding:1rem;">当前没有待恢复发布记录</div>';
                        return;
                    }
                    body.innerHTML = '<div style="display:flex; justify-content:flex-end; margin-bottom:0.75rem;"><button class="btn btn-ghost btn-sm" onclick="Admin.runPendingBatchRetry()">运行一轮自动补偿</button></div>' + items.map(function (row) {
                        var who = escapeHtml(row.nickname || row.username || ('用户#' + row.user_id));
                        var statusColor = row.status === 'awaiting_retry' ? 'var(--accent-orange)' : (row.status === 'storage_ready' ? 'var(--accent-green)' : 'var(--accent-purple)');
                        return '<div class="glass" style="padding:0.8rem; margin-bottom:0.75rem; border-radius:10px;">' +
                            '<div style="display:flex; justify-content:space-between; gap:0.6rem; flex-wrap:wrap; align-items:center;">' +
                                '<div><b>' + escapeHtml(row.title || '未命名帖子') + '</b><div style="font-size:0.8rem; color:var(--text-muted); margin-top:0.2rem;">' + who + ' · ' + escapeHtml(row.tx_hash || '') + '</div></div>' +
                                '<span style="font-size:0.82rem; color:' + statusColor + ';">' + escapeHtml(row.status || 'pending') + '</span>' +
                            '</div>' +
                            (row.last_error ? ('<div style="font-size:0.82rem; color:var(--text-secondary); margin-top:0.5rem;">' + escapeHtml(row.last_error) + '</div>') : '') +
                            '<div style="font-size:0.76rem; color:var(--text-muted); margin-top:0.45rem;">更新时间: ' + (row.updated_at ? new Date(row.updated_at).toLocaleString() : '-') + '</div>' +
                            '<div style="display:flex; gap:0.45rem; flex-wrap:wrap; margin-top:0.65rem;">' +
                                '<button class="btn btn-primary btn-sm" onclick="Admin.retryPendingPublication(' + row.id + ')">补偿重试</button>' +
                                '<button class="btn btn-ghost btn-sm" style="color:var(--accent-red);" onclick="Admin.deletePendingPublication(' + row.id + ')">删除记录</button>' +
                            '</div>' +
                        '</div>';
                    }).join('');
                } catch (e) {
                    body.innerHTML = '<div style="color:var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
                }
            },

            async runPendingBatchRetry() {
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
                if (!confirm('确定删除这条待恢复记录？')) return;
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
                    body.innerHTML = '' +
                        '<div class="glass" style="padding:0.9rem; margin-bottom:0.8rem; border-radius:10px;">' +
                            '<div style="display:flex; gap:0.7rem; flex-wrap:wrap;">' +
                                '<div><div style="font-size:0.78rem; color:var(--text-muted);">待发布总数</div><div style="font-size:1.35rem; font-weight:700;">' + escapeHtml(String(pending.total || 0)) + '</div></div>' +
                                '<div><div style="font-size:0.78rem; color:var(--text-muted);">最近一小时错误</div><div style="font-size:1.35rem; font-weight:700; color:var(--accent-red);">' + escapeHtml(String(lastHour.error || 0)) + '</div></div>' +
                                '<div><div style="font-size:0.78rem; color:var(--text-muted);">最近一小时警告</div><div style="font-size:1.35rem; font-weight:700; color:var(--accent-orange);">' + escapeHtml(String(lastHour.warn || 0)) + '</div></div>' +
                                '<div><div style="font-size:0.78rem; color:var(--text-muted);">自动补偿</div><div style="font-size:1.05rem; font-weight:700; color:' + (worker.enabled ? 'var(--accent-green)' : 'var(--text-muted)') + ';">' + (worker.enabled ? ('运行中 / ' + escapeHtml(String(worker.interval_seconds || 0)) + 's') : '未启用') + '</div></div>' +
                            '</div>' +
                        '</div>' +
                        '<div style="display:grid; gap:0.7rem; margin-bottom:0.8rem;">' +
                            alerts.map(function (alert) {
                                var color = alert.severity === 'error' ? 'var(--accent-red)' : (alert.severity === 'warn' ? 'var(--accent-orange)' : 'var(--accent-green)');
                                return '<div class="glass" style="padding:0.8rem; border-radius:10px; border:1px solid ' + color + ';">' +
                                    '<div style="font-weight:700; color:' + color + ';">' + escapeHtml(alert.title || '告警') + '</div>' +
                                    '<div style="font-size:0.86rem; color:var(--text-secondary); margin-top:0.25rem;">' + escapeHtml(alert.message || '') + '</div>' +
                                '</div>';
                            }).join('') +
                        '</div>' +
                        '<div class="glass" style="padding:0.9rem; border-radius:10px;">' +
                            '<div style="font-weight:700; margin-bottom:0.6rem;">最近事件</div>' +
                            (latest.length ? latest.map(function (ev) {
                                var payload = ev.payload || {};
                                return '<div style="padding:0.45rem 0; border-bottom:1px dashed var(--border-color);">' +
                                    '<div style="font-size:0.8rem; color:var(--text-muted);">' + new Date(ev.created_at).toLocaleString() + ' · ' + escapeHtml(ev.severity || 'info') + '</div>' +
                                    '<div style="font-weight:600;">' + escapeHtml(ev.event || '') + '</div>' +
                                    '<div style="font-size:0.8rem; color:var(--text-secondary);">' + escapeHtml(JSON.stringify(payload).slice(0, 220)) + '</div>' +
                                '</div>';
                            }).join('') : '<div style="color:var(--text-muted);">暂无事件</div>') +
                        '</div>';
                } catch (e) {
                    body.innerHTML = '<div style="color:var(--accent-red);">' + escapeHtml(e.message || '加载失败') + '</div>';
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
    };
})();
