(function () {
    'use strict';

    window.GHAuthFactory = function GHAuthFactory(deps) {
        var API_BASE = deps.API_BASE;
        var getCurrentUser = deps.getCurrentUser;
        var setCurrentUser = deps.setCurrentUser;
        var fetchJsonSafe = deps.fetchJsonSafe;
        var handle401 = deps.handle401;
        var Toast = deps.Toast;
        var Modal = deps.Modal;
        var Post = deps.Post;
        var UI = deps.UI;
        var SiteNotice = deps.SiteNotice;
        var Onboarding = deps.Onboarding;
        var Checkin = deps.Checkin;
        var GroupLinks = deps.GroupLinks;
        var Notification = deps.Notification;
        var copyTextWithFallback = deps.copyTextWithFallback;
        var navigateWithTransition = deps.navigateWithTransition;
        var apiJson = window.apiJson;
        var authState = window.authState;

        return {
            async init() {
                await this.fetchMe();
                this.checkLoginExpiry();
                setInterval(() => this.checkLoginExpiry(), 5 * 60 * 1000);
                UI.updateAuth();
                SiteNotice.load();
                Onboarding.load();
                Checkin.load();
                GroupLinks.load();
                this.autoOpenBindWallet();
                if (getCurrentUser() && Notification && typeof Notification.load === 'function') {
                    setInterval(function () {
                        if (document.visibilityState === 'visible') Notification.load();
                    }, 60000);
                }
            },

            autoOpenBindWallet() {
                try {
                    var url = new URL(window.location.href);
                    if (url.searchParams.get('bind_wallet') !== '1') return;
                    url.searchParams.delete('bind_wallet');
                    window.history.replaceState({}, '', url.pathname + url.search + url.hash);
                    var currentUser = getCurrentUser();
                    if (!currentUser || currentUser.address) return;
                    window.setTimeout(() => {
                        this.bindWallet();
                    }, 180);
                } catch (_) {}
            },

            async fetchMe() {
                try {
                    var result = await apiJson(API_BASE + '/user/me', { fallback: {}, check401: false });
                    var res = result.res;
                    if (res.ok) {
                        if (authState && authState.markLoggedIn) authState.markLoggedIn();
                        setCurrentUser(result.data);
                    } else {
                        if (authState && authState.clear) authState.clear();
                        setCurrentUser(null);
                    }
                } catch (_) {
                    setCurrentUser(null);
                }
            },

            toggleForm(mode) {
                var login = document.getElementById('loginFormContainer');
                var reg = document.getElementById('registerFormContainer');
                var cp = document.getElementById('changePasswordFormContainer');
                if (login) {
                    login.hidden = mode !== 'login';
                    login.style.display = (mode === 'login') ? 'block' : 'none';
                }
                if (reg) {
                    reg.hidden = mode !== 'register';
                    reg.style.display = (mode === 'register') ? 'block' : 'none';
                }
                if (cp) {
                    cp.hidden = mode !== 'changePassword';
                    cp.style.display = (mode === 'changePassword') ? 'block' : 'none';
                }
            },
            async fetchNonceForAddress(address) {
                var nonceResult = await apiJson(API_BASE + '/auth/nonce?address=' + encodeURIComponent(address), {
                    auth: false,
                    fallback: {}
                });
                var nonceRes = nonceResult.res;
                var nonceData = nonceResult.data;
                if (!nonceRes.ok || !nonceData || !nonceData.nonce) {
                    throw new Error((nonceData && nonceData.error) || '获取签名消息失败，请重试');
                }
                return String(nonceData.nonce);
            },

            async requestPersonalSign(provider, address, message) {
                var normalizeSig = function (result) {
                    if (result && typeof result === 'object' && result.result) return result.result;
                    return result;
                };
                try {
                    var signRes = await provider.request({
                        method: 'personal_sign',
                        params: [message, address]
                    });
                    return normalizeSig(signRes);
                } catch (_) {
                    try {
                        var signRes2 = await provider.request({
                            method: 'personal_sign',
                            params: [address, message]
                        });
                        return normalizeSig(signRes2);
                    } catch (_) {
                        throw new Error('签名被拒绝或钱包不支持');
                    }
                }
            },

            async loginWeb3() {
                if (typeof window.BinanceChain !== 'undefined') {
                    window.web3 = new Web3(window.BinanceChain);
                } else if (typeof window.ethereum !== 'undefined') {
                    window.web3 = new Web3(window.ethereum);
                } else {
                    var isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
                    if (isMobile) {
                        var fullUrl = window.location.href;
                        var dappHost = window.location.host;
                        var tryMetaMask = function () { window.location.href = 'https://metamask.app.link/dapp/' + dappHost; };
                        var copyAndGuideBinance = function () {
                            navigator.clipboard.writeText(fullUrl).then(function () {
                                Toast.success('已复制链接');
                                alert('请打开 币安 App → 底部「钱包」→ 右上角「…」→「浏览器」→ 粘贴地址访问本站');
                            });
                        };
                        if (confirm('移动端未检测到钱包。\n\n• 选「确定」跳转 MetaMask App\n• 选「取消」复制链接，到币安 App 内置浏览器粘贴打开')) {
                            tryMetaMask();
                            return;
                        }
                        copyAndGuideBinance();
                        return;
                    }
                    return Toast.error('请安装 MetaMask, Binance Wallet 或其他 Web3 钱包');
                }

                try {
                    var provider = window.BinanceChain || window.ethereum;
                    if (!provider) return Toast.error('请安装币安钱包、MetaMask 或其他 Web3 钱包');
                    Toast.info('正在拉起钱包，请在弹出的窗口中授权…');
                    var accounts;
                    try {
                        accounts = await provider.request({ method: 'eth_requestAccounts' });
                    } catch (e) {
                        if (e.code === 4001 || (e.message && e.message.includes('reject'))) return Toast.error('已取消授权');
                        return Toast.error('无法连接钱包: ' + (e.message || '请重试'));
                    }
                    if (!accounts || !accounts.length) return Toast.error('未检测到账户');
                    await this.handleWeb3Verify(accounts[0], provider, false);
                } catch (e) {
                    Toast.error(e && e.message ? e.message : 'Web3 登录失败');
                }
            },

            async handleWeb3Verify(address, provider, isWalletConnect) {
                try {
                    var nonce = await this.fetchNonceForAddress(address);
                    var message = 'Sign this message to login to ' + location.host + ': ' + nonce;
                    var signature = await this.requestPersonalSign(provider, address, message);
                    if (!signature) throw new Error('签名结果为空，请重试');
                    var verifyResult = await apiJson(API_BASE + '/auth/verify', {
                        method: 'POST',
                        body: { address: address, signature: signature, message: message },
                        auth: false,
                        fallback: {}
                    });
                    var verifyRes = verifyResult.res;
                    var verifyData = verifyResult.data;
                    if (!verifyRes.ok) throw new Error((verifyData && verifyData.error) || '验证失败，请稍后重试');
                    if (!verifyData || !verifyData.user) throw new Error('服务返回异常，请稍后重试');
                    this.success(verifyData);
                    if (isWalletConnect) this.wcProvider = provider;
                } catch (e) {
                    console.error(e);
                    throw e;
                }
            },

            async getWalletChoices() {
                var installed = [];
                var hasBinance = !!window.BinanceChain;
                var hasMetaMask = !!(window.ethereum && window.ethereum.isMetaMask);
                var hasGenericInjected = !!(window.ethereum && !hasMetaMask && !hasBinance);
                if (hasBinance) installed.push({ id: 'binance', icon: '🟡', name: 'Binance Wallet', sub: '已安装 · 推荐（BSC）' });
                if (hasMetaMask) installed.push({ id: 'metamask', icon: '🦊', name: 'MetaMask', sub: '已安装' });
                var walletConnectEnabled = false;
                var walletConnectSub = '扫码登录（手机钱包）';
                try {
                    var cfgResult = await apiJson(API_BASE + '/config/public', { auth: false, fallback: {} });
                    var cfg = cfgResult.data;
                    var projectId = cfg && cfg.walletconnect_project_id ? cfg.walletconnect_project_id.trim() : '';
                    walletConnectEnabled = !!(projectId && window.UniversalProvider);
                    if (!projectId) walletConnectSub = '站点暂未配置 WalletConnect';
                    else if (!window.UniversalProvider) walletConnectSub = 'WalletConnect 组件未加载';
                } catch (_) {
                    walletConnectSub = 'WalletConnect 配置读取失败';
                }
                var others = [
                    { id: 'binance_app', icon: '🟨', name: 'Binance App', sub: '手机端在币安 App 内置钱包/浏览器打开本站' },
                    { id: 'walletconnect', icon: '🔗', name: 'WalletConnect', sub: walletConnectSub, disabled: !walletConnectEnabled }
                ];
                if (hasGenericInjected) others.push({ id: 'browser', icon: '🌐', name: 'Browser Wallet', sub: '使用当前浏览器注入钱包' });
                return { installed: installed, others: others };
            },

            async openWalletSelector() {
                var listEl = document.getElementById('walletSelectList');
                var qrWrap = document.getElementById('walletSelectQr');
                if (!listEl) {
                    Toast.error('钱包列表加载失败');
                    return;
                }
                if (qrWrap) {
                    qrWrap.hidden = true;
                    qrWrap.style.display = 'none';
                    qrWrap.innerHTML = '';
                }
                var groups = await this.getWalletChoices();
                var renderItem = function (item) {
                    return '<button type="button" class="wallet-select-item" data-wallet="' + item.id + '" ' + (item.disabled ? 'disabled' : '') + '>' +
                        '<span class="wallet-select-icon">' + item.icon + '</span>' +
                        '<span class="wallet-select-meta">' +
                            '<span class="wallet-select-name">' + item.name + '</span>' +
                            '<span class="wallet-select-sub">' + (item.sub || '') + '</span>' +
                        '</span>' +
                    '</button>';
                };
                listEl.innerHTML =
                    '<div class="wallet-select-group-title">已安装</div>' +
                    '<div class="wallet-select-list">' +
                        (groups.installed.length ? groups.installed.map(renderItem).join('') : '<div class="wallet-select-sub wallet-select-sub-padded">未检测到注入钱包，可使用 WalletConnect 扫码登录。</div>') +
                    '</div>' +
                    '<div class="wallet-select-group-title">其他方式</div>' +
                    '<div class="wallet-select-list">' + groups.others.map(renderItem).join('') + '</div>';
                listEl.querySelectorAll('button[data-wallet]').forEach((btn) => {
                    btn.onclick = async () => {
                        var key = btn.getAttribute('data-wallet') || '';
                        if (!key || btn.disabled) return;
                        if (key === 'walletconnect') return this.loginWithWalletConnect('walletSelectQr');
                        if (key === 'binance_app') return this.openBinanceAppGuide();
                        if (key === 'binance') return this.loginWithInjectedWallet(window.BinanceChain, 'Binance Wallet');
                        if (key === 'metamask') return this.loginWithInjectedWallet(window.ethereum, 'MetaMask');
                        if (key === 'browser') return this.loginWithInjectedWallet(window.BinanceChain || window.ethereum, 'Browser Wallet');
                    };
                });
                Modal.close('loginModal');
                Modal.open('walletSelectModal');
            },

            async openBinanceAppGuide() {
                var copied = await copyTextWithFallback(window.location.href, '已复制当前页面链接');
                var isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || '');
                if (isMobile) Toast.info(copied ? '请到币安 App 的钱包浏览器中粘贴刚复制的链接打开本站' : '请在币安 App 的钱包浏览器中打开本站');
                else Toast.info(copied ? '请在手机币安 App 的钱包浏览器中粘贴刚复制的链接打开本站' : '请在手机币安 App 的钱包浏览器中打开本站');
            },

            async loginWithInjectedWallet(provider, walletName) {
                if (!provider) {
                    Toast.error((walletName || '钱包') + ' 未检测到');
                    return;
                }
                try {
                    var accounts = await provider.request({ method: 'eth_requestAccounts' });
                    if (!accounts || !accounts.length) {
                        Toast.error('未获取到钱包地址');
                        return;
                    }
                    await this.handleWeb3Verify(accounts[0], provider, false);
                } catch (e) {
                    var msg = String((e && e.message) || e || '');
                    if ((e && e.code === 4001) || msg.includes('reject')) Toast.info('已取消授权');
                    else Toast.error(msg || ((walletName || '钱包') + ' 连接失败'));
                }
            },

            async loginWithWalletConnect(qrContainerId) {
                try {
                    var cfgResult = await apiJson(API_BASE + '/config/public', { auth: false, fallback: {} });
                    var cfg = cfgResult.data;
                    var projectId = cfg && cfg.walletconnect_project_id ? cfg.walletconnect_project_id.trim() : '';
                    if (!projectId) throw new Error('WalletConnect 未配置');
                    var UC = window.UniversalProvider && (window.UniversalProvider.UniversalProvider || window.UniversalProvider);
                    if (!UC) throw new Error('UniversalProvider 未加载');
                    var provider = await UC.init({
                        projectId: projectId,
                        metadata: {
                            name: '诡话',
                            description: 'Web3 灵异文学社区',
                            url: location.origin,
                            icons: [location.origin + '/static/logo.svg']
                        }
                    });
                    var accountsInSession = provider.session && provider.session.namespaces && provider.session.namespaces.eip155 && provider.session.namespaces.eip155.accounts;
                    if (accountsInSession && accountsInSession.length) {
                        var activeAddress = accountsInSession[0].split(':')[2];
                        await this.handleWeb3Verify(activeAddress, provider, true);
                        return;
                    }
                    var qrWrap = document.getElementById(qrContainerId);
                    if (qrWrap) {
                        qrWrap.style.display = 'block';
                        qrWrap.hidden = false;
                        qrWrap.innerHTML = '<p class="wallet-select-qr-hint">请使用币安钱包 / Trust Wallet 扫码</p>';
                    }
                    provider.on('display_uri', function (uri) {
                        if (!qrWrap) return;
                        qrWrap.hidden = false;
                        qrWrap.innerHTML = '<p class="wallet-select-qr-hint">请使用币安钱包 / Trust Wallet 扫码</p>';
                        new QRCode(qrWrap, { text: uri, width: 220, height: 220 });
                    });
                    await provider.connect({
                        namespaces: {
                            eip155: {
                                methods: ['personal_sign'],
                                chains: ['eip155:56'],
                                events: ['accountsChanged', 'chainChanged']
                            }
                        }
                    });
                    var accounts = provider.session && provider.session.namespaces && provider.session.namespaces.eip155 && provider.session.namespaces.eip155.accounts;
                    if (!accounts || !accounts.length) throw new Error('未获取到钱包地址');
                    var address = accounts[0].split(':')[2];
                    await this.handleWeb3Verify(address, provider, true);
                } catch (e) {
                    var msg = String((e && e.message) || e || '');
                    if (msg.includes('reject')) Toast.info('用户取消了扫码');
                    else Toast.error(msg || 'WalletConnect 连接失败');
                }
            },

            async loginWithBinance() {
                return this.openWalletSelector();
            },

            async loginWeb2(username, password) {
                var btn = document.querySelector('#loginForm button[type="submit"]');
                if (btn) { btn.disabled = true; btn.textContent = '登录中...'; }
                try {
                    var result = await fetchJsonSafe(API_BASE + '/auth/web2/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: username, password: password })
                    }, { fallback: {}, errorMessage: '登录失败' });
                    if (result.res.ok) this.success(result.data);
                    else Toast.error(result.data.error || '登录失败');
                } catch (_) {
                    Toast.error('网络错误');
                } finally {
                    if (btn) { btn.disabled = false; btn.textContent = '登录'; }
                }
            },

            async changePassword() {
                var username = (document.getElementById('cpUsername') || {}).value;
                var oldPassword = (document.getElementById('cpOldPassword') || {}).value;
                var newPassword = (document.getElementById('cpNewPassword') || {}).value;
                var confirmPassword = (document.getElementById('cpConfirmPassword') || {}).value;
                if (!username || !oldPassword || !newPassword) return Toast.error('请填写用户名、原密码和新密码');
                if (newPassword !== confirmPassword) return Toast.error('两次输入的新密码不一致');
                try {
                    var result = await fetchJsonSafe(API_BASE + '/auth/web2/change-password', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username: username, old_password: oldPassword, new_password: newPassword })
                    }, { fallback: {}, errorMessage: '修改失败' });
                    if (result.res.ok) {
                        Toast.success(result.data.message || '密码已修改');
                        this.toggleForm('login');
                    } else {
                        Toast.error(result.data.error || '修改失败');
                    }
                } catch (_) {
                    Toast.error('网络错误');
                }
            },

            async register() {
                var username = ((document.getElementById('regUsername') || {}).value || '').trim();
                var password = (document.getElementById('regPassword') || {}).value || '';
                if (!username) return Toast.error('请填写用户名');
                if (!password) return Toast.error('请填写密码');
                if (password.length < 6) return Toast.error('密码至少 6 位');
                var result = await apiJson(API_BASE + '/auth/web2/register', {
                    method: 'POST',
                    body: { username: username, password: password },
                    auth: false,
                    fallback: {}
                });
                var res = result.res;
                var data = result.data;
                if (res.ok) this.success(data);
                else Toast.error(data.error || '注册失败');
            },

            success(data) {
                if (authState && authState.markLoggedIn) authState.markLoggedIn();
                setCurrentUser(data.user);
                UI.updateAuth();
                Modal.close('walletSelectModal');
                Modal.close('loginModal');
                Toast.success('认证成功');
                Post.load({ sort: Post.currentSort || 'new' });
            },

            async logout() {
                if (this.wcProvider) {
                    try { await this.wcProvider.disconnect(); } catch (_) {}
                    this.wcProvider = null;
                }
                try {
                    await apiJson(API_BASE + '/auth/logout', {
                        method: 'POST',
                        auth: false,
                        check401: false,
                        fallback: {}
                    });
                } catch (_) {}
                if (authState && authState.clear) authState.clear();
                setCurrentUser(null);
                UI.updateAuth();
                Toast.info('已退出');
                navigateWithTransition('/');
            },

            checkLoginExpiry() {
                var loginAt = localStorage.getItem('login_at');
                if (!(authState && authState.hasSessionHint && authState.hasSessionHint()) || !loginAt) return;
                var elapsed = Date.now() - parseInt(loginAt, 10);
                var twentyThreeHours = 23 * 60 * 60 * 1000;
                if (elapsed >= twentyThreeHours && !sessionStorage.getItem('login_expiry_warned')) {
                    sessionStorage.setItem('login_expiry_warned', '1');
                    if (Toast && Toast.warning) Toast.warning('登录即将过期，请重新登录');
                    else if (Toast && Toast.info) Toast.info('登录即将过期，请重新登录');
                }
            },

            async bindWallet() {
                if (!window.BinanceChain && !window.ethereum) return Toast.error('请安装币安钱包或 MetaMask');
                try {
                    var bindProvider = window.BinanceChain || window.ethereum;
                    var accounts = await bindProvider.request({ method: 'eth_requestAccounts' });
                    var address = accounts[0];
                    var nonceResp = await fetchJsonSafe(API_BASE + '/user/bind_wallet/nonce', {}, { fallback: {}, errorMessage: '获取绑定 nonce 失败' });
                    var nonce = nonceResp.data && nonceResp.data.nonce;
                    if (!nonceResp.res.ok || !nonce) {
                        Toast.error((nonceResp.data && nonceResp.data.error) || '获取绑定签名失败');
                        return;
                    }
                    var currentUser = getCurrentUser();
                    var message = 'Bind wallet ' + address + ' to account ' + currentUser.id + ' on ' + location.host + ': ' + nonce;
                    var signature;
                    try {
                        signature = await this.requestPersonalSign(bindProvider, address, message);
                    } catch (_) {
                        return Toast.error('签名被拒绝或钱包不支持');
                    }
                    var result = await fetchJsonSafe(API_BASE + '/user/bind_wallet', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ address: address, signature: signature, message: message })
                    }, { fallback: {}, errorMessage: '绑定失败' });
                    if (result.res.ok) {
                        Toast.success('绑定成功');
                        setCurrentUser(result.data.user);
                        UI.updateAuth();
                    } else {
                        Toast.error(result.data.error);
                    }
                } catch (e) {
                    Toast.error('绑定失败: ' + e.message);
                }
            },

            checkAndGoStudio() {
                if (getCurrentUser()) navigateWithTransition('/studio');
                else {
                    Toast.info('请先登录');
                    Modal.open('loginModal');
                }
            }
        };
    };
})();
