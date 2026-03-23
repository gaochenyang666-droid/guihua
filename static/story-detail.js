(function () {
    'use strict';

    var root = document.querySelector('.story-x-shell[data-post-id]');
    if (!root || !window.GHPostCommentsFactory || !window.apiJson) return;

    var postId = Number(root.getAttribute('data-post-id') || 0);
    if (!Number.isFinite(postId) || postId <= 0) return;

    var body = document.querySelector('.story-comments-section');
    if (!body) return;

    var comments = window.GHPostCommentsFactory({
        escapeAttr: window.escapeAttr,
        escapeHtml: window.escapeHtml,
        mentionifyText: window.mentionifyText
    });
    var state = comments.createState();
    var currentPost = null;
    var backBtn = document.getElementById('storyBackBtn');

    if (backBtn) {
        backBtn.addEventListener('click', function (evt) {
            try {
                var ref = document.referrer ? new URL(document.referrer) : null;
                if (ref && ref.origin === window.location.origin && window.history.length > 1) {
                    evt.preventDefault();
                    window.history.back();
                }
            } catch (_) {
                // Fall back to the anchor href.
            }
        });
    }

    function toastError(msg) {
        if (window.Toast && window.Toast.error) window.Toast.error(msg || '操作失败');
    }

    function toastSuccess(msg) {
        if (window.Toast && window.Toast.success) window.Toast.success(msg || '操作成功');
    }

    function requestJson(url, opts) {
        return window.apiJson(url, Object.assign({ fallback: {} }, opts || {}));
    }

    async function doPost(url, payload) {
        return requestJson(url, { method: 'POST', body: payload });
    }

    function countAllComments(list) {
        if (!Array.isArray(list) || !list.length) return 0;
        return list.reduce(function (total, item) {
            return total + 1 + countAllComments(item && item.replies);
        }, 0);
    }

    function updateCommentsHeader() {
        var countEl = document.getElementById('storyCommentsCount');
        if (!countEl) return;
        var total = countAllComments(currentPost && currentPost.comments);
        countEl.textContent = String(total);
    }

    function updateActionButtons() {
        if (!currentPost) return;
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.textContent = '😰 恐惧 (' + Number(currentPost.likes_count || 0) + ')';
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.textContent = '⭐ 收藏' + (currentPost.is_bookmarked ? '（已收）' : '');
        });
    }

    async function likePost() {
        var result = await doPost('/api/posts/' + postId + '/like');
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError((data && (data.error || data.message)) || '操作失败');
            return;
        }
        var isLiked = String((data && data.message) || '').toLowerCase().indexOf('unlike') === -1;
        currentPost.likes_count = Math.max(0, Number(currentPost.likes_count || 0) + (isLiked ? 1 : -1));
        updateActionButtons();
    }

    async function bookmarkPost() {
        var result = await doPost('/api/posts/' + postId + '/bookmark');
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError((data && (data.error || data.message)) || '操作失败');
            return;
        }
        currentPost.is_bookmarked = String((data && data.message) || '').toLowerCase().indexOf('unbook') === -1;
        updateActionButtons();
    }

    async function reportPost() {
        var reason = window.prompt('请简要说明举报原因（违规内容、广告、抄袭等）：');
        if (reason == null || !reason.trim()) return;
        if (reason.length > 500) {
            toastError('原因最多500字');
            return;
        }
        var result = await doPost('/api/reports', { post_id: postId, reason: reason.trim() });
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError((data && (data.error || data.message)) || '举报失败');
            return;
        }
        toastSuccess((data && data.message) || '举报已提交');
    }

    async function sharePost() {
        var url = window.location.href;
        var title = (currentPost && currentPost.title) || document.title || '诡话';
        if (navigator.share) {
            try {
                await navigator.share({ title: title, text: title, url: url });
                return;
            } catch (err) {
                if (err && err.name === 'AbortError') return;
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
            toastError('转发失败，请稍后重试');
        }
    }

    function bindCommentListEvents() {
        if (!currentPost) return;
        comments.bindListEvents(state, currentPost, {
            body: body,
            apiBase: '/api',
            postId: postId,
            requestJson: window.apiJson,
            toastError: window.Toast && window.Toast.error ? window.Toast.error : null,
            requireLogin: function () { return true; },
            renderHooks: { bindEvents: bindCommentListEvents }
        });
    }

    function bindStaticControls() {
        var sendBtn = document.getElementById('commentSendBtn');
        var input = document.getElementById('commentInput');
        var moreBtn = document.getElementById('commentsMoreBtn');
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.addEventListener('click', likePost);
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.addEventListener('click', bookmarkPost);
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="share"]'), function (btn) {
            btn.addEventListener('click', sharePost);
        });
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="report"]'), function (btn) {
            btn.addEventListener('click', reportPost);
        });
        if (sendBtn) {
            sendBtn.addEventListener('click', function () {
                if (!currentPost) return;
                comments.submitComment(state, currentPost, {
                    body: body,
                    apiBase: '/api',
                    postId: postId,
                    requestJson: window.apiJson,
                    toastError: window.Toast && window.Toast.error ? window.Toast.error : null,
                    requireLogin: function () { return true; },
                    renderHooks: { bindEvents: bindCommentListEvents }
                });
            });
        }
        if (input) {
            input.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && !evt.shiftKey) {
                    evt.preventDefault();
                    if (sendBtn) sendBtn.click();
                }
            });
        }
        if (moreBtn) {
            moreBtn.addEventListener('click', function () {
                if (!currentPost) return;
                comments.loadMoreComments(state, currentPost, { bindEvents: bindCommentListEvents });
            });
        }
    }

    function renderPostComments(post) {
        currentPost = post || {};
        var commentInput = document.getElementById('commentInput');
        var commentSendBtn = document.getElementById('commentSendBtn');
        var canComment = !!currentPost.allow_comments;
        if (commentInput) {
            commentInput.disabled = !canComment;
            commentInput.placeholder = canComment ? '写下你的评论...' : '评论区已关闭';
        }
        if (commentSendBtn) commentSendBtn.disabled = !canComment;
        comments.resetVisibility(state, currentPost);
        comments.scheduleRender(state, currentPost, { bindEvents: bindCommentListEvents });
        updateActionButtons();
        updateCommentsHeader();
    }

    try {
        var seedEl = document.getElementById('storyCommentsSeed');
        var seedText = seedEl ? (seedEl.textContent || '').trim() : '';
        if (seedText) {
            renderPostComments(JSON.parse(seedText));
            bindStaticControls();
        } else {
            throw new Error('缺少评论种子数据');
        }
    } catch (_) {
        window.apiJson('/api/posts/' + postId, { method: 'GET' })
            .then(function (result) {
                if (!result || !result.res || !result.res.ok) {
                    throw new Error((result && result.data && (result.data.error || result.data.message)) || '加载评论失败');
                }
                renderPostComments(result.data || {});
                bindStaticControls();
            })
            .catch(function (err) {
                var host = document.getElementById('postCommentsList');
                if (host) host.innerHTML = '<div class="state-error profile-inline-state">' + window.escapeHtml(err && err.message ? err.message : '加载评论失败') + '</div>';
            });
    }
})();
