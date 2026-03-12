(function () {
    'use strict';

    const API_BASE = window.location.origin + '/api';

    function parseJsonSafe(res, fallback) {
        return res.json().catch(function () { return fallback || {}; });
    }

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

    async function web3Login() {
        const provider = window.ethereum || window.BinanceChain;
        if (!provider) {
            Toast.error('未检测到钱包插件');
            return;
        }
        try {
            const accounts = await provider.request({ method: 'eth_requestAccounts' });
            const address = (accounts && accounts[0]) ? accounts[0] : '';
            if (!address) {
                Toast.error('未获取到钱包地址');
                return;
            }

            const nonceRes = await fetch(API_BASE + '/auth/nonce?address=' + encodeURIComponent(address));
            const nonceData = await parseJsonSafe(nonceRes, {});
            if (!nonceRes.ok || !nonceData.nonce) {
                Toast.error((nonceData && nonceData.error) || '获取签名挑战失败');
                return;
            }

            const message = 'Sign this message to login to ' + window.location.host + ': ' + nonceData.nonce;
            let signature = '';
            try {
                signature = await provider.request({ method: 'personal_sign', params: [message, address] });
            } catch (_) {
                try {
                    signature = await provider.request({ method: 'personal_sign', params: [address, message] });
                } catch (err2) {
                    Toast.error('签名被拒绝或钱包不支持');
                    return;
                }
            }

            const verifyRes = await fetch(API_BASE + '/auth/verify', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ address: address, signature: signature, message: message })
            });
            const verifyData = await parseJsonSafe(verifyRes, {});
            if (!verifyRes.ok || !verifyData.token) {
                Toast.error((verifyData && verifyData.error) || '钱包登录失败');
                return;
            }

            saveLogin(verifyData);
            Toast.success('登录成功');
            goAfterLogin();
        } catch (e) {
            Toast.error((e && e.message) || '钱包登录失败');
        }
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
        walletLoginBtn.addEventListener('click', web3Login);

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
