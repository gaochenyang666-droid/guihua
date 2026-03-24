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

    function getCurrentUser() {
        var user = window.currentUser;
        if (user && (user.address || user.wallet_address || user.username)) return Promise.resolve(user);
        return requestJson('/api/user/me', { method: 'GET', check401: false }).then(function (result) {
            if (!result || !result.res || !result.res.ok) return null;
            window.currentUser = result.data || null;
            return window.currentUser;
        }).catch(function () {
            return null;
        });
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

    function getAuthorWallet() {
        var author = currentPost && currentPost.author;
        if (!author) return '';
        return String(author.wallet_address || author.address || '').trim();
    }

    function openTipModal() {
        var modal = document.getElementById('tipAuthorModal');
        if (!modal) return;
        var wallet = getAuthorWallet();
        var displayEl = document.getElementById('tipAuthorAddressDisplay');
        var copyBtn = document.getElementById('tipAuthorCopyBtn');
        var sendBtn = modal.querySelector('[data-action="tip-author-send"]');
        if (displayEl) {
            displayEl.textContent = wallet || '作者未绑定钱包，暂无法打赏';
            displayEl.style.color = wallet ? 'var(--accent-green)' : 'var(--text-muted)';
        }
        if (copyBtn) copyBtn.hidden = !wallet;
        if (sendBtn) sendBtn.disabled = !wallet;
        modal.classList.add('active');
    }

    function closeTipModal() {
        var modal = document.getElementById('tipAuthorModal');
        if (modal) modal.classList.remove('active');
    }

    async function copyTipAddress() {
        var wallet = getAuthorWallet();
        if (!wallet) {
            toastError('作者未绑定钱包');
            return;
        }
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(wallet);
            } else {
                var ta = document.createElement('textarea');
                ta.value = wallet;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            toastSuccess('已复制收款地址');
        } catch (_) {
            toastError('复制失败，请手动复制');
        }
    }

    async function sendTip() {
        var wallet = getAuthorWallet();
        if (!wallet) {
            toastError('作者未绑定钱包，暂无法打赏');
            return;
        }
        var currentUser = await getCurrentUser();
        if (!currentUser || !(currentUser.address || currentUser.wallet_address)) {
            window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
            return;
        }
        var input = document.getElementById('tipAmountInput');
        var amountUsdt = parseFloat(((input && input.value) || '1').trim());
        if (isNaN(amountUsdt) || amountUsdt < 1) {
            toastError('打赏金额至少 1 USDT');
            return;
        }
        var provider = window.BinanceChain || window.ethereum;
        if (!provider || !window.Web3) {
            await copyTipAddress();
            toastSuccess('已复制作者地址，请在钱包内手动转账');
            return;
        }
        try {
            var configResult = await requestJson('/api/config/fees', { method: 'GET', check401: false });
            if (!configResult.res.ok || !configResult.data || !configResult.data.usdt_contract) {
                toastError('无法获取 USDT 合约配置');
                return;
            }
            var web3 = new window.Web3(provider);
            var fromAddr = currentUser.address || currentUser.wallet_address;
            var amountRaw = web3.utils.toBN(web3.utils.toWei(amountUsdt.toString(), 'ether'));
            var sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
            var paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [wallet, amountRaw]);
            var txData = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
            var txHash = await provider.request({
                method: 'eth_sendTransaction',
                params: [{
                    to: configResult.data.usdt_contract,
                    from: fromAddr,
                    value: '0x0',
                    data: txData,
                    gas: web3.utils.toHex(100000)
                }]
            });
            if (!txHash) {
                toastError('打赏取消');
                return;
            }
            toastSuccess('交易已发送，正在确认...');
            var verifyResult = await requestJson('/api/tips/verify', {
                method: 'POST',
                body: { tx_hash: txHash, post_id: postId },
                check401: false
            });
            if (!verifyResult.res.ok) {
                toastError((verifyResult.data && verifyResult.data.error) || '验证失败');
                return;
            }
            toastSuccess('打赏成功！');
            closeTipModal();
        } catch (err) {
            if (err && err.code === 4001) toastError('已取消打赏');
            else toastError((err && err.message) || '打赏失败');
        }
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
        Array.prototype.forEach.call(document.querySelectorAll('[data-action="tip-author"]'), function (btn) {
            btn.addEventListener('click', openTipModal);
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
        document.addEventListener('click', function (evt) {
            var actionEl = evt.target && evt.target.closest ? evt.target.closest('[data-action]') : null;
            if (!actionEl) return;
            var action = actionEl.getAttribute('data-action') || '';
            if (action === 'tip-author-copy') {
                evt.preventDefault();
                copyTipAddress();
            } else if (action === 'tip-amount-preset') {
                var tipInput = document.getElementById('tipAmountInput');
                if (tipInput) {
                    evt.preventDefault();
                    tipInput.value = actionEl.getAttribute('data-amount') || '1';
                }
            } else if (action === 'tip-author-send') {
                evt.preventDefault();
                sendTip();
            }
            var dismissId = actionEl.getAttribute('data-dismiss');
            if (dismissId === 'tipAuthorModal') {
                evt.preventDefault();
                closeTipModal();
            }
        });
        var tipModal = document.getElementById('tipAuthorModal');
        if (tipModal) {
            tipModal.addEventListener('click', function (evt) {
                if (evt.target === tipModal) closeTipModal();
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
