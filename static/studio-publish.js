(function () {
    'use strict';

    window.GHStudioPublishFactory = function GHStudioPublishFactory(deps) {
        const {
            apiBase,
            apiJson,
            getCurrentUser,
            getQuill,
            Draft,
            setHidden,
            Toast,
            handle401,
            navigateWithTransition
        } = deps;

        return {
            checkWalletEnv() {
                const area = document.getElementById('walletActionArea');
                const specialArea = document.getElementById('adminSpecialArea');
                const currentUser = getCurrentUser();
                const isAdmin = currentUser && currentUser.is_admin;
                const hasPending = !!this.pendingTxHash;
                if (specialArea) setHidden('adminSpecialArea', !isAdmin);
                area.innerHTML = isAdmin ? `
                    <button class="btn btn-primary studio-block-button studio-publish-button studio-publish-button-spaced" id="publishBtn">
                        ⚡ 支付并上链发布 (Web3)
                    </button>
                    <button class="btn btn-ghost studio-block-button studio-direct-publish-button" id="adminDirectPublishBtn">
                        📝 直接发帖（仅管理员，不上链）
                    </button>
                ` : `
                    <button class="btn btn-primary studio-block-button studio-publish-button" id="publishBtn">
                        ${hasPending ? '🔄 继续发布（已支付）' : '⚡ 确认支付并发布'}
                    </button>
                `;
                this.bindWalletActionArea();
            },

            updateResumePanel(message, tone, stage) {
                const panel = document.getElementById('resumeStatePanel');
                const msgEl = document.getElementById('resumeStateMessage');
                if (!panel || !msgEl) return;
                if (!this.pendingTxHash) {
                    setHidden('resumeStatePanel', true);
                    this.updateResumeStages('');
                    return;
                }
                setHidden('resumeStatePanel', false);
                msgEl.textContent = message || '已记录一笔待恢复支付，可直接继续发布。';
                msgEl.classList.remove('is-error', 'is-success', 'is-warn');
                if (tone === 'error') msgEl.classList.add('is-error');
                else if (tone === 'success') msgEl.classList.add('is-success');
                else if (tone === 'warn') msgEl.classList.add('is-warn');
                this.updateResumeStages(stage || '');
            },

            updateResumeStages(stage) {
                const list = document.getElementById('resumeStageList');
                if (!list) return;
                const order = ['initiated', 'payment_verified', 'storage_ready', 'awaiting_retry', 'published'];
                const stageIndex = order.indexOf(stage);
                list.querySelectorAll('.resume-stage-item').forEach((node) => {
                    const key = node.getAttribute('data-stage') || '';
                    const index = order.indexOf(key);
                    node.classList.remove('is-current', 'is-complete', 'is-error');
                    if (stageIndex >= 0 && index >= 0 && index < stageIndex) node.classList.add('is-complete');
                    if (key === stage) node.classList.add('is-current');
                    if (key === stage && stage === 'awaiting_retry') node.classList.add('is-error');
                });
            },

            addLog(msg) {
                const c = document.getElementById('loadingLogs');
                const line = document.createElement('div');
                line.textContent = `> ${msg}`;
                c.appendChild(line);
                c.scrollTop = c.scrollHeight;
            },

            startLogs() {
                const c = document.getElementById('loadingLogs');
                c.innerHTML = '';
                const logs = [
                    '初始化 Web3 钱包...',
                    '正在请求用户签名...',
                    '广播交易至 BSC 节点...',
                    '等待区块确认 (1/12)...',
                    '正在封装数据包 (Size: 12KB)...',
                    '正在写入永存档案...',
                    '正在写入智能合约...',
                    '🛡️ 进行最终安全验证...'
                ];
                let i = 0;
                this.addLog(logs[0]);
                this.logInterval = setInterval(() => {
                    i++;
                    if (i < logs.length) this.addLog(logs[i]);
                }, 2500);
            },

            stopLogs() {
                if (this.logInterval) clearInterval(this.logInterval);
            },

            copyHash() {
                const hash = document.getElementById('realTxHash').textContent;
                navigator.clipboard.writeText(hash);
                Toast.success('已复制');
            },

            copyDappUrlForBinance() {
                const url = window.location.href;
                navigator.clipboard.writeText(url).then(() => {
                    Toast.success('已复制链接');
                    alert('已复制本站链接。请打开 币安 App → 底部「钱包」→ 右上角「…」→「浏览器」→ 粘贴地址访问');
                });
            },

            savePendingPost(txHash) {
                const quill = getQuill();
                const title = document.getElementById('studioPostTitle').value;
                const content = quill ? quill.root.innerHTML : '';
                const tags = this.parseTagsInput();
                const seriesId = this.seriesSelectValue();
                const specialChecked = !!(document.getElementById('adminSpecialPostCheckbox') && document.getElementById('adminSpecialPostCheckbox').checked);
                const data = {
                    title,
                    content,
                    tags,
                    series_id: seriesId || null,
                    tx_hash: txHash !== undefined ? txHash : (this.pendingTxHash || null),
                    is_special_announcement: specialChecked,
                    time: Date.now()
                };
                try { localStorage.setItem('studio_pending_post', JSON.stringify(data)); } catch (e) {}
            },

            clearPendingPost() {
                try { localStorage.removeItem('studio_pending_post'); } catch (e) {}
            },

            async clearPendingState(notify) {
                const txHash = this.pendingTxHash;
                if (txHash) {
                    try {
                        await apiJson(`${apiBase}/posts/pending/clear`, {
                            method: 'POST',
                            body: { tx_hash: txHash },
                            fallback: {}
                        });
                    } catch (e) {}
                }
                this.pendingTxHash = null;
                this.clearPendingPost();
                this.checkWalletEnv();
                this.updateResumePanel('', '', '');
                if (notify) Toast.info('已清除待恢复记录');
            },

            async loadServerPendingPost() {
                if (!getCurrentUser()) return false;
                try {
                    const result = await apiJson(`${apiBase}/posts/pending/latest`, { fallback: {} });
                    const pending = result.data && result.data.pending;
                    const quill = getQuill();
                    if (!pending || !pending.tx_hash) return false;
                    this.pendingTxHash = pending.tx_hash;
                    if (pending.title) document.getElementById('studioPostTitle').value = pending.title;
                    if (pending.content && quill) quill.clipboard.dangerouslyPasteHTML(pending.content);
                    if (Array.isArray(pending.tags)) {
                        const tagsInput = document.getElementById('studioPostTags');
                        if (tagsInput) tagsInput.value = pending.tags.join(', ');
                    }
                    const seriesVal = (pending.series_id == null ? '' : String(pending.series_id));
                    this.loadSeriesOptions(seriesVal);
                    const specialBox = document.getElementById('adminSpecialPostCheckbox');
                    if (specialBox) specialBox.checked = !!pending.is_special_announcement;
                    this.checkWalletEnv();
                    this.updateResumePanel(
                        pending.last_error || '检测到服务端待恢复发布记录，可直接继续，无需再次支付。',
                        pending.status === 'awaiting_retry' ? 'warn' : '',
                        pending.status || ''
                    );
                    return true;
                } catch (e) {
                    return false;
                }
            },

            loadPendingPost() {
                try {
                    const raw = localStorage.getItem('studio_pending_post');
                    const quill = getQuill();
                    if (!raw) {
                        this.updateResumePanel('', '', '');
                        this.loadServerPendingPost();
                        return;
                    }
                    const p = JSON.parse(raw);
                    if (!p.tx_hash || !p.time || (Date.now() - p.time > 24 * 60 * 60 * 1000)) {
                        this.clearPendingState(false);
                        this.loadServerPendingPost();
                        return;
                    }
                    this.pendingTxHash = p.tx_hash;
                    if (p.title) document.getElementById('studioPostTitle').value = p.title;
                    if (p.content && quill) quill.clipboard.dangerouslyPasteHTML(p.content);
                    if (Array.isArray(p.tags)) {
                        const tagsInput = document.getElementById('studioPostTags');
                        if (tagsInput) tagsInput.value = p.tags.join(', ');
                    }
                    const seriesVal = (p.series_id == null ? '' : String(p.series_id));
                    this.loadSeriesOptions(seriesVal);
                    const specialBox = document.getElementById('adminSpecialPostCheckbox');
                    if (specialBox) specialBox.checked = !!p.is_special_announcement;
                    this.checkWalletEnv();
                    this.updateResumePanel('检测到未完成的发布记录，可直接继续，无需再次支付。', 'warn', 'initiated');
                    this.checkPendingStatus(p.tx_hash, true);
                    Toast.info('检测到未完成的发布（已支付），可直接点击发布继续，无需再次支付');
                } catch (e) {}
            },

            resumeWithTxHash() {
                const input = document.getElementById('resumeTxHashInput');
                if (!input) return;
                const txHash = (input.value || '').trim();
                if (!/^0x[a-fA-F0-9]{64}$/.test(txHash)) {
                    Toast.error('请输入有效的 BSC 交易哈希（0x 开头，64 位十六进制）');
                    return;
                }
                this.pendingTxHash = txHash;
                this.savePendingPost(txHash);
                input.value = '';
                this.checkWalletEnv();
                this.updateResumePanel('已记录交易哈希，正在检查当前处理状态…', 'warn', 'initiated');
                this.checkPendingStatus(txHash, true);
                Toast.success('已记录该交易哈希，请直接点击「确认支付并发布」继续（不会再次扣款）');
            },

            async checkPendingStatus(txHash, silent) {
                const hash = (txHash || this.pendingTxHash || '').trim();
                if (!hash) {
                    if (!silent) Toast.info('当前没有待恢复的交易哈希');
                    return;
                }
                this.pendingTxHash = hash;
                this.updateResumePanel('正在检查链上与发布状态…', 'warn', 'initiated');
                try {
                    const result = await apiJson(`${apiBase}/posts/check_tx?tx_hash=${encodeURIComponent(hash)}`, {
                        auth: false,
                        fallback: {}
                    });
                    const data = result.data || {};
                    if (!result.res.ok || data.error) {
                        this.updateResumePanel(data.error || '暂时无法检查状态，请稍后重试。', 'error', '');
                        if (!silent) Toast.error(data.error || '检查状态失败');
                        return;
                    }
                    if (data.status === 'success') {
                        Draft.clear();
                        this.pendingTxHash = null;
                        this.updateResumePanel('该交易对应的帖子已发布完成。', 'success', 'published');
                        this.checkWalletEnv();
                        if (!silent) Toast.success(data.message || '帖子已成功发布');
                        return;
                    }
                    if (data.status === 'pending') {
                        this.updateResumePanel(data.message || '支付处理中，可稍后继续发布。', data.stage === 'confirmed_processing' ? 'warn' : '', data.pending_status || 'payment_verified');
                        if (!silent) Toast.info(data.message || '支付处理中');
                        return;
                    }
                    this.updateResumePanel(data.message || '当前交易状态异常，可稍后重试或联系管理员。', 'error', data.pending_status || '');
                    if (!silent) Toast.error(data.message || '交易状态异常');
                } catch (e) {
                    this.updateResumePanel('状态检查失败，请稍后重试。', 'error', '');
                    if (!silent) Toast.error('状态检查失败');
                }
            },

            openDrawer() {
                const drawer = document.getElementById('paymentDrawer');
                if (drawer) {
                    drawer.classList.add('active');
                    const container = document.querySelector('.studio-container') || document.querySelector('.main-container');
                    if (container) container.style.filter = 'blur(5px)';
                }
            },

            closeDrawer() {
                document.getElementById('paymentDrawer').classList.remove('active');
                const container = document.querySelector('.studio-container') || document.querySelector('.main-container');
                if (container) container.style.filter = 'none';
                this.stopLogs();
                if (this.timeoutId) clearTimeout(this.timeoutId);
                this.isPublishing = false;
                const btn = document.getElementById('publishBtn');
                if (btn) btn.disabled = false;
            },

            async initPayment() {
                if (this.isPublishing) return;
                const pre = await this.runPrecheck();
                if (!pre.ok) {
                    Toast.error((pre.issues && pre.issues[0]) || '发布前检查未通过');
                    return;
                }
                if (pre.warnings && pre.warnings.length) Toast.info(pre.warnings[0]);

                document.getElementById('drawerPreviewMode').style.display = 'block';
                setHidden('drawerProgressMode', true);
                document.getElementById('previewAmount').textContent = 'Loading...';
                this.openDrawer();

                try {
                    const cfgResult = await apiJson(`${apiBase}/config/fees`, { auth: false, fallback: {} });
                    const cRes = cfgResult.res;
                    const config = cfgResult.data || {};
                    if (!cRes.ok) {
                        Toast.error(config.error || '无法获取支付配置');
                        this.closeDrawer();
                        return;
                    }

                    const feeUsdt = (config.fee_usdt != null ? config.fee_usdt : (Number(config.fee) / 1e18)).toFixed(2);
                    document.getElementById('previewAmount').textContent = `${feeUsdt} USDT`;
                    const addrEl = document.getElementById('previewReceiveAddress');
                    if (addrEl && config.receive_address) addrEl.textContent = config.receive_address;

                    const area = document.getElementById('drawerActionArea');
                    const isMobile = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
                    if (isMobile && typeof window.ethereum === 'undefined' && typeof window.BinanceChain === 'undefined') {
                        const dappUrl = window.location.host + window.location.pathname;
                        const metamaskLink = `https://metamask.app.link/dapp/${dappUrl}`;
                        area.innerHTML = `
                            <div class="drawer-mobile-guide-copy">
                                ⚠️ 移动端请用钱包 App 内置浏览器打开本站
                            </div>
                            <a href="${metamaskLink}" class="btn btn-primary drawer-block-button drawer-wallet-link drawer-wallet-link-metamask">
                                🦊 用 MetaMask App 打开
                            </a>
                            <button type="button" class="btn btn-primary drawer-block-button drawer-wallet-link drawer-wallet-link-binance" id="drawerBinanceGuideBtn">
                                🟡 用币安 App 打开（复制链接后到币安内置浏览器粘贴）
                            </button>
                        `;
                    } else {
                        area.innerHTML = `
                            <button class="btn btn-primary drawer-block-button drawer-confirm-button" id="drawerConfirmPaymentActionBtn">
                                🚀 确认并支付
                            </button>
                        `;
                    }
                    this.bindDrawerActions();
                } catch (e) {
                    Toast.error('无法获取费率: ' + e.message);
                    this.closeDrawer();
                }
            },

            async confirmPayment() {
                document.getElementById('drawerPreviewMode').style.display = 'none';
                setHidden('drawerProgressMode', false);
                this.startLogs();
                await this.publish();
            },

            async pollTxStatus(txHash) {
                this.addLog('🔄 网络波动，正在后台轮询上链状态...');
                let attempts = 0;
                const maxAttempts = 30;
                const poll = async () => {
                    if (attempts >= maxAttempts) {
                        this.addLog('❌ 服务器响应超时，请稍后在个人中心查看');
                        setHidden('forceCloseLoading', false);
                        return;
                    }
                    attempts++;
                    try {
                        const result = await apiJson(`${apiBase}/posts/check_tx?tx_hash=${encodeURIComponent(txHash)}`, {
                            auth: false,
                            fallback: {}
                        });
                        const resp = result.data || {};
                        if (resp.status === 'success') {
                            this.addLog('✅ 服务器确认成功!');
                            Draft.clear();
                            this.pendingTxHash = null;
                            this.checkWalletEnv();
                            this.updateResumePanel('该交易已发布完成。', 'success');
                            Toast.success('发布成功');
                            setTimeout(() => navigateWithTransition('/'), 2000);
                        } else if (resp.status === 'error') {
                            this.addLog('❌ ' + (resp.message || '链路状态异常'));
                            this.updateResumePanel(resp.message || '链路状态异常，请稍后再试。', 'error');
                            setHidden('forceCloseLoading', false);
                        } else {
                            if (resp.message) this.addLog('ℹ️ ' + resp.message);
                            setTimeout(poll, 3000);
                        }
                    } catch (e) {
                        setTimeout(poll, 3000);
                    }
                };
                poll();
            },

            async resumePendingPublication(txHash, title, content, tags, seriesId, specialChecked) {
                this.addLog('检测到已支付交易，正在走服务端补偿发布...');
                const result = await apiJson(`${apiBase}/posts/pending/retry`, {
                    method: 'POST',
                    body: {
                        tx_hash: txHash,
                        title,
                        content,
                        tags,
                        series_id: seriesId || null,
                        is_special_announcement: specialChecked,
                        region: '其他'
                    },
                    fallback: {}
                });
                const res = result.res;
                const data = result.data || {};
                if (handle401(res)) return { handled: true, ok: false };
                if (res.ok) {
                    this.addLog('✅ 待恢复发布已补偿完成!');
                    Draft.clear();
                    this.clearPendingPost();
                    this.pendingTxHash = null;
                    this.checkWalletEnv();
                    this.updateResumePanel('当前发布已完成。', 'success');
                    Toast.success(data.message || '发布成功');
                    setTimeout(() => navigateWithTransition('/'), 2000);
                    return { handled: true, ok: true };
                }
                const msg = data.error || (data.pending && data.pending.last_error) || ('请求失败 ' + res.status);
                if (res.status === 503 && data.pending) {
                    this.addLog('ℹ️ ' + msg);
                    this.updateResumePanel(msg, data.pending.status === 'awaiting_retry' ? 'warn' : 'error');
                }
                throw new Error(msg);
            },

            async publish() {
                if (this.isPublishing) return;
                const currentUser = getCurrentUser();
                const quill = getQuill();
                if (!currentUser) {
                    Toast.error('登录已失效，请重新登录');
                    return;
                }
                const title = document.getElementById('studioPostTitle').value;
                const content = quill ? quill.root.innerHTML : '';
                const tags = this.parseTagsInput();
                const seriesId = this.seriesSelectValue();
                const specialChecked = !!(document.getElementById('adminSpecialPostCheckbox') && document.getElementById('adminSpecialPostCheckbox').checked);
                const btn = document.getElementById('publishBtn');

                this.isPublishing = true;
                if (btn) btn.disabled = true;
                this.timeoutId = setTimeout(() => setHidden('forceCloseLoading', false), 60000);

                let txHash = this.pendingTxHash;
                try {
                    const pre = await this.runPrecheck();
                    if (!pre.ok) throw new Error((pre.issues && pre.issues[0]) || '发布前检查未通过');
                    if (txHash) {
                        const resumed = await this.resumePendingPublication(txHash, title, content, tags, seriesId, specialChecked);
                        if (resumed && resumed.handled) return;
                    }

                    if (typeof window.web3 === 'undefined') {
                        if (window.BinanceChain || window.ethereum) window.web3 = new Web3(window.BinanceChain || window.ethereum);
                        else throw new Error('No wallet found');
                    }
                    const web3 = window.web3;
                    const provider = window.BinanceChain || window.ethereum;
                    if (!provider) throw new Error('No wallet found');

                    const cfgResult = await apiJson(`${apiBase}/config/fees`, { auth: false, fallback: {} });
                    const cRes = cfgResult.res;
                    const config = cfgResult.data || {};
                    if (!cRes.ok || !config.receive_address) throw new Error(config.error || '无法获取支付配置');

                    if (web3) {
                        const chainId = await web3.eth.getChainId();
                        if (Number(chainId) !== Number(config.chain_id)) {
                            try {
                                await provider.request({
                                    method: 'wallet_switchEthereumChain',
                                    params: [{ chainId: web3.utils.toHex(String(config.chain_id)) }]
                                });
                            } catch (switchError) {
                                throw new Error(`请切换到 BSC Mainnet 主网 (Chain ID: ${config.chain_id})`);
                            }
                        }
                    }

                    this.savePendingPost(txHash || undefined);
                    this.updateResumePanel('已创建恢复记录，如中途失败可直接继续。', 'warn');
                    if (!txHash) {
                        if (!config.usdt_contract) throw new Error('未配置 USDT 合约地址');
                        this.addLog('等待钱包确认 USDT 转账...');
                        const feeRaw = web3.utils.toBN(config.fee.toString());
                        const sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
                        const paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [config.receive_address, feeRaw]);
                        const data = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
                        txHash = await provider.request({
                            method: 'eth_sendTransaction',
                            params: [{
                                to: config.usdt_contract,
                                from: currentUser.address,
                                value: '0x0',
                                data,
                                gas: web3.utils.toHex(100000)
                            }]
                        });
                        this.pendingTxHash = txHash;
                        this.savePendingPost(txHash);
                        this.checkWalletEnv();
                    }

                    this.addLog('交易已广播: ' + txHash.substring(0, 10) + '...');
                    setHidden('txHashDisplay', false);
                    document.getElementById('realTxHash').textContent = txHash;
                    this.addLog('等待链上确认...');

                    let receipt = null;
                    for (let i = 0; i < 60; i++) {
                        try {
                            receipt = await web3.eth.getTransactionReceipt(txHash);
                            if (receipt && receipt.status) break;
                        } catch (e) {}
                        await new Promise((r) => setTimeout(r, 1000));
                    }
                    if (!receipt || !receipt.status) throw new Error('交易未确认');

                    this.addLog('交易确认成功! 正在写入永存档案...');
                    const publishResult = await apiJson(`${apiBase}/posts`, {
                        method: 'POST',
                        body: {
                            title,
                            content,
                            tx_hash: txHash,
                            tags,
                            series_id: seriesId || null,
                            is_special_announcement: specialChecked,
                            images: [],
                            region: '其他'
                        },
                        fallback: {}
                    });
                    const res = publishResult.res;
                    const errData = publishResult.data || {};
                    if (handle401(res)) return;
                    if (res.ok) {
                        this.addLog('✅ 永存档案已写入，发布成功!');
                        Draft.clear();
                        this.clearPendingPost();
                        this.pendingTxHash = null;
                        this.checkWalletEnv();
                        this.updateResumePanel('当前发布已完成。', 'success');
                        Toast.success('发布成功');
                        setTimeout(() => navigateWithTransition('/'), 2000);
                    } else {
                        const msg = errData.error || ('请求失败 ' + res.status);
                        if (res.status === 503 && (errData.code === 'ARWEAVE_FAIL' || msg.includes('永存档案'))) {
                            this.addLog('⚠️ 永存档案写入暂时失败，请点击「重试发布」再试（无需再次支付）');
                            this.addLog('ℹ️ 当前状态：支付已确认，帖子仍在待发布队列');
                            this.updateResumePanel('支付已确认，正在等待永存写入恢复。可直接点“继续发布”重试，无需再次支付。', 'warn', 'awaiting_retry');
                        }
                        throw new Error(msg);
                    }
                } catch (e) {
                    console.error(e);
                    if (e.message && (e.message.includes('Token') || e.message.includes('expired'))) {
                        this.addLog('❌ 身份验证过期，草稿已自动保存');
                        Draft.save();
                        Toast.error('登录过期，请重新登录');
                        setTimeout(() => navigateWithTransition('/'), 2000);
                        return;
                    }
                    if (txHash && (e.message.includes('fetch') || e.message.includes('Network'))) {
                        this.pollTxStatus(txHash);
                        return;
                    }
                    this.addLog('❌ 错误: ' + e.message);
                    Toast.error('发布失败: ' + e.message);
                    setHidden('forceCloseLoading', false);
                    if (this.pendingTxHash && btn) {
                        btn.innerHTML = '🔄 重试发布 (已支付)';
                        this.updateResumePanel('你可以直接点击“继续发布”重试，或先检查当前状态。', 'warn', 'awaiting_retry');
                    }
                }
            },

            async publishAsAdmin() {
                const currentUser = getCurrentUser();
                const quill = getQuill();
                if (!currentUser || !currentUser.is_admin) {
                    Toast.error('仅管理员可操作');
                    return;
                }
                const title = document.getElementById('studioPostTitle').value.trim();
                const content = quill ? quill.root.innerHTML : '';
                const textContent = quill ? quill.getText().trim() : '';
                const tags = this.parseTagsInput();
                const seriesId = this.seriesSelectValue();
                if (!title) return Toast.error('请填写标题');
                if (!textContent) return Toast.error('请填写正文');
                const specialChecked = !!(document.getElementById('adminSpecialPostCheckbox') && document.getElementById('adminSpecialPostCheckbox').checked);
                const btn = document.getElementById('adminDirectPublishBtn');
                if (btn) btn.disabled = true;
                try {
                    const result = await apiJson(`${apiBase}/posts`, {
                        method: 'POST',
                        body: {
                            title,
                            content,
                            tags,
                            series_id: seriesId || null,
                            is_special_announcement: specialChecked,
                            images: [],
                            region: '其他'
                        },
                        fallback: {}
                    });
                    const res = result.res;
                    const resp = result.data || {};
                    if (handle401(res)) return;
                    if (res.ok) {
                        Draft.clear();
                        Toast.success('已发布（普通帖，未上链）');
                        setTimeout(() => navigateWithTransition('/'), 1500);
                    } else {
                        Toast.error(resp.error || '发布失败');
                    }
                } catch (e) {
                    Toast.error('发布失败: ' + (e.message || '网络错误'));
                } finally {
                    if (btn) btn.disabled = false;
                }
            },

            bindWalletActionArea() {
                const publishBtn = document.getElementById('publishBtn');
                if (publishBtn) publishBtn.onclick = () => this.initPayment();
                const adminDirectBtn = document.getElementById('adminDirectPublishBtn');
                if (adminDirectBtn) adminDirectBtn.onclick = () => this.publishAsAdmin();
            },

            bindDrawerActions() {
                const confirmBtn = document.getElementById('drawerConfirmPaymentBtn');
                if (confirmBtn) confirmBtn.onclick = () => this.confirmPayment();
                const confirmActionBtn = document.getElementById('drawerConfirmPaymentActionBtn');
                if (confirmActionBtn) confirmActionBtn.onclick = () => this.confirmPayment();
                const cancelBtn = document.getElementById('drawerCancelBtn');
                if (cancelBtn) cancelBtn.onclick = () => this.closeDrawer();
                const copyBtn = document.getElementById('drawerCopyHashBtn');
                if (copyBtn) copyBtn.onclick = () => this.copyHash();
                const forceCloseBtn = document.getElementById('forceCloseLoading');
                if (forceCloseBtn) forceCloseBtn.onclick = () => this.closeDrawer();
                const binanceGuideBtn = document.getElementById('drawerBinanceGuideBtn');
                if (binanceGuideBtn) binanceGuideBtn.onclick = () => this.copyDappUrlForBinance();
            },

            bindStaticActions() {
                const createSeriesBtn = document.getElementById('createSeriesBtn');
                if (createSeriesBtn) createSeriesBtn.onclick = () => this.quickCreateSeries();
                const nextStepBtn = document.getElementById('studioNextStepBtn');
                if (nextStepBtn) nextStepBtn.onclick = () => this.nextStep(3);
                const prevStepBtn = document.getElementById('studioPrevStepBtn');
                if (prevStepBtn) prevStepBtn.onclick = () => this.prevStep(1);
                const resumeWithTxHashBtn = document.getElementById('resumeWithTxHashBtn');
                if (resumeWithTxHashBtn) resumeWithTxHashBtn.onclick = () => this.resumeWithTxHash();
                const resumeCheckBtn = document.getElementById('resumeCheckBtn');
                if (resumeCheckBtn) resumeCheckBtn.onclick = () => this.checkPendingStatus();
                const resumeClearBtn = document.getElementById('resumeClearBtn');
                if (resumeClearBtn) resumeClearBtn.onclick = () => this.clearPendingState(true);
                const loginModal = document.getElementById('loginModal');
                if (loginModal) {
                    loginModal.addEventListener('click', function (event) {
                        if (event.target === loginModal) window.Modal.close('loginModal');
                    });
                }
                const loginModalCloseBtn = document.getElementById('studioLoginModalCloseBtn');
                if (loginModalCloseBtn) loginModalCloseBtn.onclick = () => window.Modal.close('loginModal');
                const loginBackHomeBtn = document.getElementById('studioLoginBackHomeBtn');
                if (loginBackHomeBtn) loginBackHomeBtn.onclick = () => navigateWithTransition('/');
                this.bindWalletActionArea();
                this.bindDrawerActions();
            }
        };
    };
})();
