(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var root = document.querySelector('.post-page-shell');
    var body = document.getElementById('postPageBody');
    var postId = Number(root && root.getAttribute('data-post-id'));
    var currentUser = null;
    var currentPost = null;

    var apiJson = window.apiJson;
    var escapeAttr = window.escapeAttr;
    var mentionifyText = window.mentionifyText;
    var renderAuthorBadge = window.renderAuthorBadge;
    var postCommentsFactory = window.GHPostCommentsFactory;
    var postLightboxFactory = window.GHPostLightboxFactory;
    var postComments = postCommentsFactory ? postCommentsFactory({
        escapeAttr: escapeAttr,
        mentionifyText: mentionifyText,
        escapeHtml: window.escapeHtml
    }) : null;
    var postLightbox = postLightboxFactory ? postLightboxFactory() : null;
    var commentsState = postComments ? postComments.createState() : null;
    var lightboxState = postLightbox ? postLightbox.createState() : null;

    function toastError(msg) {
        if (window.Toast && Toast.error) Toast.error(msg || '操作失败');
    }

    function toastSuccess(msg) {
        if (window.Toast && Toast.success) Toast.success(msg || '操作成功');
    }

    async function requestJson(url, opts) {
        opts = opts || {};
        return apiJson(url, Object.assign({ fallback: {} }, opts));
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

    async function copyText(text, successMessage) {
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                var ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            toastSuccess(successMessage || '已复制');
        } catch (_) {
            toastError('复制失败，请稍后重试');
        }
    }

    function requireLogin() {
        if (currentUser) return true;
        toastError('请先登录');
        if (typeof navigateWithTransition === 'function') navigateWithTransition('/');
        else window.location.href = '/';
        return false;
    }

    async function loadCurrentUser() {
        try {
            var result = await requestJson(API_BASE + '/user/me', {
                check401: false
            });
            var res = result.res;
            var data = result.data;
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

    function scheduleCommentsRender(post) {
        if (!postComments || !commentsState) return;
        postComments.scheduleRender(commentsState, post, {
            bindEvents: bindCommentListEvents
        });
    }

    function renderSeries(series) {
        if (!Array.isArray(series) || !series.length) return '';
        return series.map(function (s) {
            return (
                '<div class="series-block">' +
                '<div class="series-block-title">📚 所属系列：<a class="series-block-link" href="/series/' + Number(s.series_id) + '" data-no-transition="1">' + escapeHtml(s.title || '') + '</a> · 第 ' + Number(s.order_index || 0) + ' 篇</div>' +
                '<div class="series-block-actions">' +
                (s.prev_post_id ? '<a class="btn btn-ghost btn-sm" href="/post/' + Number(s.prev_post_id) + '" data-no-transition="1">⬅️ 上一篇</a>' : '') +
                (s.next_post_id ? '<a class="btn btn-ghost btn-sm" href="/post/' + Number(s.next_post_id) + '" data-no-transition="1">➡️ 下一篇</a>' : '') +
                '</div>' +
                '</div>'
            );
        }).join('');
    }

    function renderPost(p) {
        currentPost = p;
        if (postComments && commentsState) {
            postComments.resetVisibility(commentsState, p);
        }
        var isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
        var seriesHtml = renderSeries(p.series || []);
        var canComment = !!(p.allow_comments || (currentUser && currentUser.is_admin));
        var meta = [
            (p.is_special_announcement ? '<span class="post-meta-flag post-meta-flag-warning">📜 长公告</span>' : ''),
            (p.is_pinned ? '<span class="post-meta-flag post-meta-flag-pinned">📌 置顶</span>' : ''),
            '发布者: ' + escapeHtml((p.author && p.author.nickname) || '用户') + ' ' + renderAuthorBadge(p.author) + ' ' + ((p.author && p.author.id != null) ? formatUserId(p.author.id, p.author) : ''),
            '浏览: ' + Number(p.view_count || 0)
        ].filter(Boolean).join(' | ');
        var adminControls = '';
        if (currentUser && currentUser.is_admin) {
            adminControls =
                '<div class="post-admin-panel">' +
                    '<div class="post-admin-title">👮 管理员操作</div>' +
                    '<div class="post-admin-actions">' +
                        '<button class="btn btn-ghost btn-sm post-admin-danger" type="button" data-action="admin-delete">删除帖子</button>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-toggle-hide">' + (p.is_hidden ? '取消隐藏' : '隐藏帖子') + '</button>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="admin-toggle-comments">' + (p.allow_comments ? '关闭评论' : '开启评论') + '</button>' +
                        '<button class="btn btn-ghost btn-sm post-admin-pin" type="button" data-action="admin-toggle-pin">' + (p.is_pinned ? '取消置顶' : '设为置顶') + '</button>' +
                    '</div>' +
                '</div>';
        }

        body.innerHTML = '' +
            '<h2 class="post-detail-title">' + escapeHtml(p.title || '') + '</h2>' +
            '<div class="post-detail-meta-row">' + meta + '</div>' +
            '<article class="post-detail-content">' + (typeof DOMPurify !== 'undefined' ? DOMPurify.sanitize((p.content == null) ? '' : String(p.content)) : ((p.content == null) ? '' : String(p.content))) + '</article>' +
            (p.ipfs_cid ? (
                '<section class="post-arweave-footer glass">' +
                    '<div class="post-arweave-footer-head">' +
                        '<div>' +
                            '<div class="post-arweave-label">Arweave TX ID</div>' +
                            '<div class="post-arweave-sub">文章末尾保留这条永存档案编号，便于核验与备份。</div>' +
                        '</div>' +
                        '<button class="btn btn-ghost btn-sm" type="button" data-action="copy-arweave" data-arweave-tx="' + escapeAttr(p.ipfs_cid) + '">复制 TX ID</button>' +
                    '</div>' +
                    '<div class="post-arweave-value">' + escapeHtml(String(p.ipfs_cid)) + '</div>' +
                    '<div class="post-arweave-links">' +
                        '<a href="https://arweave.net/' + escapeAttr(p.ipfs_cid) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">打开 Arweave 档案</a>' +
                        (p.tx_hash ? '<a href="https://bscscan.com/tx/' + escapeAttr(p.tx_hash) + '" target="_blank" rel="noopener" class="btn btn-ghost btn-sm">查看支付凭证</a>' : '') +
                    '</div>' +
                '</section>'
            ) : '') +
            '<div class="on-chain-evidence">' +
                '<div class="on-chain-evidence-status">' + (isPermanent ? '✅ 已永久保存 · 链上可验' : 'ℹ️ 当前帖子暂未永存') + '</div>' +
                '<div class="on-chain-evidence-links">' +
                    (p.tx_hash ? '<a class="on-chain-link on-chain-link-payment" href="https://bscscan.com/tx/' + escapeAttr(p.tx_hash) + '" target="_blank" rel="noopener">⛓ 支付凭证 BSCScan</a>' : '<span class="on-chain-link-muted">无支付凭证</span>') +
                    (p.ipfs_cid ? '<a class="on-chain-link on-chain-link-storage" href="https://arweave.net/' + escapeAttr(p.ipfs_cid) + '" target="_blank" rel="noopener">💾 永存档案</a>' : '') +
                '</div>' +
            '</div>' +
            seriesHtml +
            '<div class="post-detail-actions">' +
                '<button class="btn btn-ghost" type="button" data-action="like">😰 恐惧 (' + Number(p.likes_count || 0) + ')</button>' +
                '<button class="btn btn-ghost" type="button" data-action="bookmark">⭐ 收藏' + (p.is_bookmarked ? '（已收）' : '') + '</button>' +
                '<button class="btn btn-ghost" type="button" data-action="share">🔗 分享</button>' +
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
                '<div id="postCommentsList" class="post-comments-list">' + (postComments ? postComments.renderLoadingState() : '') + '</div>' +
                '<div class="comments-more-wrap"><button class="btn btn-ghost btn-sm" id="commentsMoreBtn" type="button" data-action="more-comments" hidden></button></div>' +
                '<div class="post-comment-compose">' +
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

    function updatePostActionButtons() {
        if (!body || !currentPost) return;
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.textContent = '😰 恐惧 (' + Number(currentPost.likes_count || 0) + ')';
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.textContent = '⭐ 收藏' + (currentPost.is_bookmarked ? '（已收）' : '');
        });
    }

    async function doPost(url, payload, extraOpts) {
        return requestJson(url, Object.assign({
            method: 'POST',
            body: payload
        }, extraOpts || {}));
    }

    async function likePost() {
        if (!requireLogin()) return;
        var result = await doPost(API_BASE + '/posts/' + postId + '/like');
        var res = result.res;
        var data = result.data;
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
        var result = await doPost(API_BASE + '/posts/' + postId + '/bookmark');
        var res = result.res;
        var data = result.data;
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
        var result = await doPost(API_BASE + '/reports', { post_id: postId, reason: reason.trim() });
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError(data.error || '举报失败');
            return;
        }
        toastSuccess(data.message || '举报已提交');
    }

    async function adminDeletePost() {
        if (!currentUser || !currentUser.is_admin) return;
        if (!confirm('确定要删除这个帖子吗？此操作不可逆。')) return;
        var result = await requestJson(API_BASE + '/posts/' + postId, {
            method: 'DELETE',
            check401: false
        });
        var res = result.res;
        var data = result.data;
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
        var result = await doPost(API_BASE + '/admin/posts/' + postId + '/hide');
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        toastSuccess(data.message || '状态已更新');
        await loadPost();
    }

    async function adminToggleComments() {
        if (!currentUser || !currentUser.is_admin) return;
        var result = await doPost(API_BASE + '/admin/posts/' + postId + '/toggle-comments');
        var res = result.res;
        var data = result.data;
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
        var result = await doPost(API_BASE + '/admin/posts/' + postId + '/pin', {
            pinned: nextPinned,
            exclusive: true
        });
        var res = result.res;
        var data = result.data;
        if (!res.ok) {
            toastError(data.error || '操作失败');
            return;
        }
        toastSuccess(nextPinned ? '已置顶' : '已取消置顶');
        await loadPost();
    }

    function bindCommentListEvents() {
        if (!postComments || !commentsState || !currentPost) return;
        postComments.bindListEvents(commentsState, currentPost, {
            body: body,
            apiBase: API_BASE,
            postId: postId,
            requireLogin: requireLogin,
            requestJson: requestJson,
            toastError: toastError,
            renderHooks: {
                bindEvents: bindCommentListEvents
            }
        });
    }

    function bindPostEvents() {
        if (!body) return;
        if (postLightbox && lightboxState) postLightbox.bindContentImages(body, lightboxState);
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="like"]'), function (btn) {
            btn.addEventListener('click', likePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="bookmark"]'), function (btn) {
            btn.addEventListener('click', bookmarkPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="share"]'), function (btn) {
            btn.addEventListener('click', sharePost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="copy-arweave"]'), function (btn) {
            btn.addEventListener('click', function () {
                var tx = btn.getAttribute('data-arweave-tx') || '';
                if (!tx) {
                    toastError('缺少 Arweave TX ID');
                    return;
                }
                copyText(tx, '已复制 Arweave TX ID');
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="report"]'), function (btn) {
            btn.addEventListener('click', reportPost);
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="comment"]'), function (btn) {
            btn.addEventListener('click', function () {
                if (!postComments || !commentsState) return;
                postComments.submitComment(commentsState, currentPost, {
                    body: body,
                    apiBase: API_BASE,
                    postId: postId,
                    requireLogin: requireLogin,
                    requestJson: requestJson,
                    toastError: toastError,
                    renderHooks: {
                        bindEvents: bindCommentListEvents
                    }
                });
            });
        });
        var rootCommentInput = document.getElementById('commentInput');
        if (rootCommentInput) {
            rootCommentInput.addEventListener('keydown', function (evt) {
                if (evt.key === 'Enter' && !evt.shiftKey) {
                    evt.preventDefault();
                    if (!postComments || !commentsState) return;
                    postComments.submitComment(commentsState, currentPost, {
                        body: body,
                        apiBase: API_BASE,
                        postId: postId,
                        requireLogin: requireLogin,
                        requestJson: requestJson,
                        toastError: toastError,
                        renderHooks: {
                            bindEvents: bindCommentListEvents
                        }
                    });
                }
            });
        }
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="submit-inline-reply"]'), function (btn) {
            btn.addEventListener('click', function () {
                if (!postComments || !commentsState) return;
                postComments.submitComment(commentsState, currentPost, {
                    body: body,
                    apiBase: API_BASE,
                    postId: postId,
                    requireLogin: requireLogin,
                    requestJson: requestJson,
                    toastError: toastError,
                    renderHooks: {
                        bindEvents: bindCommentListEvents
                    }
                });
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="cancel-inline-reply"]'), function (btn) {
            btn.addEventListener('click', function () {
                if (!postComments || !commentsState) return;
                postComments.cancelReply(commentsState, currentPost, {
                    bindEvents: bindCommentListEvents
                });
            });
        });
        Array.prototype.forEach.call(body.querySelectorAll('[data-action="more-comments"]'), function (btn) {
            btn.addEventListener('click', function () {
                if (!postComments || !commentsState) return;
                postComments.loadMoreComments(commentsState, currentPost, {
                    bindEvents: bindCommentListEvents
                });
            });
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
        if (postLightbox && lightboxState) postLightbox.handleKeydown(lightboxState, evt);
    });

    async function loadPost() {
        if (!body) return;
        body.classList.remove('is-ready');
        body.classList.remove('is-entering');
        body.innerHTML = renderPostLoadingShell();
        try {
            var result = await requestJson(API_BASE + '/posts/' + postId, {
                check401: false
            });
            var res = result.res;
            var data = result.data;
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
