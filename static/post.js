(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var root = document.querySelector('.post-page-shell');
    var body = document.getElementById('postPageBody');
    var postId = Number(root && root.getAttribute('data-post-id'));
    var currentUser = null;
    var currentPost = null;
    var replyParentId = null;

    function parseJsonSafe(res, fallback) {
        return res.json().catch(function () { return fallback; });
    }

    function escapeAttr(s) {
        if (s == null || s === undefined) return '';
        return String(s)
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    function mentionifyText(text) {
        var safe = escapeHtml(text || '');
        return safe.replace(/(^|[\s(（\[【])@([A-Za-z0-9_\u4e00-\u9fff]{2,32})/g, function (_, prefix, token) {
            var encoded = encodeURIComponent(token || '');
            return prefix + '<a class="mention-link" href="/profile?user=' + encoded + '" data-no-transition="1">@' + token + '</a>';
        });
    }

    function authHeaders(withJson) {
        var token = localStorage.getItem('token');
        var h = {};
        if (withJson) h['Content-Type'] = 'application/json';
        if (token) h['Authorization'] = 'Bearer ' + token;
        return h;
    }

    function equippedTitleByKey(key) {
        var map = {
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
        return map[key] || key;
    }

    function renderAuthorBadge(user) {
        if (!user) return '';
        var equipped = (user.equipped_achievement_key || '').trim();
        if (equipped) {
            return '<span class="honor-badge" style="border-color:rgba(16,185,129,0.5); color:var(--accent-green);">🏆 ' + escapeHtml(equippedTitleByKey(equipped)) + '</span>';
        }
        if (!user.honor_title) return '';
        return '<span class="honor-badge">🏷 ' + escapeHtml(user.honor_title) + '</span>';
    }

    function toastError(msg) {
        if (window.Toast && Toast.error) Toast.error(msg || '操作失败');
    }

    function toastSuccess(msg) {
        if (window.Toast && Toast.success) Toast.success(msg || '操作成功');
    }

    function requireLogin() {
        if (currentUser) return true;
        toastError('请先登录');
        if (typeof navigateWithTransition === 'function') navigateWithTransition('/');
        else window.location.href = '/';
        return false;
    }

    async function loadCurrentUser() {
        var token = localStorage.getItem('token');
        if (!token) {
            currentUser = null;
            return;
        }
        try {
            var res = await fetch(API_BASE + '/user/me', { headers: authHeaders(false) });
            var data = await parseJsonSafe(res, {});
            if (!res.ok) {
                if (typeof handle401 === 'function' && handle401(res)) return;
                currentUser = null;
                return;
            }
            currentUser = data || null;
        } catch (_) {
            currentUser = null;
        }
    }

    function renderComments(list, depth) {
        depth = depth || 0;
        if (!Array.isArray(list) || !list.length) return '';
        return list.map(function (c) {
            var author = (c && c.author) || {};
            var nick = author.nickname || '匿名';
            var created = c && c.created_at ? new Date(c.created_at).toLocaleString() : '';
            var replies = renderComments(c && c.replies, depth + 1);
            var margin = depth * 20;
            var border = depth > 0 ? '2px solid var(--border-color)' : 'none';
            var padding = depth > 0 ? '0.9rem' : '0';
            return (
                '<div class="comment-item" style="margin-left:' + margin + 'px; border-left:' + border + '; padding-left:' + padding + ';">' +
                '<div class="comment-header"><span>' + escapeHtml(nick) + '</span><span>' + escapeHtml(created) + '</span></div>' +
                '<div style="margin-bottom:0.45rem;">' + mentionifyText((c && c.content) || '') + '</div>' +
                '<button class="btn btn-ghost btn-sm" type="button" data-action="reply" data-parent-id="' + Number(c.id) + '" data-nickname="' + escapeAttr(nick) + '">↩ 回复</button>' +
                replies +
                '</div>'
            );
        }).join('');
    }

    function renderSeries(series) {
        if (!Array.isArray(series) || !series.length) return '';
        return series.map(function (s) {
            return (
                '<div class="series-block">' +
                '<div style="margin-bottom:0.35rem;">📚 所属系列：<a href="/series/' + Number(s.series_id) + '" data-no-transition="1" style="color:var(--accent-purple-light); text-decoration:underline;">' + escapeHtml(s.title || '') + '</a> · 第 ' + Number(s.order_index || 0) + ' 篇</div>' +
                '<div style="display:flex; gap:0.5rem; flex-wrap:wrap;">' +
                (s.prev_post_id ? '<a class="btn btn-ghost btn-sm" href="/post/' + Number(s.prev_post_id) + '" data-no-transition="1">⬅️ 上一篇</a>' : '') +
                (s.next_post_id ? '<a class="btn btn-ghost btn-sm" href="/post/' + Number(s.next_post_id) + '" data-no-transition="1">➡️ 下一篇</a>' : '') +
                '</div>' +
                '</div>'
            );
        }).join('');
    }

    function renderPost(p) {
        currentPost = p;
        var isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
        var commentsHtml = renderComments(p.comments || [], 0);
        var seriesHtml = renderSeries(p.series || []);
        var canComment = !!(p.allow_comments || (currentUser && currentUser.is_admin));
        var meta = [
            (p.is_special_announcement ? '<span style="color:var(--accent-orange); font-weight:700;">📜 长公告</span>' : ''),
            (p.is_pinned ? '<span style="color:var(--accent-gold); font-weight:700;">📌 置顶</span>' : ''),
            '发布者: ' + escapeHtml((p.author && p.author.nickname) || '用户') + ' ' + renderAuthorBadge(p.author) + ' ' + ((p.author && p.author.id != null) ? formatUserId(p.author.id) : ''),
            '浏览: ' + Number(p.view_count || 0)
        ].filter(Boolean).join(' | ');

        body.innerHTML = '' +
            '<h2 style="margin-bottom:0.5rem;">' + escapeHtml(p.title || '') + '</h2>' +
            '<div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem; display:flex; align-items:center; gap:0.45rem; flex-wrap:wrap;">' + meta + '</div>' +
            '<article class="post-detail-content">' + ((p.content == null) ? '' : String(p.content)) + '</article>' +
            '<div class="on-chain-evidence" style="margin-top:1rem; padding:0.75rem; background:var(--bg-secondary); border-radius:8px; font-size:0.85rem;">' +
                '<div style="color:var(--text-muted); margin-bottom:0.5rem;">' + (isPermanent ? '✅ 已永久保存 · 链上可验' : 'ℹ️ 当前帖子暂未永存') + '</div>' +
                '<div style="display:flex; flex-wrap:wrap; gap:0.5rem 1rem;">' +
                    (p.tx_hash ? '<a href="https://bscscan.com/tx/' + escapeAttr(p.tx_hash) + '" target="_blank" rel="noopener" style="color:var(--accent-purple);">⛓ 支付凭证 BSCScan</a>' : '<span style="color:var(--text-muted);">无支付凭证</span>') +
                    (p.ipfs_cid ? '<a href="https://arweave.net/' + escapeAttr(p.ipfs_cid) + '" target="_blank" rel="noopener" style="color:var(--accent-gold);">💾 永存档案</a>' : '') +
                '</div>' +
            '</div>' +
            seriesHtml +
            '<div style="display:flex; gap:0.5rem; margin:1rem 0; border-top:1px solid var(--border-color); padding-top:1rem; flex-wrap:wrap;">' +
                '<button class="btn btn-ghost" type="button" data-action="like">😰 恐惧 (' + Number(p.likes_count || 0) + ')</button>' +
                '<button class="btn btn-ghost" type="button" data-action="bookmark">⭐ 收藏' + (p.is_bookmarked ? '（已收）' : '') + '</button>' +
                '<button class="btn btn-ghost" type="button" data-action="report">🚩 举报</button>' +
            '</div>' +
            '<section class="comments-section">' +
                '<h4>评论</h4>' +
                '<div id="postCommentsList" style="margin-bottom:0.8rem;">' + (commentsHtml || '<div style="color:var(--text-muted);">暂无评论</div>') + '</div>' +
                '<div id="replyTarget" style="display:none; font-size:0.8rem; color:var(--accent-purple); padding:0.2rem 0;">回复 @<span id="replyTargetName"></span> <button class="btn btn-ghost" style="padding:0 0.3rem; height:auto;" type="button" data-action="cancel-reply">✕</button></div>' +
                '<div style="display:flex; gap:0.5rem;">' +
                    '<input type="text" id="commentInput" class="form-input" placeholder="' + (canComment ? '发表评论...' : '评论区已关闭') + '" ' + (canComment ? '' : 'disabled') + '>' +
                    '<button class="btn btn-primary" id="commentSendBtn" type="button" data-action="comment" ' + (canComment ? '' : 'disabled') + '>发送</button>' +
                '</div>' +
            '</section>';

        bindPostEvents();
    }

    function setReply(parentId, nickname) {
        replyParentId = parentId;
        var target = document.getElementById('replyTarget');
        var name = document.getElementById('replyTargetName');
        var input = document.getElementById('commentInput');
        if (target) target.style.display = 'block';
        if (name) name.textContent = nickname || '匿名';
        if (input) {
            input.placeholder = '回复 @' + (nickname || '匿名') + '...';
            input.focus();
        }
    }

    function cancelReply() {
        replyParentId = null;
        var target = document.getElementById('replyTarget');
        var input = document.getElementById('commentInput');
        if (target) target.style.display = 'none';
        if (input) input.placeholder = '发表评论...';
    }

    async function doPost(url, payload) {
        var opts = {
            method: 'POST',
            headers: authHeaders(!!payload)
        };
        if (payload) opts.body = JSON.stringify(payload);
        return fetch(url, opts);
    }

    async function likePost() {
        if (!requireLogin()) return;
        await doPost(API_BASE + '/posts/' + postId + '/like');
        await loadPost();
    }

    async function bookmarkPost() {
        if (!requireLogin()) return;
        await doPost(API_BASE + '/posts/' + postId + '/bookmark');
        await loadPost();
    }

    async function reportPost() {
        if (!requireLogin()) return;
        var reason = prompt('请简要说明举报原因（违规内容、广告、抄袭等）：');
        if (reason == null || !reason.trim()) return;
        if (reason.length > 500) {
            toastError('原因最多500字');
            return;
        }
        var res = await doPost(API_BASE + '/reports', { post_id: postId, reason: reason.trim() });
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '举报失败');
            return;
        }
        toastSuccess(data.message || '举报已提交');
    }

    async function submitComment() {
        if (!requireLogin()) return;
        if (!currentPost) return;
        var input = document.getElementById('commentInput');
        if (!input) return;
        var content = (input.value || '').trim();
        if (!content) {
            toastError('评论不能为空');
            return;
        }
        var payload = { content: content };
        if (replyParentId) payload.parent_id = replyParentId;
        var res = await doPost(API_BASE + '/posts/' + postId + '/comments', payload);
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '评论失败');
            return;
        }
        input.value = '';
        cancelReply();
        await loadPost();
    }

    function bindPostEvents() {
        if (!body) return;
        body.querySelectorAll('.post-detail-content img').forEach(function (im) {
            im.setAttribute('referrerpolicy', 'no-referrer');
            im.loading = 'lazy';
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="reply"]'), function (btn) {
            btn.addEventListener('click', function () {
                var pid = Number(btn.getAttribute('data-parent-id'));
                var nick = btn.getAttribute('data-nickname') || '匿名';
                setReply(pid, nick);
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="cancel-reply"]'), function (btn) {
            btn.addEventListener('click', cancelReply);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.addEventListener('click', likePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.addEventListener('click', bookmarkPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="report"]'), function (btn) {
            btn.addEventListener('click', reportPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="comment"]'), function (btn) {
            btn.addEventListener('click', submitComment);
        });
    }

    async function loadPost() {
        if (!body) return;
        body.textContent = '加载中...';
        try {
            var res = await fetch(API_BASE + '/posts/' + postId, { headers: authHeaders(false) });
            var data = await parseJsonSafe(res, {});
            if (typeof handle401 === 'function' && handle401(res)) return;
            if (!res.ok) {
                throw new Error((data && data.error) || '加载失败');
            }
            renderPost(data);
        } catch (e) {
            body.innerHTML = '<div class="list-page-error">' + escapeHtml((e && e.message) || '加载失败') + '</div>';
        }
    }

    window.addEventListener('load', async function () {
        if (!Number.isFinite(postId) || postId <= 0) {
            if (body) body.innerHTML = '<div class="list-page-error">无效帖子 ID</div>';
            return;
        }
        await loadCurrentUser();
        await loadPost();
    });
})();
