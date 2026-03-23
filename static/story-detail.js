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
        comments.resetVisibility(state, currentPost);
        comments.scheduleRender(state, currentPost, { bindEvents: bindCommentListEvents });
    }

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
})();
