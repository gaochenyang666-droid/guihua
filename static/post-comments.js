(function () {
    'use strict';

    window.GHPostCommentsFactory = function (deps) {
        deps = deps || {};

        var escapeAttr = deps.escapeAttr || function (v) { return String(v == null ? '' : v); };
        var mentionifyText = deps.mentionifyText || function (v) { return String(v == null ? '' : v); };
        var escapeHtml = deps.escapeHtml || function (v) { return String(v == null ? '' : v); };

        var INITIAL_COMMENT_BATCH = 6;
        var COMMENT_BATCH_SIZE = 6;

        function createState() {
            return {
                renderToken: 0,
                visibleCount: 0,
                sortMode: 'latest',
                showAuthorOnly: false,
                replyParentId: null,
                replyTargetName: '',
                replyDraftText: ''
            };
        }

        function isPostAuthor(post, user) {
            if (!post || !post.author || !user) return false;
            var postAuthor = post.author || {};
            if (postAuthor.id != null && user.id != null && Number(postAuthor.id) === Number(user.id)) return true;
            if (postAuthor.username && user.username && String(postAuthor.username) === String(user.username)) return true;
            return false;
        }

        function renderComments(list, depth, state, post) {
            depth = depth || 0;
            if (!Array.isArray(list) || !list.length) return '';
            return list.map(function (comment) {
                var author = (comment && comment.author) || {};
                var nick = author.nickname || '匿名';
                var created = comment && comment.created_at ? new Date(comment.created_at).toLocaleString() : '';
                var replies = renderComments(comment && comment.replies, depth + 1, state, post);
                var replyCount = Array.isArray(comment && comment.replies) ? comment.replies.length : 0;
                var collapseDeepReplies = depth >= 1 && replyCount > 0;
                var replyThreadId = 'reply-thread-' + Number(comment.id || 0) + '-' + depth;
                var margin = depth * 20;
                var border = depth > 0 ? '2px solid var(--border-color)' : 'none';
                var padding = depth > 0 ? '0.9rem' : '0';
                var authorTag = isPostAuthor(post, author) ? '<span class="comment-role-badge author">作者</span>' : '';
                var adminTag = author && author.is_admin ? '<span class="comment-role-badge admin">管理员</span>' : '';
                var commentClasses = ['comment-item'];
                if (isPostAuthor(post, author)) commentClasses.push('is-author-comment');
                if (author && author.is_admin) commentClasses.push('is-admin-comment');
                var inlineReplyComposer = state.replyParentId === Number(comment.id)
                    ? (
                        '<div class="inline-reply-box">' +
                            '<div class="inline-reply-title">回复 @' + escapeHtml(state.replyTargetName || nick) + '</div>' +
                            '<div class="inline-reply-actions">' +
                                '<input type="text" id="inlineReplyInput" class="form-input" placeholder="写下你的回复..." value="' + escapeAttr(state.replyDraftText || '') + '">' +
                                '<button class="btn btn-primary btn-sm comment-action-btn comment-action-btn-primary" type="button" data-action="submit-inline-reply">发送</button>' +
                                '<button class="btn btn-ghost btn-sm comment-action-btn" type="button" data-action="cancel-inline-reply">取消</button>' +
                            '</div>' +
                        '</div>'
                    )
                    : '';
                return (
                    '<div class="' + commentClasses.join(' ') + ' comment-depth-' + Math.min(depth, 4) + '" data-comment-depth="' + depth + '">' +
                    '<div class="comment-header"><div class="comment-author-line"><span class="comment-author-name">' + escapeHtml(nick) + '</span>' + authorTag + adminTag + '</div><span class="comment-time">' + escapeHtml(created) + '</span></div>' +
                    '<div class="comment-body-text">' + mentionifyText((comment && comment.content) || '') + '</div>' +
                    '<div class="comment-actions-row">' +
                        '<button class="btn btn-ghost btn-sm comment-action-btn" type="button" data-action="reply" data-parent-id="' + Number(comment.id) + '" data-nickname="' + escapeAttr(nick) + '">↩ 回复</button>' +
                        '<button class="btn btn-ghost btn-sm comment-action-btn" type="button" data-action="like-comment" data-comment-id="' + Number(comment.id) + '">' + ((comment && comment.is_liked) ? '👍 已赞' : '👍 点赞') + ' (' + Number((comment && comment.likes_count) || 0) + ')</button>' +
                    '</div>' +
                    inlineReplyComposer +
                    (collapseDeepReplies
                        ? '<div class="comment-thread-toggle-wrap"><button class="btn btn-ghost btn-sm comment-thread-toggle comment-action-btn" type="button" data-action="toggle-replies" data-target-id="' + replyThreadId + '" data-collapsed-label="展开 ' + replyCount + ' 条深层回复" data-expanded-label="收起深层回复" aria-expanded="false">展开 ' + replyCount + ' 条深层回复</button></div><div class="comment-thread-group" id="' + replyThreadId + '" hidden>' + replies + '</div>'
                        : replies) +
                    '</div>'
                );
            }).join('');
        }

        function renderLoadingState() {
            return '' +
                '<div class="comments-loading-state">' +
                    '<div class="skeleton-block skeleton-line"></div>' +
                    '<div class="skeleton-block skeleton-line short"></div>' +
                    '<div class="skeleton-block skeleton-line"></div>' +
                '</div>';
        }

        function getCommentTimestamp(comment) {
            if (!comment || !comment.created_at) return 0;
            var ts = new Date(comment.created_at).getTime();
            return Number.isFinite(ts) ? ts : 0;
        }

        function compareComments(state, a, b) {
            var mode = state.sortMode === 'hot' ? 'hot' : 'latest';
            if (mode === 'hot') {
                var hotDiff = Number((b && b.likes_count) || 0) - Number((a && a.likes_count) || 0);
                if (hotDiff !== 0) return hotDiff;
            }
            return getCommentTimestamp(b) - getCommentTimestamp(a);
        }

        function buildProcessedComment(state, post, comment) {
            if (!comment) return null;
            var sourceReplies = Array.isArray(comment.replies) ? comment.replies : [];
            var nextReplies = sourceReplies
                .map(function (item) { return buildProcessedComment(state, post, item); })
                .filter(Boolean)
                .sort(function (a, b) { return compareComments(state, a, b); });
            var authorMatch = isPostAuthor(post, comment.author || {});
            if (state.showAuthorOnly && !authorMatch && !nextReplies.length) return null;
            return Object.assign({}, comment, { replies: nextReplies });
        }

        function getProcessedComments(state, post) {
            var list = Array.isArray(post && post.comments) ? post.comments : [];
            return list
                .map(function (item) { return buildProcessedComment(state, post, item); })
                .filter(Boolean)
                .sort(function (a, b) { return compareComments(state, a, b); });
        }

        function resetVisibility(state, post) {
            var total = getProcessedComments(state, post).length;
            state.visibleCount = Math.min(INITIAL_COMMENT_BATCH, total);
        }

        function renderVisibleComments(state, post) {
            var list = getProcessedComments(state, post);
            var visible = list.slice(0, state.visibleCount || list.length);
            return renderComments(visible, 0, state, post);
        }

        function updateToolbar(state, post) {
            var latestBtn = document.getElementById('commentsSortLatestBtn');
            var hotBtn = document.getElementById('commentsSortHotBtn');
            var authorBtn = document.getElementById('commentsAuthorOnlyBtn');
            var meta = document.getElementById('commentsFilterMeta');
            var total = getProcessedComments(state, post).length;
            if (latestBtn) latestBtn.classList.toggle('active', state.sortMode === 'latest');
            if (hotBtn) hotBtn.classList.toggle('active', state.sortMode === 'hot');
            if (authorBtn) authorBtn.classList.toggle('active', !!state.showAuthorOnly);
            if (authorBtn) authorBtn.textContent = state.showAuthorOnly ? '查看全部回复' : '只看作者回复';
            if (meta) {
                var shown = Math.min(state.visibleCount || 0, total);
                meta.textContent = total ? ('已显示 ' + shown + ' / ' + total + ' 条') : '暂无评论';
            }
        }

        function updateMoreButton(state, post) {
            var btn = document.getElementById('commentsMoreBtn');
            if (!btn) return;
            var wrap = btn.parentElement;
            var total = getProcessedComments(state, post).length;
            if (!total || state.visibleCount >= total) {
                btn.hidden = true;
                btn.textContent = '';
                if (wrap) wrap.style.display = 'none';
                return;
            }
            var remain = Math.max(0, total - state.visibleCount);
            btn.hidden = false;
            btn.textContent = '展开更多评论（剩余 ' + remain + ' 条）';
            if (wrap) wrap.style.display = 'flex';
        }

        function scheduleRender(state, post, hooks) {
            hooks = hooks || {};
            state.renderToken += 1;
            var token = state.renderToken;
            var run = function () {
                if (token !== state.renderToken) return;
                var host = document.getElementById('postCommentsList');
                if (!host) return;
                var commentsHtml = renderVisibleComments(state, post);
                host.innerHTML = commentsHtml || '<div class="state-empty profile-inline-state">暂无评论</div>';
                Array.prototype.forEach.call(host.querySelectorAll('[data-comment-depth]'), function (node) {
                    var rawDepth = Number(node.getAttribute('data-comment-depth') || 0);
                    var margin = Math.max(0, rawDepth) * 20;
                    var border = rawDepth > 0 ? '2px solid var(--border-color)' : 'none';
                    var padding = rawDepth > 0 ? '0.9rem' : '0';
                    node.style.marginLeft = margin + 'px';
                    node.style.borderLeft = border;
                    node.style.paddingLeft = padding;
                });
                if (typeof hooks.bindEvents === 'function') hooks.bindEvents();
                updateToolbar(state, post);
                updateMoreButton(state, post);
                var inlineInput = document.getElementById('inlineReplyInput');
                if (inlineInput && state.replyParentId) inlineInput.focus();
            };
            if (window.requestAnimationFrame) {
                window.requestAnimationFrame(function () {
                    window.setTimeout(run, 40);
                });
                return;
            }
            window.setTimeout(run, 40);
        }

        function setReply(state, post, parentId, nickname, hooks) {
            state.replyParentId = parentId;
            state.replyTargetName = nickname || '匿名';
            state.replyDraftText = '';
            scheduleRender(state, post, hooks);
        }

        function cancelReply(state, post, hooks) {
            state.replyParentId = null;
            state.replyTargetName = '';
            state.replyDraftText = '';
            scheduleRender(state, post, hooks);
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

        function insertCommentIntoState(post, comment) {
            if (!post || !comment) return;
            post.comments = Array.isArray(post.comments) ? post.comments : [];
            comment.replies = Array.isArray(comment.replies) ? comment.replies : [];
            if (comment.parent_id) {
                var parent = findCommentNode(post.comments, comment.parent_id);
                if (parent) {
                    parent.replies = Array.isArray(parent.replies) ? parent.replies : [];
                    parent.replies.unshift(comment);
                    return;
                }
            }
            post.comments.unshift(comment);
        }

        async function submitComment(state, post, ctx) {
            ctx = ctx || {};
            if (typeof ctx.requireLogin === 'function' && !ctx.requireLogin()) return;
            if (!post) return;
            var input = state.replyParentId ? document.getElementById('inlineReplyInput') : document.getElementById('commentInput');
            var submitBtn = state.replyParentId
                ? ctx.body && ctx.body.querySelector('[data-action="submit-inline-reply"]')
                : document.getElementById('commentSendBtn');
            if (!input) return;
            var content = (input.value || '').trim();
            if (!content) {
                if (ctx.toastError) ctx.toastError('评论不能为空');
                return;
            }
            if (state.replyParentId) state.replyDraftText = content;
            input.disabled = true;
            if (submitBtn) submitBtn.disabled = true;
            var payload = { content: content };
            if (state.replyParentId) payload.parent_id = state.replyParentId;
            var result = await ctx.requestJson(ctx.apiBase + '/posts/' + ctx.postId + '/comments', {
                method: 'POST',
                body: payload
            });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                input.disabled = false;
                if (submitBtn) submitBtn.disabled = false;
                if (ctx.toastError) ctx.toastError(data.error || '评论失败');
                return;
            }
            input.value = '';
            input.disabled = false;
            if (submitBtn) submitBtn.disabled = false;
            insertCommentIntoState(post, data && data.comment);
            if (!state.replyParentId) {
                var nextTotal = getProcessedComments(state, post).length;
                state.visibleCount = Math.min(nextTotal, Math.max(state.visibleCount + 1, INITIAL_COMMENT_BATCH));
            }
            cancelReply(state, post, ctx.renderHooks);
        }

        async function likeComment(state, post, commentId, ctx) {
            ctx = ctx || {};
            if (typeof ctx.requireLogin === 'function' && !ctx.requireLogin()) return;
            var cid = Number(commentId);
            if (!Number.isFinite(cid) || cid <= 0) return;
            var result = await ctx.requestJson(ctx.apiBase + '/comments/' + cid + '/like', {
                method: 'POST',
                body: {}
            });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                if (ctx.toastError) ctx.toastError(data.error || '操作失败');
                return;
            }
            var target = findCommentNode(post && post.comments, cid);
            if (target) {
                target.is_liked = !!data.liked;
                target.likes_count = Number(data.likes_count || 0);
                scheduleRender(state, post, ctx.renderHooks);
            }
        }

        function loadMoreComments(state, post, hooks) {
            var total = getProcessedComments(state, post).length;
            if (!total) return;
            state.visibleCount = Math.min(total, state.visibleCount + COMMENT_BATCH_SIZE);
            scheduleRender(state, post, hooks);
        }

        function changeSort(state, post, mode, hooks) {
            var nextMode = mode === 'hot' ? 'hot' : 'latest';
            if (state.sortMode === nextMode) return;
            state.sortMode = nextMode;
            resetVisibility(state, post);
            scheduleRender(state, post, hooks);
        }

        function toggleAuthorOnly(state, post, hooks) {
            state.showAuthorOnly = !state.showAuthorOnly;
            resetVisibility(state, post);
            scheduleRender(state, post, hooks);
        }

        function bindListEvents(state, post, ctx) {
            ctx = ctx || {};
            var body = ctx.body;
            if (!body) return;
            Array.prototype.forEach.call(body.querySelectorAll('[data-action="reply"]'), function (btn) {
                btn.addEventListener('click', function () {
                    var pid = Number(btn.getAttribute('data-parent-id'));
                    var nick = btn.getAttribute('data-nickname') || '匿名';
                    setReply(state, post, pid, nick, ctx.renderHooks);
                });
            });
            Array.prototype.forEach.call(body.querySelectorAll('#inlineReplyInput'), function (input) {
                input.addEventListener('input', function () {
                    state.replyDraftText = input.value || '';
                });
                input.addEventListener('keydown', function (evt) {
                    if (evt.key === 'Enter' && !evt.shiftKey) {
                        evt.preventDefault();
                        submitComment(state, post, ctx);
                    }
                });
            });
            Array.prototype.forEach.call(body.querySelectorAll('[data-action="like-comment"]'), function (btn) {
                btn.addEventListener('click', function () {
                    likeComment(state, post, btn.getAttribute('data-comment-id'), ctx);
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
                    changeSort(state, post, btn.getAttribute('data-sort-mode'), ctx.renderHooks);
                });
            });
            Array.prototype.forEach.call(body.querySelectorAll('[data-action="toggle-author-comments"]'), function (btn) {
                btn.addEventListener('click', function () {
                    toggleAuthorOnly(state, post, ctx.renderHooks);
                });
            });
        }

        return {
            createState: createState,
            renderLoadingState: renderLoadingState,
            resetVisibility: resetVisibility,
            scheduleRender: scheduleRender,
            submitComment: submitComment,
            bindListEvents: bindListEvents,
            loadMoreComments: loadMoreComments,
            cancelReply: cancelReply
        };
    };
})();
