(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var root = document.querySelector('.post-page-shell');
    var body = document.getElementById('postPageBody');
    var postId = Number(root && root.getAttribute('data-post-id'));
    var currentUser = null;
    var currentPost = null;
    var replyParentId = null;
    var replyTargetName = '';
    var replyDraftText = '';
    var commentsRenderToken = 0;
    var visibleCommentCount = 0;
    var commentSortMode = 'latest';
    var showAuthorCommentsOnly = false;
    var lightboxItems = [];
    var lightboxIndex = 0;
    var INITIAL_COMMENT_BATCH = 6;
    var COMMENT_BATCH_SIZE = 6;

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

    function getShareUrl() {
        return window.location.origin + '/post/' + Number(postId);
    }

    function getShareText() {
        var title = (currentPost && currentPost.title ? String(currentPost.title) : '').trim();
        return title ? ('「' + title + '」') : '来看看这篇灵异帖';
    }

    async function sharePost() {
        var url = getShareUrl();
        var text = getShareText();
        if (navigator.share) {
            try {
                await navigator.share({
                    title: (currentPost && currentPost.title) || '诡话',
                    text: text,
                    url: url
                });
                return;
            } catch (e) {
                if (e && e.name === 'AbortError') return;
            }
        }
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(url);
            } else {
                var ta = document.createElement('textarea');
                ta.value = url;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            toastSuccess('已复制帖子链接');
        } catch (_) {
            toastError('分享失败，请稍后重试');
        }
    }

    function sharePostToX() {
        var url = getShareUrl();
        var text = getShareText();
        var intent = 'https://x.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(url);
        window.open(intent, '_blank', 'noopener,noreferrer');
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
            var replyCount = Array.isArray(c && c.replies) ? c.replies.length : 0;
            var collapseDeepReplies = depth >= 1 && replyCount > 0;
            var replyThreadId = 'reply-thread-' + Number(c.id || 0) + '-' + depth;
            var margin = depth * 20;
            var border = depth > 0 ? '2px solid var(--border-color)' : 'none';
            var padding = depth > 0 ? '0.9rem' : '0';
            var authorTag = isPostAuthor(author) ? '<span class="comment-role-badge author">作者</span>' : '';
            var adminTag = author && author.is_admin ? '<span class="comment-role-badge admin">管理员</span>' : '';
            var commentClasses = ['comment-item'];
            if (isPostAuthor(author)) commentClasses.push('is-author-comment');
            if (author && author.is_admin) commentClasses.push('is-admin-comment');
            var inlineReplyComposer = replyParentId === Number(c.id)
                ? (
                    '<div class="inline-reply-box">' +
                        '<div class="inline-reply-title">回复 @' + escapeHtml(replyTargetName || nick) + '</div>' +
                        '<div class="inline-reply-actions">' +
                            '<input type="text" id="inlineReplyInput" class="form-input" placeholder="写下你的回复..." value="' + escapeAttr(replyDraftText || '') + '">' +
                            '<button class="btn btn-primary btn-sm" type="button" data-action="submit-inline-reply">发送</button>' +
                            '<button class="btn btn-ghost btn-sm" type="button" data-action="cancel-inline-reply">取消</button>' +
                        '</div>' +
                    '</div>'
                )
                : '';
            return (
                '<div class="' + commentClasses.join(' ') + '" style="margin-left:' + margin + 'px; border-left:' + border + '; padding-left:' + padding + ';">' +
                '<div class="comment-header"><div class="comment-author-line"><span class="comment-author-name">' + escapeHtml(nick) + '</span>' + authorTag + adminTag + '</div><span>' + escapeHtml(created) + '</span></div>' +
                '<div style="margin-bottom:0.45rem;">' + mentionifyText((c && c.content) || '') + '</div>' +
                '<div style="display:flex; gap:0.45rem; flex-wrap:wrap;">' +
                    '<button class="btn btn-ghost btn-sm" type="button" data-action="reply" data-parent-id="' + Number(c.id) + '" data-nickname="' + escapeAttr(nick) + '">↩ 回复</button>' +
                    '<button class="btn btn-ghost btn-sm" type="button" data-action="like-comment" data-comment-id="' + Number(c.id) + '">' + ((c && c.is_liked) ? '👍 已赞' : '👍 点赞') + ' (' + Number((c && c.likes_count) || 0) + ')</button>' +
                '</div>' +
                inlineReplyComposer +
                (collapseDeepReplies
                    ? '<div class="comment-thread-toggle-wrap"><button class="btn btn-ghost btn-sm comment-thread-toggle" type="button" data-action="toggle-replies" data-target-id="' + replyThreadId + '" data-collapsed-label="展开 ' + replyCount + ' 条深层回复" data-expanded-label="收起深层回复" aria-expanded="false">展开 ' + replyCount + ' 条深层回复</button></div><div class="comment-thread-group" id="' + replyThreadId + '" hidden>' + replies + '</div>'
                    : replies) +
                '</div>'
            );
        }).join('');
    }

    function renderPostLoadingShell() {
        return '' +
            '<div class="post-page-loading-shell">' +
                '<div class="skeleton-block skeleton-title"></div>' +
                '<div class="skeleton-block skeleton-meta"></div>' +
                '<div class="skeleton-block skeleton-line"></div>' +
                '<div class="skeleton-block skeleton-line"></div>' +
                '<div class="skeleton-block skeleton-line short"></div>' +
                '<div class="post-page-loading-gallery">' +
                    '<div class="skeleton-block skeleton-thumb"></div>' +
                    '<div class="skeleton-block skeleton-thumb"></div>' +
                    '<div class="skeleton-block skeleton-thumb"></div>' +
                '</div>' +
                '<div class="skeleton-block skeleton-line"></div>' +
                '<div class="skeleton-block skeleton-line medium"></div>' +
            '</div>';
    }

    function renderCommentsLoadingState() {
        return '' +
            '<div class="comments-loading-state">' +
                '<div class="skeleton-block skeleton-line"></div>' +
                '<div class="skeleton-block skeleton-line short"></div>' +
                '<div class="skeleton-block skeleton-line"></div>' +
            '</div>';
    }

    function resetCommentVisibility(post) {
        var total = getProcessedComments(post).length;
        visibleCommentCount = Math.min(INITIAL_COMMENT_BATCH, total);
    }

    function isPostAuthor(user) {
        if (!currentPost || !currentPost.author || !user) return false;
        var postAuthor = currentPost.author || {};
        if (postAuthor.id != null && user.id != null && Number(postAuthor.id) === Number(user.id)) return true;
        if (postAuthor.username && user.username && String(postAuthor.username) === String(user.username)) return true;
        return false;
    }

    function getCommentTimestamp(comment) {
        if (!comment || !comment.created_at) return 0;
        var ts = new Date(comment.created_at).getTime();
        return Number.isFinite(ts) ? ts : 0;
    }

    function compareComments(a, b) {
        var mode = commentSortMode === 'hot' ? 'hot' : 'latest';
        if (mode === 'hot') {
            var hotDiff = Number((b && b.likes_count) || 0) - Number((a && a.likes_count) || 0);
            if (hotDiff !== 0) return hotDiff;
        }
        return getCommentTimestamp(b) - getCommentTimestamp(a);
    }

    function buildProcessedComment(comment) {
        if (!comment) return null;
        var sourceReplies = Array.isArray(comment.replies) ? comment.replies : [];
        var nextReplies = sourceReplies
            .map(buildProcessedComment)
            .filter(Boolean)
            .sort(compareComments);
        var authorMatch = isPostAuthor(comment.author || {});
        if (showAuthorCommentsOnly && !authorMatch && !nextReplies.length) return null;
        return Object.assign({}, comment, { replies: nextReplies });
    }

    function getProcessedComments(post) {
        var list = Array.isArray(post && post.comments) ? post.comments : [];
        return list
            .map(buildProcessedComment)
            .filter(Boolean)
            .sort(compareComments);
    }

    function renderVisibleComments(post) {
        var list = getProcessedComments(post);
        var visible = list.slice(0, visibleCommentCount || list.length);
        return renderComments(visible, 0);
    }

    function updateCommentsToolbar(post) {
        var latestBtn = document.getElementById('commentsSortLatestBtn');
        var hotBtn = document.getElementById('commentsSortHotBtn');
        var authorBtn = document.getElementById('commentsAuthorOnlyBtn');
        var meta = document.getElementById('commentsFilterMeta');
        var total = getProcessedComments(post).length;
        if (latestBtn) latestBtn.classList.toggle('active', commentSortMode === 'latest');
        if (hotBtn) hotBtn.classList.toggle('active', commentSortMode === 'hot');
        if (authorBtn) authorBtn.classList.toggle('active', !!showAuthorCommentsOnly);
        if (authorBtn) authorBtn.textContent = showAuthorCommentsOnly ? '查看全部回复' : '只看作者回复';
        if (meta) {
            var shown = Math.min(visibleCommentCount || 0, total);
            meta.textContent = total ? ('已显示 ' + shown + ' / ' + total + ' 条') : '暂无评论';
        }
    }

    function updateCommentsMoreButton(post) {
        var btn = document.getElementById('commentsMoreBtn');
        if (!btn) return;
        var total = getProcessedComments(post).length;
        if (!total || visibleCommentCount >= total) {
            btn.hidden = true;
            btn.textContent = '';
            return;
        }
        var remain = Math.max(0, total - visibleCommentCount);
        btn.hidden = false;
        btn.textContent = '展开更多评论（剩余 ' + remain + ' 条）';
    }

    function scheduleCommentsRender(post) {
        commentsRenderToken += 1;
        var token = commentsRenderToken;
        var run = function () {
            if (token !== commentsRenderToken) return;
            var host = document.getElementById('postCommentsList');
            if (!host) return;
            var commentsHtml = renderVisibleComments(post);
            host.innerHTML = commentsHtml || '<div style="color:var(--text-muted);">暂无评论</div>';
            bindCommentListEvents();
            updateCommentsToolbar(post);
            updateCommentsMoreButton(post);
            var inlineInput = document.getElementById('inlineReplyInput');
            if (inlineInput && replyParentId) inlineInput.focus();
        };
        if (window.requestAnimationFrame) {
            window.requestAnimationFrame(function () {
                window.setTimeout(run, 40);
            });
            return;
        }
        window.setTimeout(run, 40);
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
        commentsRenderToken += 1;
        resetCommentVisibility(p);
        var isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
        var seriesHtml = renderSeries(p.series || []);
        var canComment = !!(p.allow_comments || (currentUser && currentUser.is_admin));
        var meta = [
            (p.is_special_announcement ? '<span style="color:var(--accent-orange); font-weight:700;">📜 长公告</span>' : ''),
            (p.is_pinned ? '<span style="color:var(--accent-gold); font-weight:700;">📌 置顶</span>' : ''),
            '发布者: ' + escapeHtml((p.author && p.author.nickname) || '用户') + ' ' + renderAuthorBadge(p.author) + ' ' + ((p.author && p.author.id != null) ? formatUserId(p.author.id, p.author) : ''),
            '浏览: ' + Number(p.view_count || 0)
        ].filter(Boolean).join(' | ');
        var adminControls = '';
        if (currentUser && currentUser.is_admin) {
            adminControls =
                '<div style="margin-top:1rem; padding-top:1rem; border-top:1px dashed var(--accent-red); color:var(--accent-red);">' +
                    '<div style="margin-bottom:0.5rem; font-size:0.82rem; font-weight:700;">👮 管理员操作</div>' +
                    '<div style="display:flex; gap:0.5rem; flex-wrap:wrap;">' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-delete" style="border-color:var(--accent-red); color:var(--accent-red);">删除帖子</button>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-toggle-hide">' + (p.is_hidden ? '取消隐藏' : '隐藏帖子') + '</button>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-toggle-comments">' + (p.allow_comments ? '关闭评论' : '开启评论') + '</button>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-toggle-pin" style="border-color:var(--accent-gold); color:var(--accent-gold);">' + (p.is_pinned ? '取消置顶' : '设为置顶') + '</button>' +
                    '</div>' +
                '</div>';
        }

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
                '<button class="btn btn-ghost" type="button" data-action="share">🔗 分享</button>' +
                '<button class="btn btn-ghost" type="button" data-action="share-x">𝕏 分享</button>' +
                '<button class="btn btn-ghost" type="button" data-action="report">🚩 举报</button>' +
            '</div>' +
            adminControls +
            '<section class="comments-section">' +
                '<h4>评论</h4>' +
                '<div class="comments-toolbar">' +
                    '<div class="comments-toolbar-group">' +
                        '<button class="btn btn-ghost btn-sm comments-filter-btn" id="commentsSortLatestBtn" type="button" data-action="sort-comments" data-sort-mode="latest">最新</button>' +
                        '<button class="btn btn-ghost btn-sm comments-filter-btn" id="commentsSortHotBtn" type="button" data-action="sort-comments" data-sort-mode="hot">最热</button>' +
                        '<button class="btn btn-ghost btn-sm comments-filter-btn" id="commentsAuthorOnlyBtn" type="button" data-action="toggle-author-comments">只看作者回复</button>' +
                    '</div>' +
                    '<div class="comments-filter-meta" id="commentsFilterMeta"></div>' +
                '</div>' +
                '<div id="postCommentsList" style="margin-bottom:0.8rem;">' + renderCommentsLoadingState() + '</div>' +
                '<div class="comments-more-wrap"><button class="btn btn-ghost btn-sm" id="commentsMoreBtn" type="button" data-action="more-comments" hidden></button></div>' +
                '<div style="display:flex; gap:0.5rem;">' +
                    '<input type="text" id="commentInput" class="form-input" placeholder="' + (canComment ? '发表评论...' : '评论区已关闭') + '" ' + (canComment ? '' : 'disabled') + '>' +
                    '<button class="btn btn-primary" id="commentSendBtn" type="button" data-action="comment" ' + (canComment ? '' : 'disabled') + '>发送</button>' +
                '</div>' +
            '</section>';

        body.classList.remove('is-ready');
        body.classList.add('is-entering');
        bindPostEvents();
        scheduleCommentsRender(p);
        window.requestAnimationFrame(function () {
            body.classList.add('is-ready');
            body.classList.remove('is-entering');
        });
    }

    function setReply(parentId, nickname) {
        replyParentId = parentId;
        replyTargetName = nickname || '匿名';
        replyDraftText = '';
        scheduleCommentsRender(currentPost);
    }

    function cancelReply() {
        replyParentId = null;
        replyTargetName = '';
        replyDraftText = '';
        scheduleCommentsRender(currentPost);
    }

    function updatePostActionButtons() {
        if (!body || !currentPost) return;
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.textContent = '😰 恐惧 (' + Number(currentPost.likes_count || 0) + ')';
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.textContent = '⭐ 收藏' + (currentPost.is_bookmarked ? '（已收）' : '');
        });
    }

    function findCommentNode(list, commentId) {
        if (!Array.isArray(list)) return null;
        for (var i = 0; i < list.length; i += 1) {
            var item = list[i];
            if (!item) continue;
            if (Number(item.id) === Number(commentId)) return item;
            var found = findCommentNode(item.replies || [], commentId);
            if (found) return found;
        }
        return null;
    }

    function insertCommentIntoState(comment) {
        if (!currentPost || !comment) return;
        currentPost.comments = Array.isArray(currentPost.comments) ? currentPost.comments : [];
        comment.replies = Array.isArray(comment.replies) ? comment.replies : [];
        if (comment.parent_id) {
            var parent = findCommentNode(currentPost.comments, comment.parent_id);
            if (parent) {
                parent.replies = Array.isArray(parent.replies) ? parent.replies : [];
                parent.replies.unshift(comment);
                return;
            }
        }
        currentPost.comments.unshift(comment);
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
        var res = await doPost(API_BASE + '/posts/' + postId + '/like');
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError((data && (data.error || data.message)) || '操作失败');
            return;
        }
        var isLiked = String((data && data.message) || '').toLowerCase().indexOf('unlike') === -1;
        currentPost.likes_count = Math.max(0, Number(currentPost.likes_count || 0) + (isLiked ? 1 : -1));
        updatePostActionButtons();
    }

    async function bookmarkPost() {
        if (!requireLogin()) return;
        var res = await doPost(API_BASE + '/posts/' + postId + '/bookmark');
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError((data && (data.error || data.message)) || '操作失败');
            return;
        }
        currentPost.is_bookmarked = String((data && data.message) || '').toLowerCase().indexOf('unbook') === -1;
        updatePostActionButtons();
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
        var input = replyParentId ? document.getElementById('inlineReplyInput') : document.getElementById('commentInput');
        var submitBtn = replyParentId
            ? body && body.querySelector('[data-action="submit-inline-reply"]')
            : document.getElementById('commentSendBtn');
        if (!input) return;
        var content = (input.value || '').trim();
        if (!content) {
            toastError('评论不能为空');
            return;
        }
        if (replyParentId) replyDraftText = content;
        input.disabled = true;
        if (submitBtn) submitBtn.disabled = true;
        var payload = { content: content };
        if (replyParentId) payload.parent_id = replyParentId;
        var res = await doPost(API_BASE + '/posts/' + postId + '/comments', payload);
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            input.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
            toastError(data.error || '评论失败');
            return;
        }
        input.value = '';
        input.disabled = false;
        if (submitBtn) submitBtn.disabled = false;
        insertCommentIntoState(data && data.comment);
        if (!replyParentId) {
            var nextTotal = getProcessedComments(currentPost).length;
            visibleCommentCount = Math.min(nextTotal, Math.max(visibleCommentCount + 1, INITIAL_COMMENT_BATCH));
        }
        cancelReply();
        scheduleCommentsRender(currentPost);
    }

    async function likeComment(commentId) {
        if (!requireLogin()) return;
        var cid = Number(commentId);
        if (!Number.isFinite(cid) || cid <= 0) return;
        var res = await doPost(API_BASE + '/comments/' + cid + '/like');
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        var target = findCommentNode(currentPost && currentPost.comments, cid);
        if (target) {
            target.is_liked = !!data.liked;
            target.likes_count = Number(data.likes_count || 0);
            scheduleCommentsRender(currentPost);
        }
    }

    function loadMoreComments() {
        var total = getProcessedComments(currentPost).length;
        if (!total) return;
        visibleCommentCount = Math.min(total, visibleCommentCount + COMMENT_BATCH_SIZE);
        scheduleCommentsRender(currentPost);
    }

    function changeCommentSort(mode) {
        var nextMode = mode === 'hot' ? 'hot' : 'latest';
        if (commentSortMode === nextMode) return;
        commentSortMode = nextMode;
        resetCommentVisibility(currentPost);
        scheduleCommentsRender(currentPost);
    }

    function toggleAuthorCommentsOnly() {
        showAuthorCommentsOnly = !showAuthorCommentsOnly;
        resetCommentVisibility(currentPost);
        scheduleCommentsRender(currentPost);
    }

    async function adminDeletePost() {
        if (!currentUser || !currentUser.is_admin) return;
        if (!confirm('确定要删除这个帖子吗？此操作不可逆。')) return;
        var res = await fetch(API_BASE + '/posts/' + postId, {
            method: 'DELETE',
            headers: authHeaders(false)
        });
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '删除失败');
            return;
        }
        toastSuccess('帖子已删除');
        if (typeof navigateWithTransition === 'function') navigateWithTransition('/');
        else window.location.href = '/';
    }

    async function adminToggleHide() {
        if (!currentUser || !currentUser.is_admin) return;
        var res = await doPost(API_BASE + '/admin/posts/' + postId + '/hide');
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        toastSuccess(data.message || '状态已更新');
        await loadPost();
    }

    async function adminToggleComments() {
        if (!currentUser || !currentUser.is_admin) return;
        var res = await doPost(API_BASE + '/admin/posts/' + postId + '/toggle-comments');
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        toastSuccess(data.message || '状态已更新');
        await loadPost();
    }

    async function adminTogglePin() {
        if (!currentUser || !currentUser.is_admin || !currentPost) return;
        var nextPinned = !currentPost.is_pinned;
        var res = await doPost(API_BASE + '/admin/posts/' + postId + '/pin', {
            pinned: nextPinned,
            exclusive: true
        });
        var data = await parseJsonSafe(res, {});
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        toastSuccess(nextPinned ? '已置顶' : '已取消置顶');
        await loadPost();
    }

    function bindCommentListEvents() {
        if (!body) return;
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="reply"]'), function (btn) {
            btn.addEventListener('click', function () {
                var pid = Number(btn.getAttribute('data-parent-id'));
                var nick = btn.getAttribute('data-nickname') || '匿名';
                setReply(pid, nick);
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('#inlineReplyInput'), function (input) {
            input.addEventListener('input', function () {
                replyDraftText = input.value || '';
            });
            input.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && !evt.shiftKey) {
                    evt.preventDefault();
                    submitComment();
                }
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like-comment"]'), function (btn) {
            btn.addEventListener('click', function () {
                likeComment(btn.getAttribute('data-comment-id'));
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="toggle-replies"]'), function (btn) {
            btn.addEventListener('click', function () {
                var targetId = btn.getAttribute('data-target-id') || '';
                if (!targetId) return;
                var thread = document.getElementById(targetId);
                if (!thread) return;
                var nextHidden = !thread.hidden;
                thread.hidden = nextHidden;
                btn.setAttribute('aria-expanded', String(!nextHidden));
                btn.textContent = nextHidden
                    ? (btn.getAttribute('data-collapsed-label') || '展开回复')
                    : (btn.getAttribute('data-expanded-label') || '收起回复');
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="sort-comments"]'), function (btn) {
            btn.addEventListener('click', function () {
                changeCommentSort(btn.getAttribute('data-sort-mode'));
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="toggle-author-comments"]'), function (btn) {
            btn.addEventListener('click', toggleAuthorCommentsOnly);
        });
    }

    function ensureImageLightbox() {
        var existing = document.getElementById('postImageLightbox');
        if (existing) return existing;
        var overlay = document.createElement('div');
        overlay.id = 'postImageLightbox';
        overlay.className = 'post-image-lightbox';
        overlay.hidden = true;
        overlay.innerHTML = '' +
            '<button class="post-image-lightbox-close" type="button" aria-label="关闭看图" data-action="close-lightbox">✕</button>' +
            '<button class="post-image-lightbox-nav prev" type="button" aria-label="上一张" data-action="prev-lightbox">‹</button>' +
            '<div class="post-image-lightbox-stage">' +
                '<img class="post-image-lightbox-img" alt="帖子图片预览">' +
                '<div class="post-image-lightbox-meta" id="postImageLightboxMeta"></div>' +
            '</div>' +
            '<button class="post-image-lightbox-nav next" type="button" aria-label="下一张" data-action="next-lightbox">›</button>';
        document.body.appendChild(overlay);
        overlay.addEventListener('click', function (evt) {
            if (evt.target === overlay) closeImageLightbox();
        });
        Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="close-lightbox"]'), function (btn) {
            btn.addEventListener('click', closeImageLightbox);
        });
        Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="prev-lightbox"]'), function (btn) {
            btn.addEventListener('click', function (evt) {
                evt.stopPropagation();
                shiftImageLightbox(-1);
            });
        });
        Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="next-lightbox"]'), function (btn) {
            btn.addEventListener('click', function (evt) {
                evt.stopPropagation();
                shiftImageLightbox(1);
            });
        });
        return overlay;
    }

    function renderLightboxImage() {
        var overlay = document.getElementById('postImageLightbox');
        if (!overlay || !lightboxItems.length) return;
        var img = overlay.querySelector('.post-image-lightbox-img');
        var meta = document.getElementById('postImageLightboxMeta');
        var prevBtn = overlay.querySelector('[data-action="prev-lightbox"]');
        var nextBtn = overlay.querySelector('[data-action="next-lightbox"]');
        var item = lightboxItems[lightboxIndex] || {};
        if (img) {
            img.src = item.src || '';
            img.alt = item.alt || '帖子图片预览';
        }
        if (meta) meta.textContent = lightboxItems.length > 1 ? ('第 ' + (lightboxIndex + 1) + ' / ' + lightboxItems.length + ' 张') : '点击空白处关闭';
        if (prevBtn) prevBtn.hidden = lightboxItems.length <= 1;
        if (nextBtn) nextBtn.hidden = lightboxItems.length <= 1;
    }

    function openImageLightbox(index) {
        var overlay = ensureImageLightbox();
        if (!overlay || !lightboxItems.length) return;
        lightboxIndex = Math.max(0, Math.min(Number(index) || 0, lightboxItems.length - 1));
        renderLightboxImage();
        overlay.hidden = false;
        document.body.classList.add('lightbox-open');
    }

    function closeImageLightbox() {
        var overlay = document.getElementById('postImageLightbox');
        if (!overlay) return;
        overlay.hidden = true;
        document.body.classList.remove('lightbox-open');
    }

    function shiftImageLightbox(delta) {
        if (!lightboxItems.length) return;
        lightboxIndex = (lightboxIndex + delta + lightboxItems.length) % lightboxItems.length;
        renderLightboxImage();
    }

    function bindPostEvents() {
        if (!body) return;
        var contentImages = body.querySelectorAll('.post-detail-content img');
        lightboxItems = [];
        Array.prototype.forEach.call(contentImages, function (im, idx) {
            im.setAttribute('referrerpolicy', 'no-referrer');
            im.loading = 'lazy';
            im.decoding = 'async';
            im.classList.add('post-detail-image');
            im.setAttribute('data-lightbox-index', String(idx));
            lightboxItems.push({
                src: im.getAttribute('src') || '',
                alt: im.getAttribute('alt') || ('帖子图片 ' + (idx + 1))
            });
            im.addEventListener('click', function (evt) {
                evt.preventDefault();
                openImageLightbox(idx);
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.addEventListener('click', likePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.addEventListener('click', bookmarkPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="share"]'), function (btn) {
            btn.addEventListener('click', sharePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="share-x"]'), function (btn) {
            btn.addEventListener('click', sharePostToX);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="report"]'), function (btn) {
            btn.addEventListener('click', reportPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="comment"]'), function (btn) {
            btn.addEventListener('click', submitComment);
        });
        var rootCommentInput = document.getElementById('commentInput');
        if (rootCommentInput) {
            rootCommentInput.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && !evt.shiftKey) {
                    evt.preventDefault();
                    submitComment();
                }
            });
        }
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="submit-inline-reply"]'), function (btn) {
            btn.addEventListener('click', submitComment);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="cancel-inline-reply"]'), function (btn) {
            btn.addEventListener('click', cancelReply);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="more-comments"]'), function (btn) {
            btn.addEventListener('click', loadMoreComments);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="admin-delete"]'), function (btn) {
            btn.addEventListener('click', adminDeletePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="admin-toggle-hide"]'), function (btn) {
            btn.addEventListener('click', adminToggleHide);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="admin-toggle-comments"]'), function (btn) {
            btn.addEventListener('click', adminToggleComments);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="admin-toggle-pin"]'), function (btn) {
            btn.addEventListener('click', adminTogglePin);
        });
    }

    document.addEventListener('keydown', function (evt) {
        var overlay = document.getElementById('postImageLightbox');
        if (!overlay || overlay.hidden) return;
        if (evt.key === 'Escape') {
            evt.preventDefault();
            closeImageLightbox();
        } else if (evt.key === 'ArrowLeft') {
            evt.preventDefault();
            shiftImageLightbox(-1);
        } else if (evt.key === 'ArrowRight') {
            evt.preventDefault();
            shiftImageLightbox(1);
        }
    });

    async function loadPost() {
        if (!body) return;
        body.classList.remove('is-ready');
        body.classList.remove('is-entering');
        body.innerHTML = renderPostLoadingShell();
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
