(function () {
    'use strict';

    const API_BASE = window.location.origin + '/api';
    const parseJsonSafe = window.parseJsonSafe;

    function getSafeNextPath() {
        const params = new URLSearchParams(window.location.search || '');
        const raw = (params.get('next') || '').trim();
        if (!raw) return '/';
        try {
            const u = new URL(raw, window.location.origin);
            if (u.origin !== window.location.origin) return '/';
            return (u.pathname || '/') + (u.search || '') + (u.hash || '');
        } catch (_) {
            return '/';
        }
    }

    function goAfterLogin() {
        const target = getSafeNextPath();
        if (typeof navigateWithTransition === 'function') navigateWithTransition(target);
        else window.location.href = target;
    }

    function setMode(mode) {
        const loginForm = document.getElementById('loginForm');
        const registerForm = document.getElementById('registerForm');
        const passwordForm = document.getElementById('passwordForm');
        const modeLoginBtn = document.getElementById('modeLoginBtn');
        const modeRegisterBtn = document.getElementById('modeRegisterBtn');
        const modePasswordBtn = document.getElementById('modePasswordBtn');

        loginForm.style.display = (mode === 'login') ? '' : 'none';
        registerForm.style.display = (mode === 'register') ? '' : 'none';
        passwordForm.style.display = (mode === 'password') ? '' : 'none';

        modeLoginBtn.className = mode === 'login' ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
        modeRegisterBtn.className = mode === 'register' ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
        modePasswordBtn.className = mode === 'password' ? 'btn btn-primary btn-sm' : 'btn btn-ghost btn-sm';
    }

    function saveLogin(data) {
        if (!data || !data.token) return false;
        localStorage.setItem('token', data.token);
        localStorage.setItem('login_at', String(Date.now()));
        sessionStorage.removeItem('login_expiry_warned');
        return true;
    }

    function closeWalletSelector() {
        const modal = document.getElementById('loginWalletSelectModal');
        if (modal) modal.classList.remove('active');
    }

    async function copyText(text, successMsg) {
        const value = (text || '').trim();
        if (!value) return false;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(value);
            } else {
                const ta = document.createElement('textarea');
                ta.value = value;
                document.body.appendChild(ta);
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            if (successMsg && window.Toast && Toast.success) Toast.success(successMsg);
            return true;
        } catch (_) {
            return false;
        }
    }

    async function openBinanceAppGuide() {
        const copied = await copyText(window.location.href, '已复制当前页面链接');
        const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || '');
        if (isMobile) {
            Toast.info(copied ? '请到币安 App 的钱包浏览器中粘贴刚复制的链接打开本站' : '请在币安 App 的钱包浏览器中打开本站');
        } else {
            Toast.info(copied ? '请在手机币安 App 的钱包浏览器中粘贴刚复制的链接打开本站' : '请在手机币安 App 的钱包浏览器中打开本站');
        }
    }

    async function getWalletChoices() {
        const installed = [];
        const hasBinance = !!window.BinanceChain;
        const hasMetaMask = !!(window.ethereum && window.ethereum.isMetaMask);
        const hasGenericInjected = !!(window.ethereum && !hasMetaMask && !hasBinance);
        if (hasBinance) {
            installed.push({ id: 'binance', icon: '🟡', name: 'Binance Wallet', sub: '已安装 · 推荐（BSC）' });
        }
        if (hasMetaMask) {
            installed.push({ id: 'metamask', icon: '🦊', name: 'MetaMask', sub: '已安装' });
        }
        let walletConnectEnabled = false;
        let walletConnectSub = '扫码登录（手机钱包）';
        try {
            const cfgRes = await fetch(API_BASE + '/config/public');
            const cfg = await parseJsonSafe(cfgRes, {});
            const projectId = cfg && cfg.walletconnect_project_id ? cfg.walletconnect_project_id.trim() : '';
            walletConnectEnabled = !!(projectId && window.UniversalProvider);
            if (!projectId) walletConnectSub = '站点暂未配置 WalletConnect';
            else if (!window.UniversalProvider) walletConnectSub = 'WalletConnect 组件未加载';
        } catch (_) {
            walletConnectSub = 'WalletConnect 配置读取失败';
        }
        const others = [
            { id: 'binance_app', icon: '🟨', name: 'Binance App', sub: '手机端在币安 App 内置钱包/浏览器打开本站' },
            { id: 'walletconnect', icon: '🔗', name: 'WalletConnect', sub: walletConnectSub, disabled: !walletConnectEnabled }
        ];
        if (hasGenericInjected) {
            others.push({ id: 'browser', icon: '🌐', name: 'Browser Wallet', sub: '使用当前浏览器注入钱包' });
        }
        return { installed, others };
    }

    async function requestPersonalSign(provider, address, message) {
        try {
            return await provider.request({ method: 'personal_sign', params: [message, address] });
        } catch (_) {
            try {
                return await provider.request({ method: 'personal_sign', params: [address, message] });
            } catch (_) {
                throw new Error('签名被拒绝或钱包不支持');
            }
        }
    }

    async function verifyAddressLogin(address, provider) {
        const nonceRes = await fetch(API_BASE + '/auth/nonce?address=' + encodeURIComponent(address));
        const nonceData = await parseJsonSafe(nonceRes, {});
        if (!nonceRes.ok || !nonceData.nonce) {
            throw new Error((nonceData && nonceData.error) || '获取签名挑战失败');
        }
        const message = 'Sign this message to login to ' + window.location.host + ': ' + nonceData.nonce;
        const signature = await requestPersonalSign(provider, address, message);
        const verifyRes = await fetch(API_BASE + '/auth/verify', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ address: address, signature: signature, message: message })
        });
        const verifyData = await parseJsonSafe(verifyRes, {});
        if (!verifyRes.ok || !verifyData.token) {
            throw new Error((verifyData && verifyData.error) || '钱包登录失败');
        }
        saveLogin(verifyData);
        closeWalletSelector();
        Toast.success('登录成功');
        goAfterLogin();
    }

    async function loginWithInjected(provider, walletName) {
        if (!provider) {
            Toast.error(`${walletName || '钱包'} 未检测到`);
            return;
        }
        try {
            const accounts = await provider.request({ method: 'eth_requestAccounts' });
            const address = (accounts && accounts[0]) ? accounts[0] : '';
            if (!address) throw new Error('未获取到钱包地址');
            await verifyAddressLogin(address, provider);
        } catch (e) {
            const msg = String((e && e.message) || e || '');
            if ((e && e.code === 4001) || msg.includes('reject')) Toast.info('已取消授权');
            else Toast.error(msg || `${walletName || '钱包'} 登录失败`);
        }
    }

    async function loginWithWalletConnect(qrContainerId) {
        try {
            const cfgRes = await fetch(API_BASE + '/config/public');
            const cfg = await parseJsonSafe(cfgRes, {});
            const projectId = cfg && cfg.walletconnect_project_id ? cfg.walletconnect_project_id.trim() : '';
            if (!projectId) throw new Error('WalletConnect 未配置');
            const UC = window.UniversalProvider && (window.UniversalProvider.UniversalProvider || window.UniversalProvider);
            if (!UC) throw new Error('UniversalProvider 未加载');
            const provider = await UC.init({
                projectId: projectId,
                metadata: {
                    name: '诡话',
                    description: 'Web3 灵异文学社区',
                    url: location.origin,
                    icons: [location.origin + '/static/logo.svg']
                }
            });

            const sessionAccounts = provider.session && provider.session.namespaces && provider.session.namespaces.eip155 && provider.session.namespaces.eip155.accounts;
            if (sessionAccounts && sessionAccounts.length) {
                await verifyAddressLogin(sessionAccounts[0].split(':')[2], provider);
                return;
            }

            const qrWrap = document.getElementById(qrContainerId);
            if (qrWrap) {
                qrWrap.style.display = 'block';
                qrWrap.innerHTML = '<p style="margin-bottom:0.55rem; color:var(--text-secondary);">请使用币安钱包 / Trust Wallet 扫码</p>';
            }
            provider.on('display_uri', function (uri) {
                if (!qrWrap) return;
                qrWrap.innerHTML = '<p style="margin-bottom:0.55rem; color:var(--text-secondary);">请使用币安钱包 / Trust Wallet 扫码</p>';
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
            const accounts = provider.session && provider.session.namespaces && provider.session.namespaces.eip155 && provider.session.namespaces.eip155.accounts;
            if (!accounts || !accounts.length) throw new Error('未获取到钱包地址');
            await verifyAddressLogin(accounts[0].split(':')[2], provider);
        } catch (e) {
            const msg = String((e && e.message) || e || '');
            if (msg.includes('reject')) Toast.info('用户取消了扫码');
            else Toast.error(msg || 'WalletConnect 登录失败');
        }
    }

    async function openWalletSelector() {
        const modal = document.getElementById('loginWalletSelectModal');
        const listEl = document.getElementById('loginWalletSelectList');
        const qrWrap = document.getElementById('loginWalletSelectQr');
        if (!modal || !listEl) {
            Toast.error('钱包面板加载失败');
            return;
        }
        if (qrWrap) {
            qrWrap.style.display = 'none';
            qrWrap.innerHTML = '';
        }
        const groups = await getWalletChoices();
        const renderItem = function (item) {
            return `
                <button type="button" class="wallet-select-item" data-wallet="${item.id}" ${item.disabled ? 'disabled' : ''}>
                    <span class="wallet-select-icon">${item.icon}</span>
                    <span class="wallet-select-meta">
                        <span class="wallet-select-name">${item.name}</span>
                        <span class="wallet-select-sub">${item.sub || ''}</span>
                    </span>
                </button>
            `;
        };
        listEl.innerHTML = `
            <div class="wallet-select-group-title">已安装</div>
            <div class="wallet-select-list">
                ${groups.installed.length ? groups.installed.map(renderItem).join('') : '<div class="wallet-select-sub" style="padding:0.35rem 0.2rem;">未检测到注入钱包，可使用 WalletConnect 扫码登录。</div>'}
            </div>
            <div class="wallet-select-group-title">其他方式</div>
            <div class="wallet-select-list">${groups.others.map(renderItem).join('')}</div>
        `;

        listEl.querySelectorAll('button[data-wallet]').forEach(function (btn) {
            btn.addEventListener('click', async function () {
                const key = btn.getAttribute('data-wallet') || '';
                if (!key || btn.disabled) return;
                if (key === 'walletconnect') {
                    await loginWithWalletConnect('loginWalletSelectQr');
                    return;
                }
                if (key === 'binance_app') {
                    await openBinanceAppGuide();
                    return;
                }
                if (key === 'binance') {
                    await loginWithInjected(window.BinanceChain, 'Binance Wallet');
                    return;
                }
                if (key === 'metamask') {
                    await loginWithInjected(window.ethereum, 'MetaMask');
                    return;
                }
                if (key === 'browser') {
                    await loginWithInjected(window.BinanceChain || window.ethereum, 'Browser Wallet');
                }
            });
        });
        modal.classList.add('active');
    }

    async function init() {
        const modeLoginBtn = document.getElementById('modeLoginBtn');
        const modeRegisterBtn = document.getElementById('modeRegisterBtn');
        const modePasswordBtn = document.getElementById('modePasswordBtn');
        const walletLoginBtn = document.getElementById('walletLoginBtn');
        const loginForm = document.getElementById('loginForm');
        const registerForm = document.getElementById('registerForm');
        const passwordForm = document.getElementById('passwordForm');

        modeLoginBtn.addEventListener('click', function () { setMode('login'); });
        modeRegisterBtn.addEventListener('click', function () { setMode('register'); });
        modePasswordBtn.addEventListener('click', function () { setMode('password'); });
        walletLoginBtn.addEventListener('click', openWalletSelector);

        loginForm.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            const btn = document.getElementById('loginSubmitBtn');
            btn.disabled = true;
            btn.textContent = '登录中...';
            const username = (document.getElementById('loginUsername').value || '').trim();
            const password = (document.getElementById('loginPassword').value || '');
            try {
                const res = await fetch(API_BASE + '/auth/web2/login', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: username, password: password })
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok || !saveLogin(data)) {
                    Toast.error((data && data.error) || '登录失败');
                    return;
                }
                Toast.success('登录成功');
                goAfterLogin();
            } catch (_) {
                Toast.error('网络错误');
            } finally {
                btn.disabled = false;
                btn.textContent = '登录';
            }
        });

        registerForm.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            const btn = document.getElementById('registerSubmitBtn');
            btn.disabled = true;
            btn.textContent = '注册中...';
            const username = (document.getElementById('registerUsername').value || '').trim();
            const password = (document.getElementById('registerPassword').value || '');
            if (!username) {
                Toast.error('请填写用户名');
                btn.disabled = false;
                btn.textContent = '创建账号并登录';
                return;
            }
            if (password.length < 6) {
                Toast.error('密码至少 6 位');
                btn.disabled = false;
                btn.textContent = '创建账号并登录';
                return;
            }
            try {
                const res = await fetch(API_BASE + '/auth/web2/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ username: username, password: password })
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok || !saveLogin(data)) {
                    Toast.error((data && data.error) || '注册失败');
                    return;
                }
                Toast.success('注册成功');
                goAfterLogin();
            } catch (_) {
                Toast.error('网络错误');
            } finally {
                btn.disabled = false;
                btn.textContent = '创建账号并登录';
            }
        });

        passwordForm.addEventListener('submit', async function (ev) {
            ev.preventDefault();
            const btn = document.getElementById('passwordSubmitBtn');
            btn.disabled = true;
            btn.textContent = '提交中...';
            const username = (document.getElementById('passwordUsername').value || '').trim();
            const oldPassword = (document.getElementById('passwordOld').value || '');
            const newPassword = (document.getElementById('passwordNew').value || '');
            if (!username || !oldPassword || !newPassword) {
                Toast.error('请填写完整信息');
                btn.disabled = false;
                btn.textContent = '确认修改';
                return;
            }
            if (newPassword.length < 6) {
                Toast.error('新密码至少 6 位');
                btn.disabled = false;
                btn.textContent = '确认修改';
                return;
            }
            try {
                const res = await fetch(API_BASE + '/auth/web2/change-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        username: username,
                        old_password: oldPassword,
                        new_password: newPassword
                    })
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    Toast.error((data && data.error) || '修改失败');
                    return;
                }
                Toast.success((data && data.message) || '密码已修改，请重新登录');
                setMode('login');
            } catch (_) {
                Toast.error('网络错误');
            } finally {
                btn.disabled = false;
                btn.textContent = '确认修改';
            }
        });

        const token = localStorage.getItem('token');
        if (token) {
            try {
                const res = await fetch(API_BASE + '/user/me', {
                    headers: { 'Authorization': 'Bearer ' + token }
                });
                if (res.ok) {
                    Toast.info('你已登录，正在进入页面...');
                    setTimeout(goAfterLogin, 120);
                    return;
                }
                if (res.status === 401) {
                    localStorage.removeItem('token');
                    localStorage.removeItem('login_at');
                }
            } catch (_) {}
        }

        setMode('login');
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
