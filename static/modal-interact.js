(function () {
    'use strict';

    window.GHModalInteractFactory = function GHModalInteractFactory(deps) {
        var API_BASE = deps.API_BASE;
        var getCurrentUser = deps.getCurrentUser;
        var parseJsonSafe = deps.parseJsonSafe;
        var Toast = deps.Toast;
        var detailScrollStore = deps.detailScrollStore;
        var navigateWithTransition = deps.navigateWithTransition;
        var getUI = deps.getUI;

        var tipAuthorPostId = null;
        var tipAuthorWallet = '';
        var currentDetailPostId = null;
        var currentDetailRequestSeq = 0;

        async function copyTextWithFallback(text, successMsg) {
            var safeText = (text || '').trim();
            if (!safeText) return false;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(safeText);
                } else {
                    var ta = document.createElement('textarea');
                    ta.value = safeText;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }
                if (successMsg && Toast) Toast.success(successMsg);
                return true;
            } catch (_) {
                return false;
            }
        }

        async function ensureWalletProvider(fallbackAddress) {
            var provider = window.BinanceChain || window.ethereum;
            if (provider) return provider;
            if (fallbackAddress) {
                await copyTextWithFallback(fallbackAddress, '已复制收款地址，可手动转账');
            }
            Toast.info('未检测到钱包，请用钱包 App 内置浏览器打开本站后再支付');
            return null;
        }

        var Modal = {
            open(id, opts) {
                opts = opts || {};
                if (id === 'loginModal') {
                    if (typeof openLoginPage === 'function') openLoginPage();
                    else window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
                    return;
                }
                var overlay = document.getElementById(id);
                if (!overlay) return;
                var modalEl = overlay.querySelector('.modal');
                if (id === 'postDetailModal') {
                    var anchorY = Number.isFinite(opts.anchorY) ? Number(opts.anchorY) : null;
                    var offset = 0;
                    if (anchorY !== null) {
                        var overlayStyle = window.getComputedStyle(overlay);
                        var padTop = parseFloat(overlayStyle.paddingTop || '0') || 0;
                        var viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
                        var desired = anchorY - padTop - 28;
                        var maxOffset = Math.max(0, viewportH - padTop - 140);
                        offset = Math.max(0, Math.min(desired, maxOffset));
                    }
                    overlay.style.setProperty('--detail-open-offset', String(Math.round(offset)) + 'px');
                    if (modalEl) modalEl.style.marginTop = String(Math.round(offset)) + 'px';
                }
                overlay.classList.add('active');
                overlay.scrollTop = 0;
                if (modalEl) modalEl.scrollTop = 0;
                var savedScrollY = Number.isFinite(opts.savedScrollY) ? opts.savedScrollY : null;
                if (id === 'postDetailModal' && savedScrollY !== null) {
                    var restore = function () {
                        if (window.scrollY !== savedScrollY) window.scrollTo(0, savedScrollY);
                    };
                    requestAnimationFrame(restore);
                    setTimeout(restore, 50);
                    setTimeout(restore, 150);
                }
            },

            close(id) {
                var overlay = document.getElementById(id);
                if (!overlay) return;
                if (id === 'postDetailModal') {
                    var modalScrollEl = document.querySelector('#postDetailModal .modal');
                    if (modalScrollEl && currentDetailPostId) {
                        var maxScroll = Math.max(0, modalScrollEl.scrollHeight - modalScrollEl.clientHeight);
                        detailScrollStore.save(currentDetailPostId, modalScrollEl.scrollTop, maxScroll);
                        detailScrollStore.unbind(modalScrollEl);
                    }
                    currentDetailPostId = null;
                    currentDetailRequestSeq += 1;
                }
                overlay.classList.remove('active');
                overlay.scrollTop = 0;
                if (id === 'postDetailModal') {
                    overlay.style.removeProperty('--detail-open-offset');
                    var modalEl = overlay.querySelector('.modal');
                    if (modalEl) modalEl.style.removeProperty('margin-top');
                }
            },

            async openDetail(evtOrId, idMaybe) {
                var isEventLike = !!(evtOrId && typeof evtOrId === 'object' && typeof evtOrId.preventDefault === 'function');
                if (isEventLike) {
                    evtOrId.preventDefault();
                    evtOrId.stopPropagation();
                }
                var targetIdRaw = isEventLike ? idMaybe : evtOrId;
                var targetId = Number(targetIdRaw);
                if (!Number.isFinite(targetId) || targetId <= 0) return;
                var next = '/post/' + targetId;
                if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                else window.location.href = next;
            }
        };

        var TipAuthor = {
            open(postId, authorWallet) {
                tipAuthorPostId = postId;
                tipAuthorWallet = (authorWallet || '').trim();
                var displayEl = document.getElementById('tipAuthorAddressDisplay');
                var copyBtn = document.getElementById('tipAuthorCopyBtn');
                var sendBtn = document.querySelector('#tipAuthorModal .btn-primary');
                if (displayEl) {
                    displayEl.textContent = tipAuthorWallet ? tipAuthorWallet : '作者未绑定钱包，暂无法打赏';
                    displayEl.style.color = tipAuthorWallet ? 'var(--accent-green)' : 'var(--text-muted)';
                }
                if (copyBtn) copyBtn.style.display = tipAuthorWallet ? 'inline-block' : 'none';
                if (sendBtn) {
                    sendBtn.disabled = !tipAuthorWallet;
                    sendBtn.style.opacity = tipAuthorWallet ? '1' : '0.5';
                }
                var input = document.getElementById('tipAmountInput');
                if (input) input.value = '1';
                Modal.open('tipAuthorModal');
            },
            copyAddress() {
                if (!tipAuthorWallet) return;
                copyTextWithFallback(tipAuthorWallet, '已复制收款地址');
            },
            async send() {
                var currentUser = getCurrentUser();
                if (!tipAuthorPostId || !currentUser || !currentUser.address) {
                    Toast.error('请先登录（钱包）');
                    return;
                }
                if (!tipAuthorWallet) {
                    Toast.error('作者未绑定钱包，暂无法打赏');
                    return;
                }
                var amountStr = ((document.getElementById('tipAmountInput') || {}).value || '1').trim();
                var amountUsdt = parseFloat(amountStr);
                if (isNaN(amountUsdt) || amountUsdt < 1) {
                    Toast.error('打赏金额至少 1 USDT');
                    return;
                }
                try {
                    var provider = await ensureWalletProvider(tipAuthorWallet);
                    if (!provider) return;
                    var web3 = new Web3(provider);
                    var cRes = await fetch(API_BASE + '/config/fees');
                    var config = await parseJsonSafe(cRes, {});
                    if (!cRes.ok || !config.usdt_contract) {
                        Toast.error('无法获取 USDT 合约配置');
                        return;
                    }
                    var amountRaw = web3.utils.toBN(web3.utils.toWei(amountUsdt.toString(), 'ether'));
                    var sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
                    var paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [tipAuthorWallet, amountRaw]);
                    var txData = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
                    var txHash = await provider.request({
                        method: 'eth_sendTransaction',
                        params: [{
                            to: config.usdt_contract,
                            from: currentUser.address,
                            value: '0x0',
                            data: txData,
                            gas: web3.utils.toHex(100000)
                        }]
                    });
                    if (!txHash) {
                        Toast.error('打赏取消');
                        return;
                    }
                    Toast.info('交易已发送，正在确认...');
                    var verifyRes = await fetch(API_BASE + '/tips/verify', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('token') },
                        body: JSON.stringify({ tx_hash: txHash, post_id: tipAuthorPostId })
                    });
                    var resp = await parseJsonSafe(verifyRes, {});
                    if (verifyRes.ok) {
                        Toast.success('打赏成功！' + resp.tip.author_receives_usdt + ' USDT 已直接转入作者钱包');
                        Modal.close('tipAuthorModal');
                        Modal.openDetail(tipAuthorPostId);
                    } else {
                        Toast.error(resp.error || '验证失败');
                    }
                } catch (e) {
                    if (e && e.code === 4001) Toast.error('已取消打赏');
                    else Toast.error(e.message || '打赏失败');
                }
            }
        };

        var Donate = {
            cachedConfig: null,
            async getConfig(forceRefresh) {
                forceRefresh = !!forceRefresh;
                if (!forceRefresh && this.cachedConfig) return this.cachedConfig;
                try {
                    var r = await fetch(API_BASE + '/config/fees', { cache: 'no-store' });
                    var c = await parseJsonSafe(r, {});
                    if (!r.ok) return null;
                    this.cachedConfig = c;
                    return c;
                } catch (_) {
                    return null;
                }
            },
            async openModal() {
                var c = await this.getConfig(true);
                var el = document.getElementById('donateAddress');
                if (el) el.textContent = (c && c.receive_address) ? c.receive_address : '暂不可用';
                if (!c || !c.receive_address || !c.usdt_contract) {
                    Toast.error('暂时无法获取收款配置，请稍后再试');
                }
                Modal.open('donateModal');
            },
            async send(amount) {
                var amountUsdt = typeof amount === 'number' ? amount : parseFloat(amount);
                if (isNaN(amountUsdt) || amountUsdt < 0.1) {
                    Toast.error('请输入有效金额（至少 0.1 USDT）');
                    return;
                }
                try {
                    var config = await this.getConfig();
                    if (!config || !config.receive_address || !config.usdt_contract) {
                        Toast.error('无法获取收款配置');
                        return;
                    }
                    var donateAddressEl = document.getElementById('donateAddress');
                    if (donateAddressEl) donateAddressEl.textContent = config.receive_address;
                    var provider = await ensureWalletProvider(config.receive_address);
                    if (!provider) return;
                    var web3 = new Web3(provider);
                    var accounts = await provider.request({ method: 'eth_requestAccounts' });
                    var from = accounts[0];
                    var amountRaw = web3.utils.toBN(web3.utils.toWei(amountUsdt.toString(), 'ether'));
                    var sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
                    var paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [config.receive_address, amountRaw]);
                    var data = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
                    var txReq = {
                        to: config.usdt_contract,
                        from: from,
                        value: '0x0',
                        data: data,
                        gas: web3.utils.toHex(100000)
                    };
                    var chainIdNum = Number(config.chain_id || 56);
                    if (Number.isFinite(chainIdNum) && chainIdNum > 0) txReq.chainId = web3.utils.toHex(chainIdNum);
                    await provider.request({ method: 'eth_sendTransaction', params: [txReq] });
                    Toast.success('感谢您的 ' + amountUsdt + ' USDT 打赏！🙏');
                    Modal.close('donateModal');
                } catch (e) {
                    if (e && e.code === 4001) Toast.error('已取消打赏');
                    else Toast.error(e.message || '打赏取消或失败');
                }
            }
        };

        var Interact = {
            getShareUrl(postId) {
                return window.GHShare.getShareUrl(postId);
            },
            getShareText(title) {
                return window.GHShare.getShareText(title);
            },
            openXShare(postId, title) {
                return window.GHShare.openXShare(postId, title);
            },
            async share(refOrPostId, titleMaybe) {
                return window.GHShare.share(refOrPostId, titleMaybe);
            },
            findRenderedPost(postId) {
                var id = Number(postId);
                if (!Number.isFinite(id) || id <= 0) return null;
                var UI = getUI();
                return ((UI && UI.renderedPosts) || []).find(function (p) { return Number(p.id) === id; }) || null;
            },
            syncFeedActionState(postId) {
                var id = Number(postId);
                if (!Number.isFinite(id) || id <= 0) return;
                var post = this.findRenderedPost(id);
                if (!post) return;
                var card = document.querySelector('.timeline-item[data-post-id="' + id + '"]');
                if (!card) return;
                var likeBtn = card.querySelector('[data-feed-action="like"]');
                var bookmarkBtn = card.querySelector('[data-feed-action="bookmark"]');
                if (likeBtn) likeBtn.innerHTML = '😰 <span>' + Number(post.likes_count || 0) + '</span>';
                if (bookmarkBtn) {
                    bookmarkBtn.innerHTML = post.is_bookmarked ? '★ <span>已收</span>' : '⭐ <span>收藏</span>';
                    bookmarkBtn.setAttribute('title', post.is_bookmarked ? '取消收藏' : '收藏');
                    bookmarkBtn.setAttribute('aria-label', post.is_bookmarked ? '取消收藏' : '收藏');
                }
            },
            async report(postId) {
                if (!getCurrentUser()) return Modal.open('loginModal');
                var reason = prompt('请简要说明举报原因（违规内容、广告、抄袭等）：');
                if (reason == null || !reason.trim()) return;
                if (reason.length > 500) {
                    Toast.error('原因最多500字');
                    return;
                }
                try {
                    var res = await fetch(API_BASE + '/reports', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + localStorage.getItem('token') },
                        body: JSON.stringify({ post_id: postId, reason: reason.trim() })
                    });
                    var data = await parseJsonSafe(res, {});
                    if (res.ok) Toast.success(data.message || '举报已提交');
                    else Toast.error(data.error || '提交失败');
                } catch (_) {
                    Toast.error('网络错误');
                }
            },
            async like(id) {
                if (!getCurrentUser()) return Modal.open('loginModal');
                var res = await fetch(API_BASE + '/posts/' + id + '/like', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') }
                });
                var data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    Toast.error(data.error || data.message || '操作失败');
                    return;
                }
                var post = this.findRenderedPost(id);
                if (post) {
                    var isLiked = String((data && data.message) || '').toLowerCase().indexOf('unlike') === -1;
                    post.likes_count = Math.max(0, Number(post.likes_count || 0) + (isLiked ? 1 : -1));
                }
                this.syncFeedActionState(id);
            },
            async bookmark(id) {
                if (!getCurrentUser()) return Modal.open('loginModal');
                var res = await fetch(API_BASE + '/posts/' + id + '/bookmark', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + localStorage.getItem('token') }
                });
                var data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    Toast.error(data.error || data.message || '操作失败');
                    return;
                }
                var post = this.findRenderedPost(id);
                if (post) {
                    post.is_bookmarked = String((data && data.message) || '').toLowerCase().indexOf('unbook') === -1;
                }
                this.syncFeedActionState(id);
            }
        };

        return {
            Modal: Modal,
            Interact: Interact,
            Donate: Donate,
            TipAuthor: TipAuthor,
            copyTextWithFallback: copyTextWithFallback
        };
    };
})();
