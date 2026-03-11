        const API_BASE = window.location.origin + '/api';
        let currentUser = null;
        const stripHtml = (s) => (s == null ? '' : String(s)).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
        const escapeAttr = (s) => (s == null ? '' : String(s))
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
        const parseJsonSafe = async (res, fallback = {}) => {
            try {
                return await res.json();
            } catch (_) {
                return fallback;
            }
        };
        const fetchJsonSafe = async (url, options = {}, cfg = {}) => {
            const conf = cfg || {};
            const fallback = Object.prototype.hasOwnProperty.call(conf, 'fallback') ? conf.fallback : {};
            const errorMessage = conf.errorMessage || '请求失败';
            const checkUnauthorized = !!conf.checkUnauthorized;
            const res = await fetch(url, options);
            if (checkUnauthorized && typeof handle401 === 'function' && handle401(res)) {
                const e = new Error('登录状态已失效');
                e.code = 'AUTH_401';
                e.response = res;
                throw e;
            }
            const data = await parseJsonSafe(res, fallback);
            if (conf.throwOnNotOk && !res.ok) {
                const e = new Error((data && data.error) || `${errorMessage}(${res.status})`);
                e.status = res.status;
                e.data = data;
                e.response = res;
                throw e;
            }
            return { res, data };
        };
        const mentionifyText = (text) => {
            const safe = escapeHtml(text || '');
            return safe.replace(/(^|[\s(（\[【])@([A-Za-z0-9_\u4e00-\u9fff]{2,32})/g, (all, prefix, token) => {
                const encoded = encodeURIComponent(token || '');
                return `${prefix}<a class="mention-link" href="/profile?user=${encoded}" data-no-transition="1">@${token}</a>`;
            });
        };
        let lastPointerClientY = null;
        const recordPointerY = (ev) => {
            if (!ev) return;
            let y = null;
            if (Number.isFinite(ev.clientY) && Number(ev.clientY) > 0) {
                y = Number(ev.clientY);
            } else if (ev.touches && ev.touches[0] && Number.isFinite(ev.touches[0].clientY)) {
                y = Number(ev.touches[0].clientY);
            }
            if (Number.isFinite(y) && Number(y) > 0) lastPointerClientY = y;
        };
        window.addEventListener('pointerdown', recordPointerY, { capture: true, passive: true });
        window.addEventListener('mousedown', recordPointerY, { capture: true, passive: true });
        window.addEventListener('touchstart', recordPointerY, { capture: true, passive: true });
        const detailScrollStore = {
            _timer: null,
            key(postId) {
                const uid = currentUser && currentUser.id ? String(currentUser.id) : 'guest';
                return `post_scroll_${uid}_${postId}`;
            },
            save(postId, scrollTop, maxScroll) {
                if (!postId || maxScroll <= 0) return;
                const pct = Math.max(0, Math.min(100, Math.round((scrollTop / maxScroll) * 100)));
                const payload = { top: Math.max(0, Math.round(scrollTop)), pct: pct, t: Date.now() };
                try { localStorage.setItem(this.key(postId), JSON.stringify(payload)); } catch (_) {}
            },
            read(postId) {
                try {
                    const raw = localStorage.getItem(this.key(postId));
                    if (!raw) return null;
                    const obj = JSON.parse(raw);
                    if (!obj || typeof obj.top !== 'number') return null;
                    return obj;
                } catch (_) {
                    return null;
                }
            },
            bind(postId, scrollEl) {
                if (!scrollEl || !postId) return;
                const handler = () => {
                    if (this._timer) clearTimeout(this._timer);
                    this._timer = setTimeout(() => {
                        const maxScroll = Math.max(0, scrollEl.scrollHeight - scrollEl.clientHeight);
                        this.save(postId, scrollEl.scrollTop, maxScroll);
                    }, 120);
                };
                scrollEl.addEventListener('scroll', handler, { passive: true });
                scrollEl.dataset.scrollTrackPost = String(postId);
                scrollEl.__ghScrollTrackHandler = handler;
            },
            unbind(scrollEl) {
                if (!scrollEl || !scrollEl.__ghScrollTrackHandler) return;
                scrollEl.removeEventListener('scroll', scrollEl.__ghScrollTrackHandler);
                delete scrollEl.__ghScrollTrackHandler;
                delete scrollEl.dataset.scrollTrackPost;
            }
        };

        const Auth = {
            async init() {
                const token = localStorage.getItem('token');
                if (token) {
                    await this.fetchMe();
                    this.checkLoginExpiry();
                    setInterval(() => this.checkLoginExpiry(), 5 * 60 * 1000);
                } else {
                    if(localStorage.getItem('token') === 'undefined') localStorage.removeItem('token');
                }
                UI.updateAuth();
                SiteNotice.load();
                Onboarding.load();
                Checkin.load();
                GroupLinks.load();
                if (localStorage.getItem('token') && typeof Notification !== 'undefined' && Notification.load) {
                    setInterval(function() {
                        if (document.visibilityState === 'visible') Notification.load();
                    }, 60000);
                }
            },

            async fetchMe() {
                try {
                    const res = await fetch(`${API_BASE}/user/me`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    if (handle401(res)) return;
                    if (res.ok) currentUser = await parseJsonSafe(res, {});
                    else this.logout();
                } catch(_) { /* 静默处理，避免生产环境泄露 */ }
            },

            toggleForm(mode) {
                const login = document.getElementById('loginFormContainer');
                const reg = document.getElementById('registerFormContainer');
                const cp = document.getElementById('changePasswordFormContainer');
                login.style.display = (mode === 'login') ? 'block' : 'none';
                reg.style.display = (mode === 'register') ? 'block' : 'none';
                if (cp) cp.style.display = (mode === 'changePassword') ? 'block' : 'none';
            },

            async parseJsonSafe(res) {
                return parseJsonSafe(res, {});
            },

            async fetchNonceForAddress(address) {
                const nonceRes = await fetch(`${API_BASE}/auth/nonce?address=${encodeURIComponent(address)}`);
                const nonceData = await this.parseJsonSafe(nonceRes);
                if (!nonceRes.ok || !nonceData || !nonceData.nonce) {
                    throw new Error((nonceData && nonceData.error) || '获取签名消息失败，请重试');
                }
                return String(nonceData.nonce);
            },

            async requestPersonalSign(provider, address, message) {
                const normalizeSig = function (result) {
                    if (result && typeof result === 'object' && result.result) return result.result;
                    return result;
                };
                try {
                    const signRes = await provider.request({
                        method: 'personal_sign',
                        params: [message, address]
                    });
                    return normalizeSig(signRes);
                } catch (_) {
                    try {
                        const signRes2 = await provider.request({
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
                    // Mobile: 无注入钱包时引导用 App 内置浏览器打开
                    const isMobile = /iPhone|iPad|iPod|Android/i.test(navigator.userAgent);
                    if (isMobile) {
                        const fullUrl = window.location.href;
                        const dappHost = window.location.host;
                        const tryMetaMask = () => { window.location.href = `https://metamask.app.link/dapp/${dappHost}`; };
                        const copyAndGuideBinance = () => {
                            navigator.clipboard.writeText(fullUrl).then(() => {
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
                    let accounts;
                    const provider = window.BinanceChain || window.ethereum;
                    if (!provider) {
                        return Toast.error('请安装币安钱包、MetaMask 或其他 Web3 钱包');
                    }
                    Toast.info('正在拉起钱包，请在弹出的窗口中授权…');
                    try {
                        accounts = await provider.request({ method: 'eth_requestAccounts' });
                    } catch (e) {
                        if (e.code === 4001 || e.message && e.message.includes('reject')) return Toast.error('已取消授权');
                        return Toast.error('无法连接钱包: ' + (e.message || '请重试'));
                    }
                    if (!accounts || accounts.length === 0) return Toast.error('未检测到账户');
                    await this.handleWeb3Verify(accounts[0], provider, false);
                } catch(e) { Toast.error(e && e.message ? e.message : 'Web3 登录失败'); }
            },

            async handleWeb3Verify(address, provider, isWalletConnect = false) {
                try {
                    const nonce = await this.fetchNonceForAddress(address);
                    const message = `Sign this message to login to ${location.host}: ${nonce}`;
                    const signature = await this.requestPersonalSign(provider, address, message);
                    if (!signature) throw new Error('签名结果为空，请重试');

                    const verifyRes = await fetch(`${API_BASE}/auth/verify`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ address, signature, message })
                    });
                    const verifyData = await this.parseJsonSafe(verifyRes);
                    if (!verifyRes.ok) {
                        throw new Error((verifyData && verifyData.error) || '验证失败，请稍后重试');
                    }
                    if (!verifyData || !verifyData.token) throw new Error('服务返回异常，请稍后重试');

                    Auth.success(verifyData);
                    if (isWalletConnect) Auth.wcProvider = provider;
                } catch (e) {
                    console.error(e);
                    throw e;
                }
            },

            async loginWithBinance() {
                try {
                    if (window.ethereum || window.BinanceChain) {
                        const provider = window.ethereum || window.BinanceChain;
                        const accounts = await provider.request({ method: 'eth_requestAccounts' });
                        if (accounts && accounts.length) {
                            return await this.handleWeb3Verify(accounts[0], provider, false);
                        }
                    }

                    const cfgRes = await fetch(`${API_BASE}/config/public`);
                    const cfg = await this.parseJsonSafe(cfgRes);
                    const projectId = cfg && cfg.walletconnect_project_id ? cfg.walletconnect_project_id.trim() : '';
                    if (!projectId) throw new Error('WalletConnect 未配置');

                    const UC = window.UniversalProvider && (window.UniversalProvider.UniversalProvider || window.UniversalProvider);
                    if (!UC) throw new Error('UniversalProvider 未加载');

                    const provider = await UC.init({
                        projectId,
                        metadata: {
                            name: '诡话',
                            description: 'Web3 灵异文学社区',
                            url: location.origin,
                            icons: [location.origin + '/static/logo.svg']
                        }
                    });

                    const accountsInSession = provider.session && provider.session.namespaces && provider.session.namespaces.eip155 && provider.session.namespaces.eip155.accounts;
                    if (accountsInSession && accountsInSession.length) {
                        const address = accountsInSession[0].split(':')[2];
                        return await this.handleWeb3Verify(address, provider, true);
                    }

                    const qrWrap = document.getElementById('wc-qrcode');
                    if (qrWrap) { qrWrap.style.display = 'block'; qrWrap.innerHTML = ''; }
                    let qrInstance = null;

                    provider.on('display_uri', (uri) => {
                        if (qrWrap) {
                            qrWrap.innerHTML = '<p style="margin-bottom:8px;">请使用币安钱包或其他钱包扫码</p>';
                            qrInstance = new QRCode(qrWrap, { text: uri, width: 220, height: 220 });
                        }
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

                    const address = accounts[0].split(':')[2];
                    if (qrWrap) qrWrap.style.display = 'none';

                    await this.handleWeb3Verify(address, provider, true);
                } catch (e) {
                    console.error(e);
                    const msg = String(e.message || e);
                    if (msg.includes('reject')) Toast.info('用户取消了扫码');
                    else Toast.error(msg || '连接失败，请重试');
                }
            },

            async loginWeb2(username, password) {
                const btn = document.querySelector('#loginForm button[type="submit"]');
                if(btn) { btn.disabled = true; btn.textContent = '登录中...'; }

                try {
                    const { res, data } = await fetchJsonSafe(`${API_BASE}/auth/web2/login`, {
                        method: 'POST', headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ username, password })
                    }, { fallback: {}, errorMessage: '登录失败' });
                    if (res.ok) this.success(data);
                    else Toast.error(data.error || '登录失败');
                } catch(e) {
                    Toast.error('网络错误');
                } finally {
                    if(btn) { btn.disabled = false; btn.textContent = '登录'; }
                }
            },

            async changePassword() {
                const username = (document.getElementById('cpUsername') || {}).value;
                const oldPassword = (document.getElementById('cpOldPassword') || {}).value;
                const newPassword = (document.getElementById('cpNewPassword') || {}).value;
                const confirmPassword = (document.getElementById('cpConfirmPassword') || {}).value;
                if (!username || !oldPassword || !newPassword) {
                    return Toast.error('请填写用户名、原密码和新密码');
                }
                if (newPassword !== confirmPassword) {
                    return Toast.error('两次输入的新密码不一致');
                }
                try {
                    const { res, data } = await fetchJsonSafe(`${API_BASE}/auth/web2/change-password`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, old_password: oldPassword, new_password: newPassword })
                    }, { fallback: {}, errorMessage: '修改失败' });
                    if (res.ok) {
                        Toast.success(data.message || '密码已修改');
                        Auth.toggleForm('login');
                    } else {
                        Toast.error(data.error || '修改失败');
                    }
                } catch (e) {
                    Toast.error('网络错误');
                }
            },

            async register() {
                const username = (document.getElementById('regUsername').value || '').trim();
                const password = (document.getElementById('regPassword').value || '');
                if (!username) { Toast.error('请填写用户名'); return; }
                if (!password) { Toast.error('请填写密码'); return; }
                if (password.length < 6) { Toast.error('密码至少 6 位'); return; }
                const res = await fetch(`${API_BASE}/auth/web2/register`, {
                    method: 'POST', headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ username, password })
                });
                const data = await parseJsonSafe(res, {});
                if (res.ok) this.success(data);
                else Toast.error(data.error || '注册失败');
            },

            success(data) {
                localStorage.setItem('token', data.token);
                localStorage.setItem('login_at', String(Date.now()));
                sessionStorage.removeItem('login_expiry_warned');
                currentUser = data.user;
                UI.updateAuth();
                Modal.close('loginModal');
                Toast.success('认证成功');
                Post.load({ sort: Post.currentSort || 'new' });
            },

            async logout() {
                if (this.wcProvider) {
                    try { await this.wcProvider.disconnect(); } catch (e) {}
                    this.wcProvider = null;
                }
                localStorage.removeItem('token');
                localStorage.removeItem('login_at');
                sessionStorage.removeItem('login_expiry_warned');
                currentUser = null;
                UI.updateAuth();
                Toast.info('已退出');
                navigateWithTransition('/');
            },

            /** 登录即将过期提醒（无 Refresh Token 时的替代）：接近 24h 弹一次提醒 */
            checkLoginExpiry() {
                const token = localStorage.getItem('token');
                const loginAt = localStorage.getItem('login_at');
                if (!token || !loginAt) return;
                const elapsed = Date.now() - parseInt(loginAt, 10);
                const twentyThreeHours = 23 * 60 * 60 * 1000;
                if (elapsed >= twentyThreeHours && !sessionStorage.getItem('login_expiry_warned')) {
                    sessionStorage.setItem('login_expiry_warned', '1');
                    if (typeof Toast !== 'undefined' && Toast.warning) Toast.warning('登录即将过期，请重新登录');
                    else if (typeof Toast !== 'undefined' && Toast.info) Toast.info('登录即将过期，请重新登录');
                }
            },

            async bindWallet() {
                if (!window.ethereum && !window.BinanceChain) return Toast.error('请安装钱包');
                try {
                    const accounts = await (window.ethereum || window.BinanceChain).request({ method: 'eth_requestAccounts' });
                    const address = accounts[0];

                    const { res: resNonce, data: nonceData } = await fetchJsonSafe(`${API_BASE}/user/bind_wallet/nonce`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    }, { fallback: {}, errorMessage: '获取绑定 nonce 失败' });
                    const nonce = nonceData && nonceData.nonce;
                    if (!resNonce.ok || !nonce) {
                        Toast.error((nonceData && nonceData.error) || '获取绑定签名失败');
                        return;
                    }

                    const message = `Bind wallet ${address} to account ${currentUser.id} on ${location.host}: ${nonce}`;
                    let signature;

                    try {
                         signature = await (window.web3 || new Web3(window.ethereum || window.BinanceChain)).eth.personal.sign(message, address, '');
                    } catch (e) {
                         return Toast.error('签名被拒绝');
                    }

                    const { res, data } = await fetchJsonSafe(`${API_BASE}/user/bind_wallet`, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${localStorage.getItem('token')}`
                        },
                        body: JSON.stringify({ address, signature, message })
                    }, { fallback: {}, errorMessage: '绑定失败' });
                    if(res.ok) {
                        Toast.success('绑定成功');
                        currentUser = data.user;
                        UI.updateAuth();
                    } else {
                        Toast.error(data.error);
                    }
                } catch(e) { Toast.error('绑定失败: ' + e.message); }
            },

            checkAndGoStudio() {
                if(currentUser) navigateWithTransition('/studio');
                else {
                    Toast.info('请先登录');
                    Modal.open('loginModal');
                }
            }
        };

        const Notification = {
            async load() {
                if(!currentUser) return;
                const { res, data } = await fetchJsonSafe(`${API_BASE}/notifications`, {
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                }, { fallback: {}, checkUnauthorized: true, errorMessage: '加载通知失败' });
                if (!res.ok) return;

                const list = document.getElementById('notificationList');
                if(data.notifications && data.notifications.length > 0) {
                    const badgeEl = document.getElementById('notifBadge');
                    if (badgeEl) badgeEl.style.display = data.notifications.some(n => !n.is_read) ? 'block' : 'none';
                    const typeText = (n) => {
                        if (n && n.content) return n.content;
                        if (!n) return '有新动态';
                        if (n.type === 'like') return '点赞了你的帖子';
                        if (n.type === 'reply') return '回复了你的评论';
                        if (n.type === 'comment') return '评论了你的帖子';
                        if (n.type === 'mention') return '提到了你';
                        if (n.type === 'report_result') return '你的举报有了处理结果';
                        if (n.type === 'tip') return '打赏了你的帖子';
                        return '有新动态';
                    };
                    list.innerHTML = data.notifications.map(n => `
                        <div style="padding:0.8rem; border-bottom:1px solid var(--border-color); ${!n.is_read ? 'background:rgba(124,58,237,0.1);' : ''} cursor:pointer;" onclick="Notification.read(${n.id}, ${n.post_id != null ? n.post_id : 'null'})">
                            <div style="font-size:0.9rem; margin-bottom:0.2rem;">
                                <b>${escapeHtml((n.sender && n.sender.nickname) || '系统')}</b> ${escapeHtml(typeText(n))}
                            </div>
                            <div style="font-size:0.8rem; color:var(--text-muted);">${escapeHtml(n.post_title || '')}</div>
                            <div style="font-size:0.7rem; color:var(--text-secondary); margin-top:0.3rem;">${new Date(n.created_at).toLocaleString()}</div>
                        </div>
                    `).join('');
                } else {
                    list.innerHTML = '<div style="padding:1rem; text-align:center; color:var(--text-muted);">暂无消息</div>';
                    const badgeEl = document.getElementById('notifBadge');
                    if (badgeEl) badgeEl.style.display = 'none';
                }
            },

            async read(id, postId) {
                await fetch(`${API_BASE}/notifications/${id}/read`, {
                    method: 'PUT', headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                });
                this.load();
                Modal.close('notificationModal');
                if (postId != null && postId !== undefined) Modal.openDetail(postId);
            },

            async readAll() {
                await fetch(`${API_BASE}/notifications/read_all`, {
                    method: 'PUT', headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                });
                this.load();
            }
        };

        const SiteNotice = {
            async load() {
                try {
                    const res = await fetch(`${API_BASE}/announcements/active`);
                    const data = await parseJsonSafe(res, {});
                    const bar = document.getElementById('siteAnnouncementBar');
                    const titleEl = document.getElementById('siteAnnouncementTitle');
                    const contentEl = document.getElementById('siteAnnouncementContent');
                    if (!bar || !titleEl || !contentEl) return;
                    const ann = data && data.announcement;
                    if (!res.ok || !ann) {
                        bar.hidden = true;
                        return;
                    }
                    const levelMap = {
                        info: '📣 公告',
                        warning: '⚠️ 提醒',
                        critical: '🚨 紧急'
                    };
                    const levelClassMap = {
                        info: 'is-info',
                        warning: 'is-warning',
                        critical: 'is-critical'
                    };
                    bar.classList.remove('is-info', 'is-warning', 'is-critical');
                    bar.classList.add(levelClassMap[ann.level] || 'is-info');
                    titleEl.textContent = levelMap[ann.level] || '📣 公告';
                    contentEl.textContent = `${ann.title}：${ann.content}`;
                    bar.hidden = false;
                } catch (_) {}
            }
        };

        const NoticeCenter = {
            async open(type) {
                const safeType = (type === 'activity') ? 'activity' : 'announcement';
                const titleEl = document.getElementById('noticeCenterTitle');
                const body = document.getElementById('noticeCenterBody');
                if (titleEl) titleEl.textContent = safeType === 'activity' ? '🎉 活动' : '📣 公告';
                if (body) body.innerHTML = '加载中...';
                Modal.open('noticeCenterModal');
                try {
                    const qs = new URLSearchParams({ type: safeType, is_active: '1', page: '1', per_page: '30' });
                    const res = await fetch(`${API_BASE}/announcements?${qs.toString()}`);
                    const data = await parseJsonSafe(res, {});
                    const items = (data && data.announcements) || [];
                    if (!res.ok) throw new Error((data && data.error) || '加载失败');
                    if (!items.length) {
                        if (body) body.innerHTML = `<div style="text-align:center; color:var(--text-muted); padding:1.5rem;">暂无${safeType === 'activity' ? '活动' : '公告'}</div>`;
                        return;
                    }
                    if (body) body.innerHTML = items.map((a) => `
                        <div class="glass" style="padding:0.75rem; border-radius:10px; margin-bottom:0.7rem;">
                            <div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:center; margin-bottom:0.3rem;">
                                <b>${escapeHtml(a.title || '')}</b>
                                <span style="font-size:0.72rem; color:var(--text-muted);">${a.created_at ? new Date(a.created_at).toLocaleDateString() : ''}</span>
                            </div>
                            <div style="font-size:0.85rem; color:var(--text-secondary); line-height:1.7;">${escapeHtml(a.content || '')}</div>
                        </div>
                    `).join('');
                } catch (e) {
                    if (body) body.innerHTML = `<div style="text-align:center; color:var(--accent-red); padding:1.5rem;">${escapeHtml((e && e.message) || '加载失败')}</div>`;
                }
            }
        };
        window.NoticeCenter = NoticeCenter;

        const Onboarding = {
            dismissedInMemory: false,
            defaultTasks() {
                return [
                    { key: 'login', title: '完成登录', done: !!currentUser },
                    { key: 'bind_wallet', title: '绑定钱包', done: false },
                    { key: 'daily_checkin', title: '完成今日签到', done: false },
                    { key: 'publish_first', title: '发布第一篇帖子', done: false },
                    { key: 'verify_archive', title: '查看永存证据', done: false },
                    { key: 'web2_bind_wallet', title: 'Web2 账号绑定钱包', done: false }
                ];
            },
            dismissedKey() {
                const uid = currentUser && currentUser.id ? String(currentUser.id) : 'guest';
                return `onboarding_v2_dismissed_${uid}`;
            },
            hideCard() {
                const card = document.getElementById('onboardingCard');
                if (!card) return;
                card.hidden = true;
                card.style.display = 'none';
                card.setAttribute('aria-hidden', 'true');
            },
            showCard() {
                const card = document.getElementById('onboardingCard');
                if (!card) return;
                card.hidden = false;
                card.style.display = '';
                card.setAttribute('aria-hidden', 'false');
            },
            render(data) {
                const listEl = document.getElementById('onboardingTaskList');
                const progressEl = document.getElementById('onboardingProgress');
                const percentEl = document.getElementById('onboardingPercent');
                const ringEl = document.getElementById('onboardingRing');
                let tasks = Array.isArray(data && data.tasks) ? data.tasks : [];
                if (!tasks.length) tasks = this.defaultTasks();
                const totalRaw = Number(data && data.total);
                const doneRaw = Number(data && data.done_count);
                const total = Number.isFinite(totalRaw) && totalRaw >= 0 ? totalRaw : tasks.length;
                const doneFromTasks = tasks.reduce((n, t) => n + (t && t.done ? 1 : 0), 0);
                const done = Number.isFinite(doneRaw) && doneRaw >= 0 ? doneRaw : doneFromTasks;
                const pct = total > 0 ? Math.round((done / total) * 100) : 0;

                if (progressEl) progressEl.textContent = `${done}/${total}`;
                if (percentEl) percentEl.textContent = `${pct}%`;
                if (ringEl) ringEl.style.setProperty('--progress', `${pct}%`);
                if (listEl) {
                    listEl.innerHTML = tasks.map(t => {
                        const isDone = !!t.done;
                        return `<div class="onboarding-task-item ${isDone ? 'is-done' : ''}">
                            <span class="onboarding-task-check">${isDone ? '✅' : '⬜️'}</span><span>${escapeHtml(t.title || '')}</span>
                        </div>`;
                    }).join('');
                }

                this.showCard();
            },
            isDismissed() {
                if (this.dismissedInMemory) return true;
                try {
                    return localStorage.getItem(this.dismissedKey()) === '1'
                        || sessionStorage.getItem(this.dismissedKey()) === '1';
                } catch (_) {
                    return this.dismissedInMemory;
                }
            },
            bindClose() {
                const btn = document.getElementById('onboardingCloseBtn');
                if (!btn || btn.dataset.bound === '1') return;
                btn.dataset.bound = '1';
                const closeHandler = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    this.dismiss();
                };
                btn.addEventListener('click', closeHandler);
                btn.addEventListener('touchend', closeHandler, { passive: false });
                btn.addEventListener('pointerup', closeHandler);
            },
            dismiss() {
                this.dismissedInMemory = true;
                try {
                    localStorage.setItem(this.dismissedKey(), '1');
                    sessionStorage.setItem(this.dismissedKey(), '1');
                } catch (_) {}
                this.hideCard();
            },
            async load() {
                const card = document.getElementById('onboardingCard');
                if (!card) return;
                this.bindClose();
                if (!currentUser) {
                    this.hideCard();
                    return;
                }
                if (this.isDismissed()) {
                    this.hideCard();
                    return;
                }
                this.render(null);
                try {
                    const token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    const res = await fetch(`${API_BASE}/onboarding/tasks`, {
                        headers: { 'Authorization': `Bearer ${token}` },
                        cache: 'no-store'
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.status === 401) {
                        this.hideCard();
                        return;
                    }
                    if (this.isDismissed()) {
                        this.hideCard();
                        return;
                    }
                    this.render(res.ok ? data : null);
                } catch (_) {
                    if (!this.isDismissed()) this.render(null);
                }
            }
        };
        window.Onboarding = Onboarding;

        const Checkin = {
            hideCard() {
                const card = document.getElementById('checkinCard');
                if (!card) return;
                card.hidden = true;
            },
            showCard() {
                const card = document.getElementById('checkinCard');
                if (!card) return;
                card.hidden = false;
            },
            applyToCurrentUser(status) {
                if (!currentUser || !status) return;
                currentUser.level = status.level;
                currentUser.level_label = status.level_label || currentUser.level_label;
                currentUser.admin_infinite_level = !!status.admin_exempt;
                currentUser.experience_points = status.experience_points;
                currentUser.level_current_exp = status.level_current_exp;
                currentUser.level_next_exp = status.level_next_exp;
                currentUser.level_progress = status.level_progress;
                currentUser.checkin_streak = status.streak;
            },
            render(status) {
                if (!status) {
                    this.hideCard();
                    return;
                }
                this.applyToCurrentUser(status);
                const already = !!status.already_checked;
                const adminExempt = !!status.admin_exempt;
                const streak = Number(status.streak || 0);
                const level = Number(status.level || 1);
                const levelLabel = status.level_label || `Lv.${Math.max(1, level)}`;
                const exp = Number(status.experience_points || 0);
                const cur = Number(status.level_current_exp || 0);
                const next = Math.max(1, Number(status.level_next_exp || 1));
                const pct = Math.max(0, Math.min(100, Math.round((cur / next) * 100)));
                const reward = Math.max(0, Number(status.next_reward || 0));
                const bonusReward = Math.max(0, Number(status.next_bonus_reward || 0));

                const subtitleEl = document.getElementById('checkinSubtitle');
                const stateEl = document.getElementById('checkinState');
                const levelEl = document.getElementById('checkinLevel');
                const expEl = document.getElementById('checkinExp');
                const rewardEl = document.getElementById('checkinReward');
                const barEl = document.getElementById('checkinProgressBar');
                const btn = document.getElementById('checkinBtn');
                const tipEl = document.getElementById('checkinTip');

                if (subtitleEl) subtitleEl.textContent = adminExempt ? '管理员免签到' : `连续签到 ${streak} 天`;
                if (stateEl) {
                    stateEl.textContent = adminExempt ? '免签到' : (already ? '已签到' : '未签到');
                    stateEl.classList.toggle('is-done', already || adminExempt);
                }
                if (levelEl) levelEl.textContent = levelLabel;
                if (expEl) expEl.textContent = `${exp}`;
                if (rewardEl) rewardEl.textContent = `+${reward}`;
                if (barEl) barEl.style.width = `${pct}%`;
                if (btn) {
                    btn.disabled = already || adminExempt;
                    btn.textContent = adminExempt ? '管理员免签到' : (already ? '今日已签到' : '立即签到');
                    btn.classList.toggle('btn-primary', !(already || adminExempt));
                }
                if (tipEl) {
                    if (adminExempt) tipEl.textContent = '管理员拥有全部签到权益（免签到）';
                    else if (bonusReward > 0) tipEl.textContent = `当前等级进度 ${cur}/${next} · 下次连签奖励 +${bonusReward}`;
                    else tipEl.textContent = `当前等级进度 ${cur}/${next}`;
                }

                this.showCard();
            },
            async load() {
                if (!currentUser) {
                    this.hideCard();
                    return;
                }
                try {
                    const token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    const res = await fetch(`${API_BASE}/checkin/status`, {
                        headers: { 'Authorization': `Bearer ${token}` },
                        cache: 'no-store'
                    });
                    const data = await parseJsonSafe(res, {});
                    if (!res.ok) {
                        this.hideCard();
                        return;
                    }
                    this.render(data);
                } catch (_) {
                    this.hideCard();
                }
            },
            async sign() {
                if (!currentUser) {
                    Modal.open('loginModal');
                    return;
                }
                const btn = document.getElementById('checkinBtn');
                if (btn && btn.disabled) return;
                if (btn) {
                    btn.disabled = true;
                    btn.textContent = '签到中...';
                }
                try {
                    const res = await fetch(`${API_BASE}/checkin`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    if (!res.ok) {
                        if (btn) btn.disabled = false;
                        Toast.error(data.error || '签到失败');
                        return;
                    }
                    if (data.status) this.render(data.status);
                    if (data.already_checked) Toast.info(data.message || '今天已经签到过了');
                    else Toast.success(data.message || '签到成功');
                    Onboarding.load();
                } catch (_) {
                    Toast.error('签到失败，请稍后重试');
                    if (btn) {
                        btn.disabled = false;
                        btn.textContent = '立即签到';
                    }
                }
            }
        };
        window.Checkin = Checkin;

        const GroupLinks = {
            hideCard() {
                const card = document.getElementById('groupLinksCard');
                if (card) card.hidden = true;
            },
            showCard() {
                const card = document.getElementById('groupLinksCard');
                if (card) card.hidden = false;
            },
            render(payload) {
                const listEl = document.getElementById('groupLinksList');
                const hintEl = document.getElementById('groupLinksHint');
                if (!listEl || !payload || !Array.isArray(payload.groups)) {
                    this.hideCard();
                    return;
                }
                const level = Number(payload.level || 1);
                const levelLabel = payload.level_label || `Lv.${Math.max(1, level)}`;
                const adminExempt = !!payload.admin_infinite_level;
                if (hintEl) hintEl.textContent = adminExempt ? '管理员已解锁全部社群入口' : `当前等级 ${levelLabel}，达标后自动解锁`;
                listEl.innerHTML = payload.groups.map((g) => {
                    const required = Number(g.required_level || 1);
                    if (g.unlocked && g.url) {
                        const safeUrl = escapeAttr(g.url);
                        return `<div class="onboarding-task-item">
                            <span>✅</span>
                            <a href="${safeUrl}" target="_blank" rel="noopener" style="color:var(--accent-green); text-decoration:underline;">加入${escapeHtml(g.title || '')}</a>
                        </div>`;
                    }
                    if (g.unlocked && !g.configured) {
                        return `<div class="onboarding-task-item"><span>🛠️</span><span>${escapeHtml(g.title || '')} 链接待管理员配置</span></div>`;
                    }
                    return `<div class="onboarding-task-item"><span>🔒</span><span>Lv.${required} 解锁 ${escapeHtml(g.title || '')}</span></div>`;
                }).join('');
                this.showCard();
            },
            async load() {
                if (!currentUser) {
                    this.hideCard();
                    return;
                }
                try {
                    const token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    const res = await fetch(`${API_BASE}/group-links`, {
                        headers: { 'Authorization': `Bearer ${token}` },
                        cache: 'no-store'
                    });
                    const data = await parseJsonSafe(res, {});
                    if (!res.ok) {
                        this.hideCard();
                        return;
                    }
                    this.render(data);
                } catch (_) {
                    this.hideCard();
                }
            }
        };
        window.GroupLinks = GroupLinks;

        const Post = {
            currentPage: 1,
            totalPages: 1,
            currentSort: 'new',
            currentQuery: '',
            currentFilters: {
                from_date: '',
                to_date: '',
                permanent_only: false,
                tags: ''
            },
            isLoading: false,
            isFetching: false,
            pinnedPostId: null,
            autoLoadObserver: null,
            hasAdvancedFilters() {
                const f = this.currentFilters || {};
                return !!((f.from_date || '').trim() || (f.to_date || '').trim() || (f.tags || '').trim() || f.permanent_only);
            },

            async loadPinnedGuide() {
                try {
                    const res = await fetch(`${API_BASE}/posts/pinned`);
                    const data = await parseJsonSafe(res, {});
                    const banner = document.getElementById('pinnedGuideBanner');
                    const titleEl = document.getElementById('pinnedGuideTitle');
                    const previewEl = document.getElementById('pinnedGuidePreview');
                    const extraEl = document.getElementById('pinnedGuideExtra');
                    const btn = document.getElementById('pinnedGuideOpenBtn');
                    const toggleBtn = document.getElementById('pinnedGuideToggleBtn');
                    if (!banner || !titleEl || !btn || !previewEl || !extraEl || !toggleBtn) return;
                    const post = data && data.post;
                    if (!res.ok || !post || !post.id) {
                        banner.hidden = true;
                        this.pinnedPostId = null;
                        return;
                    }
                    const plainText = stripHtml(post.content || '');
                    const preview = plainText.length > 70 ? `${plainText.slice(0, 70)}...` : plainText;
                    this.pinnedPostId = post.id;
                    titleEl.textContent = post.title || '站点使用指南';
                    previewEl.textContent = preview || '点击查看站点功能与使用流程。';
                    extraEl.textContent = plainText || '该帖子用于向新访客解释站点功能与运作方式。';
                    extraEl.hidden = true;
                    toggleBtn.textContent = '展开简介';
                    toggleBtn.onclick = function () {
                        const isHidden = extraEl.hidden;
                        extraEl.hidden = !isHidden;
                        toggleBtn.textContent = isHidden ? '收起简介' : '展开简介';
                    };
                    btn.onclick = function(ev) { Modal.openDetail(ev, post.id); };
                    banner.hidden = false;
                } catch (_) {}
            },

            async load(params={}) {
                if(this.isLoading || this.isFetching) return;
                this.isLoading = true;
                this.isFetching = true;

                try {
                    if(params.sort || params.q !== undefined || params.filters) {
                        this.currentPage = 1;
                        document.getElementById('postGrid').innerHTML = '';
                        this.currentSort = params.sort || 'new';
                        if (params.q !== undefined) this.currentQuery = params.q || '';
                        if (params.filters) {
                            this.currentFilters = {
                                from_date: (params.filters.from_date || '').trim(),
                                to_date: (params.filters.to_date || '').trim(),
                                permanent_only: !!params.filters.permanent_only,
                                tags: (params.filters.tags || '').trim()
                            };
                        }
                    }

                    const qParams = new URLSearchParams();
                    qParams.append('page', this.currentPage);
                    qParams.append('sort', this.currentSort);
                    if(this.currentQuery) qParams.append('q', this.currentQuery);
                    if (this.currentFilters.from_date) qParams.append('from_date', this.currentFilters.from_date);
                    if (this.currentFilters.to_date) qParams.append('to_date', this.currentFilters.to_date);
                    if (this.currentFilters.permanent_only) qParams.append('permanent_only', '1');
                    if (this.currentFilters.tags) qParams.append('tags', this.currentFilters.tags);

                    const headers = {};
                    const token = localStorage.getItem('token');
                    if (token) headers['Authorization'] = `Bearer ${token}`;

                    let endpoint = `${API_BASE}/posts`;
                    if (this.currentQuery || this.hasAdvancedFilters()) endpoint = `${API_BASE}/search`;

                    const res = await fetch(`${endpoint}?${qParams.toString()}`, { headers });
                const data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    const msg = (data && data.error) || (res.status >= 500 ? '服务暂时不可用，请稍后重试' : `请求失败(${res.status})`);
                    throw new Error(msg);
                }

                if (data.posts) {
                    if(this.currentPage === 1) {
                        document.getElementById('postGrid').innerHTML = '';
                        if (data.posts.length === 0) {
                            let emptyMsg = '这里一片荒芜，什么也没有...';
                            let emptyBtn = this.currentQuery ? '<button class="btn btn-ghost" onclick="Post.load()" style="margin-top:1rem;">返回全部</button>' : '';
                            if (this.currentSort === 'bookmarks') {
                                if (!token) {
                                    emptyMsg = '请先登录后查看收藏';
                                    emptyBtn = '<button class="btn btn-primary" onclick="Modal.open(\'loginModal\')" style="margin-top:1rem;">去登录</button>';
                                } else {
                                    emptyMsg = '暂无收藏，去首页逛逛吧';
                                    emptyBtn = '<button class="btn btn-ghost" onclick="UI.handleNav(document.querySelector(\'[data-sort=new]\'), \'new\')" style="margin-top:1rem;">看最新</button>';
                                }
                            }
                            document.getElementById('postGrid').innerHTML = `
                                <div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-muted);">
                                    <div style="font-size: 3rem; margin-bottom: 1rem;">${this.currentSort === 'bookmarks' ? '⭐' : '👻'}</div>
                                    <p>${emptyMsg}</p>
                                    ${emptyBtn}
                                </div>
                            `;
                        }
                    }
                    UI.renderPosts(data.posts, this.currentPage > 1);
                    if (data.pages) {
                        this.totalPages = data.pages;
                        const loadMore = document.getElementById('loadMoreArea');
                        if (loadMore) {
                            loadMore.style.display = this.currentPage < this.totalPages ? 'block' : 'none';
                        }
                    }
                }
                } catch (e) {
                    if (this.currentPage === 1) {
                        const loadingEl = document.getElementById('loadingArea');
                        const msg = (e && e.message) || '网络异常或服务暂时不可用';
                        loadingEl.innerHTML = `<div style="color:var(--text-muted); padding:1.5rem;">${msg}</div><button class="btn btn-ghost" onclick="Post.load()" style="margin-top:0.5rem;">重试</button>`;
                    }
                } finally {
                    this.isLoading = false;
                    this.isFetching = false;
                    document.getElementById('loadingArea').style.display = 'none';
                }
            },

            loadMore() {
                if(this.currentPage < this.totalPages) {
                    this.currentPage++;
                    this.load();
                }
            },
            initAutoLoad() {
                const sentinel = document.getElementById('loadMoreArea');
                if (!sentinel || this.autoLoadObserver) return;
                this.autoLoadObserver = new IntersectionObserver((entries) => {
                    const entry = entries && entries[0];
                    if (!entry || !entry.isIntersecting) return;
                    if (this.isLoading || this.isFetching) return;
                    if (this.currentPage >= this.totalPages) return;
                    this.loadMore();
                }, {
                    root: null,
                    rootMargin: '200px 0px 260px 0px',
                    threshold: 0.01
                });
                this.autoLoadObserver.observe(sentinel);
            },

            async repost(id) {
                if (!currentUser) return Modal.open('loginModal');
                const content = prompt("转发附言:");
                if (content === null) return;

                const res = await fetch(`${API_BASE}/posts/${id}/repost`, {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': `Bearer ${localStorage.getItem('token')}`
                    },
                    body: JSON.stringify({ content })
                });
                if(res.ok) { Toast.success('转发成功'); this.load(); }
                else {
                    const data = await parseJsonSafe(res, {});
                    Toast.error(data.error || '转发失败');
                }
            }
        };

        const UI = {
            updateAuth() {
                const authBtns = document.getElementById('authButtons');
                const userMenu = document.getElementById('userMenu');

                if (currentUser) {
                    authBtns.style.display = 'none';
                    userMenu.style.display = 'flex';
                    document.getElementById('userDisplayName').textContent = currentUser.nickname;

                    let notifBtn = document.getElementById('notifBtn');
                    if(!notifBtn) {
                        notifBtn = document.createElement('div');
                        notifBtn.id = 'notifBtn';
                        notifBtn.style.position = 'relative';
                        notifBtn.style.cursor = 'pointer';
                        notifBtn.style.marginRight = '0.5rem';
                        notifBtn.innerHTML = '<span style="font-size:1.2rem;">🔔</span><div id="notifBadge" style="position:absolute; top:-2px; right:-2px; width:8px; height:8px; background:var(--accent-red); border-radius:50%; display:none;"></div>';
                        notifBtn.onclick = () => { Modal.open('notificationModal'); Notification.load(); };
                        const avatarBtn = document.getElementById('userAvatarEmoji');
                        avatarBtn.parentNode.insertBefore(notifBtn, avatarBtn);
                    }
                    Notification.load();

                    let profileLink = document.getElementById('profileLink');
                    if(!profileLink) {
                        profileLink = document.createElement('a');
                        profileLink.id = 'profileLink';
                        profileLink.className = 'btn btn-ghost';
                        profileLink.style.padding = '0.3rem 0.6rem';
                        profileLink.style.fontSize = '0.8rem';
                        profileLink.textContent = '👤 我的主页';
                        profileLink.href = `/profile?user=${currentUser.username || currentUser.address}`;
                        const logoutBtn = document.getElementById('logoutBtn');
                        logoutBtn.parentNode.insertBefore(profileLink, logoutBtn);
                    }

                    let bindBtn = document.getElementById('bindWalletBtn');
                    if(!bindBtn) {
                        bindBtn = document.createElement('button');
                        bindBtn.id = 'bindWalletBtn';
                        bindBtn.className = 'btn btn-ghost';
                        bindBtn.style.padding = '0.3rem 0.6rem';
                        bindBtn.style.fontSize = '0.8rem';
                        bindBtn.style.color = 'var(--accent-orange)';
                        bindBtn.style.borderColor = 'var(--accent-orange)';
                        bindBtn.textContent = '🔗 绑定钱包';
                        bindBtn.onclick = Auth.bindWallet;
                        const logoutBtn = document.getElementById('logoutBtn');
                        logoutBtn.parentNode.insertBefore(bindBtn, logoutBtn);
                    }

                    if(currentUser.address) {
                        bindBtn.style.display = 'none';
                    } else {
                        bindBtn.style.display = 'inline-flex';
                    }

                    if(currentUser.is_admin) {
                        let statsBtn = document.getElementById('adminStatsBtn');
                        if(!statsBtn) {
                            statsBtn = document.createElement('button');
                            statsBtn.id = 'adminStatsBtn';
                            statsBtn.className = 'btn btn-ghost';
                            statsBtn.style.color = 'var(--accent-gold)';
                            statsBtn.style.borderColor = 'var(--accent-gold)';
                            statsBtn.textContent = '📊 看板';
                            statsBtn.onclick = Admin.openStats;
                            const reportsBtn = document.createElement('button');
                            reportsBtn.id = 'adminReportsBtn';
                            reportsBtn.className = 'btn btn-ghost';
                            reportsBtn.style.color = 'var(--accent-red)';
                            reportsBtn.style.borderColor = 'var(--accent-red)';
                            reportsBtn.textContent = '🚩 举报';
                            reportsBtn.onclick = Admin.openReports;
                            const usersBtn = document.createElement('button');
                            usersBtn.id = 'adminUsersBtn';
                            usersBtn.className = 'btn btn-ghost';
                            usersBtn.style.color = 'var(--accent-purple)';
                            usersBtn.style.borderColor = 'var(--accent-purple)';
                            usersBtn.textContent = '👥 用户';
                            usersBtn.onclick = Admin.openUsers;
                            const annBtn = document.createElement('button');
                            annBtn.id = 'adminAnnBtn';
                            annBtn.className = 'btn btn-ghost';
                            annBtn.style.color = 'var(--accent-orange)';
                            annBtn.style.borderColor = 'var(--accent-orange)';
                            annBtn.textContent = '📣 公告';
                            annBtn.onclick = Admin.openAnnouncements;
                            const groupBtn = document.createElement('button');
                            groupBtn.id = 'adminGroupLinksBtn';
                            groupBtn.className = 'btn btn-ghost';
                            groupBtn.style.color = 'var(--accent-green)';
                            groupBtn.style.borderColor = 'var(--accent-green)';
                            groupBtn.textContent = '🛰️ 群链接';
                            groupBtn.onclick = Admin.editGroupLinks;
                            const auditBtn = document.createElement('button');
                            auditBtn.id = 'adminAuditBtn';
                            auditBtn.className = 'btn btn-ghost';
                            auditBtn.style.color = 'var(--text-secondary)';
                            auditBtn.textContent = '🧾 日志';
                            auditBtn.onclick = Admin.openAuditLogs;
                            const logoutBtn = document.getElementById('logoutBtn');
                            logoutBtn.parentNode.insertBefore(usersBtn, logoutBtn);
                            logoutBtn.parentNode.insertBefore(reportsBtn, logoutBtn);
                            logoutBtn.parentNode.insertBefore(annBtn, logoutBtn);
                            logoutBtn.parentNode.insertBefore(groupBtn, logoutBtn);
                            logoutBtn.parentNode.insertBefore(auditBtn, logoutBtn);
                            logoutBtn.parentNode.insertBefore(statsBtn, logoutBtn);
                        }
                    }

                    if(currentUser.avatar) {
                        const avatarEl = document.getElementById('userAvatarEmoji');
                        avatarEl.textContent = currentUser.avatar;
                    }
                } else {
                    authBtns.style.display = 'flex';
                    userMenu.style.display = 'none';
                }
                Onboarding.load();
                Checkin.load();
                GroupLinks.load();
            },

            resolveCoverUrl(post) {
                const removedLegacyCover = '/static/images/hua_cover.jpg';
                const normalize = (val) => {
                    if (typeof val !== 'string') return null;
                    const trimmed = val.trim();
                    if (!trimmed || trimmed === removedLegacyCover) return null;
                    return trimmed;
                };
                const direct = normalize(post && post.cover_image);
                if (direct) return direct;

                const images = post && post.images;
                if (Array.isArray(images)) {
                    for (const it of images) {
                        const found = normalize(it);
                        if (found) return found;
                    }
                    return null;
                }
                if (typeof images === 'string') {
                    const raw = images.trim();
                    if (!raw) return null;
                    if (raw.startsWith('[')) {
                        try {
                            const parsed = JSON.parse(raw);
                            if (Array.isArray(parsed)) {
                                for (const it of parsed) {
                                    const found = normalize(it);
                                    if (found) return found;
                                }
                                return null;
                            }
                        } catch (_) {}
                    }
                    return normalize(raw);
                }
                return null;
            },

            renderCover(imageUrl) {
                if (!imageUrl) {
                    return '<div class="post-image-wrap is-fallback"><div class="post-image-placeholder">📝</div></div>';
                }
                const imgSrc = escapeAttr(imageUrl);
                return `<div class="post-image-wrap">
                    <div class="post-image-placeholder">📝</div>
                    <img src="${imgSrc}" class="post-image" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement.classList.add('has-image');this.parentElement.classList.remove('is-fallback')" onerror="this.remove();this.parentElement.classList.add('is-fallback')">
                </div>`;
            },

            renderPosts(posts, append=false) {
                const grid = document.getElementById('postGrid');
                const html = posts.map((p, idx) => {
                    const imgUrl = this.resolveCoverUrl(p);
                    const coverHtml = this.renderCover(imgUrl);
                    const author = p.author || { nickname: '用户', avatar: '👻' };

                    const isWeb3 = p.post_type === 1 || p.tx_hash;
                    const isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
                    const isSpecial = !!p.is_special_announcement;
                    const cardClasses = ['post-card', 'glass'];
                    if (isWeb3) cardClasses.push('post-card--web3');
                    const badge = isWeb3 ? '<div class="post-badge post-badge-web3">Web3</div>' : '';
                    const permanentBadge = isPermanent ? '<div class="post-badge post-badge-permanent">已永存</div>' : '';
                    const specialBadge = isSpecial ? '<div class="post-badge post-badge-special">📜 长公告</div>' : '';
                    const pinBadge = p.is_pinned ? '<div class="post-badge post-badge-pinned">📌 置顶</div>' : '';

                    return `
                    <div class="masonry-item" style="--stagger:${Math.min((idx % 12) * 28, 280)}ms;">
                        <div class="${cardClasses.join(' ')}" onclick="Modal.openDetail(event, ${p.id})">
                            ${pinBadge}
                            ${badge}
                            ${permanentBadge}
                            ${specialBadge}
                            ${coverHtml}
                            <div class="post-content">
                                <div class="post-title">${escapeHtml(p.title)}</div>
                                <div class="post-meta">
                                    <div class="author-info">
                                        ${UI.renderAvatar(author)}
                                        <span>${escapeHtml(author.nickname || '用户')}</span>
                                        ${UI.renderAuthorBadge(author)}
                                        ${author.id != null ? formatUserId(author.id) : ''}
                                    </div>
                                    <div class="post-like">
                                        <span><i class="fas fa-heart" style="${p.is_liked ? 'color:var(--accent-red)' : ''}"></i> ${p.likes_count}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>`;
                }).join('');

                if(append) grid.insertAdjacentHTML('beforeend', html);
                else grid.innerHTML = html;

                document.getElementById('loadingArea').style.display = 'none';
            },

            renderAvatar(user) {
                return `<div class="user-avatar-emoji post-avatar">${user.avatar || '👻'}</div>`;
            },
            equippedTitleByKey(key) {
                const map = {
                    report_privilege: '举报权限',
                    wearable_unlock: '成就佩戴权限',
                    co_create_group: '共创群资格',
                    core_group: '核心群资格',
                    legacy_new_soul: '新魂',
                    legacy_chain_traveler: '链上旅人',
                    legacy_wallet_bound: '钱包绑定',
                    legacy_dual_identity: '双界行者',
                    legacy_contract_psychic: '结契通灵者',
                    legacy_first_post: '首帖达成',
                    legacy_post_10: '十帖异闻录',
                    legacy_post_100: '百帖引魂者',
                    legacy_post_1000: '千帖通灵者',
                    legacy_year_1: '一年见习者',
                    legacy_year_5: '五年夜巡者',
                    legacy_year_10: '十年守秘人',
                    legacy_admin_guardian: '守夜人'
                };
                return map[key] || key;
            },
            renderAuthorBadge(user) {
                if (!user) return '';
                const equippedKey = (user.equipped_achievement_key || '').trim();
                if (equippedKey) {
                    return `<span class="honor-badge" style="border-color:rgba(16,185,129,0.5); color:var(--accent-green);">🏆 ${escapeHtml(this.equippedTitleByKey(equippedKey))}</span>`;
                }
                if (!user.honor_title) return '';
                return `<span class="honor-badge">🏷 ${escapeHtml(user.honor_title)}</span>`;
            },

            handleNav(el, sort) {
                document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
                el.classList.add('active');
                Post.load({sort});
            }
        };

        const Admin = {
            async openStats() {
                Modal.open('adminStatsModal');
                const body = document.getElementById('adminStatsBody');
                body.innerHTML = '加载中...';

                try {
                    const { res, data } = await fetchJsonSafe(`${API_BASE}/admin/stats`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    }, { fallback: {}, errorMessage: '加载统计失败' });

                    if(!res.ok || data.error) throw new Error(data.error || '加载失败');

                    body.innerHTML = `
                        <div class="sidebar-card glass" style="grid-column: span 2; text-align: center;">
                            <div style="font-size: 0.9rem; color: var(--text-secondary);">总营收 (估算)</div>
                            <div style="font-size: 2rem; font-weight: bold; color: var(--accent-gold);">${(data.revenue.total_usdt != null ? data.revenue.total_usdt : 0).toFixed(2)} USDT</div>
                            <div style="font-size: 0.8rem; color: var(--text-muted);">单篇费用: ${(data.revenue.fee_per_post_usdt != null ? data.revenue.fee_per_post_usdt : 0)} USDT</div>
                        </div>

                        <div class="sidebar-card glass">
                            <div style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 0.5rem;">用户统计</div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                                <span>总用户:</span> <b>${data.users.total}</b>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                                <span>Web3 (钱包):</span> <span style="color: var(--accent-purple);">${data.users.web3}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span>Web2 (仅注册):</span> <span>${data.users.web2}</span>
                            </div>
                        </div>

                        <div class="sidebar-card glass">
                            <div style="font-size: 0.9rem; color: var(--text-secondary); margin-bottom: 0.5rem;">帖子统计</div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                                <span>总帖子:</span> <b>${data.posts.total}</b>
                            </div>
                            <div style="display: flex; justify-content: space-between; margin-bottom: 0.3rem;">
                                <span>Web3 (永存):</span> <span style="color: var(--accent-gold);">${data.posts.web3}</span>
                            </div>
                            <div style="display: flex; justify-content: space-between;">
                                <span>Web2 (普通):</span> <span>${data.posts.web2}</span>
                            </div>
                        </div>
                    `;
                } catch(e) {
                    body.innerHTML = `<div style="color: var(--accent-red);">加载失败: ${e.message}</div>`;
                }
            },
            async openReports() {
                Modal.open('adminReportsModal');
                const body = document.getElementById('adminReportsBody');
                body.innerHTML = '加载中...';
                try {
                    const res = await fetch(`${API_BASE}/admin/reports`, { headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` } });
                    const list = await parseJsonSafe(res, []);
                    if (res.status !== 200 || !Array.isArray(list)) {
                        body.innerHTML = `<div style="color: var(--accent-red);">${list.error || '加载失败'}</div>`;
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">暂无举报</div>';
                        return;
                    }
                    body.innerHTML = list.map(r => `
                        <div class="glass" style="padding: 0.75rem; margin-bottom: 0.75rem; border-radius: 8px;">
                            <div style="font-size: 0.85rem; margin-bottom: 0.4rem;">
                                <span style="color: var(--text-muted);">#${r.id}</span> ${r.status === 'pending' ? '<span style="color: var(--accent-red);">待处理</span>' : r.status === 'resolved' ? '<span style="color: var(--accent-green);">已处理</span>' : '<span style="color: var(--text-muted);">已忽略</span>'}
                            </div>
                            <div style="margin-bottom: 0.4rem;">举报人: ${escapeHtml(r.reporter_nickname || '')} · 被举报: ${escapeHtml(r.reported_nickname || '')} ${r.post_title ? '· 帖子: ' + escapeHtml(r.post_title) : ''}</div>
                            <div style="font-size: 0.9rem; color: var(--text-primary); margin-bottom: 0.5rem;">${escapeHtml(r.reason || '')}</div>
                            ${r.admin_notes ? `<div style="font-size: 0.8rem; color: var(--text-muted); margin-bottom: 0.5rem;">备注: ${escapeHtml(r.admin_notes)}</div>` : ''}
                            ${r.status === 'pending' ? `
                                <div style="display: flex; gap: 0.5rem; margin-top: 0.5rem;">
                                    <button class="btn btn-primary btn-sm" onclick="Admin.resolveReport(${r.id}, 'resolved')">已处理</button>
                                    <button class="btn btn-ghost btn-sm" onclick="Admin.resolveReport(${r.id}, 'dismissed')">忽略</button>
                                </div>
                            ` : ''}
                        </div>
                    `).join('');
                } catch (e) {
                    body.innerHTML = `<div style="color: var(--accent-red);">${e.message || '加载失败'}</div>`;
                }
            },
            async resolveReport(reportId, status) {
                try {
                    const res = await fetch(`${API_BASE}/admin/reports/${reportId}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                        body: JSON.stringify({ status })
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) { Toast.success(data.message || '已更新'); Admin.openReports(); }
                    else Toast.error(data.error || '操作失败');
                } catch (e) { Toast.error('网络错误'); }
            },
            async openUsers() {
                Modal.open('adminUsersModal');
                const body = document.getElementById('adminUsersBody');
                body.innerHTML = '加载中...';
                try {
                    const res = await fetch(`${API_BASE}/admin/users`, { headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` } });
                    const list = await parseJsonSafe(res, []);
                    if (res.status !== 200 || !Array.isArray(list)) {
                        body.innerHTML = `<div style="color: var(--accent-red);">${list.error || '加载失败'}</div>`;
                        return;
                    }
                    if (list.length === 0) {
                        body.innerHTML = '<div style="text-align:center; color: var(--text-muted); padding: 2rem;">暂无用户</div>';
                        return;
                    }
                    body.innerHTML = list.map(u => `
                        <div class="glass" style="padding: 0.75rem; margin-bottom: 0.75rem; border-radius: 8px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 0.5rem;">
                            <div>
                                <div style="font-weight: 600;">${escapeHtml(u.nickname || u.username || '')}</div>
                                <div style="font-size: 0.8rem; color: var(--text-muted);">ID: ${u.id} · ${u.type === 'web3' ? '钱包' : 'Web2'}</div>
                            </div>
                            ${!u.is_admin ? `<button class="btn btn-ghost btn-sm" style="color: var(--accent-red);" onclick="Admin.toggleBan(${u.id}, ${u.is_banned})">${u.is_banned ? '解除封禁' : '封禁'}</button>` : '<span style="font-size: 0.8rem; color: var(--accent-gold);">管理员</span>'}
                        </div>
                    `).join('');
                } catch (e) {
                    body.innerHTML = `<div style="color: var(--accent-red);">${e.message || '加载失败'}</div>`;
                }
            },
            async toggleBan(userId, currentlyBanned) {
                try {
                    const res = await fetch(`${API_BASE}/admin/users/${userId}/ban`, {
                        method: 'POST',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) { Toast.success(data.message || (currentlyBanned ? '已解除封禁' : '已封禁')); Admin.openUsers(); }
                    else Toast.error(data.error || '操作失败');
                } catch (e) { Toast.error('网络错误'); }
            },
            async openAnnouncements() {
                Modal.open('adminAnnouncementsModal');
                const body = document.getElementById('adminAnnouncementsBody');
                body.innerHTML = '加载中...';
                try {
                    const res = await fetch(`${API_BASE}/admin/announcements`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    const list = data.announcements || [];
                    if (!res.ok) throw new Error(data.error || '加载失败');
                    if (!list.length) {
                        body.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem;">暂无公告</div>';
                        return;
                    }
                    body.innerHTML = list.map(a => `
                        <div class="glass" style="padding:0.7rem; margin-bottom:0.7rem; border-radius:8px;">
                            <div style="display:flex; justify-content:space-between; gap:0.5rem; align-items:center;">
                                <b>${a.entry_type === 'activity' ? '🎉 ' : '📣 '}${escapeHtml(a.title || '')}</b>
                                <span style="font-size:0.78rem; color:${a.is_active ? 'var(--accent-green)' : 'var(--text-muted)'};">${a.is_active ? '生效中' : '未生效'}</span>
                            </div>
                            <div style="font-size:0.86rem; margin:0.45rem 0;">${escapeHtml(a.content || '')}</div>
                            <div style="font-size:0.74rem; color:var(--text-muted); margin-bottom:0.45rem;">类型: ${escapeHtml(a.entry_type || 'announcement')} ${a.starts_at ? (' · 开始: ' + new Date(a.starts_at).toLocaleString()) : ''} ${a.expires_at ? (' · 结束: ' + new Date(a.expires_at).toLocaleString()) : ''}</div>
                            <div style="display:flex; gap:0.45rem; flex-wrap:wrap;">
                                <button class="btn btn-ghost btn-sm" onclick="Admin.toggleAnnouncementActive(${a.id}, ${a.is_active ? 'false' : 'true'})">${a.is_active ? '停用' : '启用'}</button>
                                <button class="btn btn-ghost btn-sm" style="color:var(--accent-red);" onclick="Admin.deleteAnnouncement(${a.id})">删除</button>
                            </div>
                        </div>
                    `).join('');
                } catch (e) {
                    body.innerHTML = `<div style="color:var(--accent-red);">${e.message || '加载失败'}</div>`;
                }
            },
            async createAnnouncement() {
                const title = prompt('公告标题（120字内）');
                if (!title || !title.trim()) return;
                const content = prompt('公告内容（1000字内）');
                if (!content || !content.trim()) return;
                const entryType = ((prompt('类型：announcement(公告) / activity(活动)', 'announcement') || 'announcement').trim().toLowerCase() === 'activity') ? 'activity' : 'announcement';
                const level = (prompt('级别：info / warning / critical', 'info') || 'info').trim().toLowerCase();
                const startsAt = (prompt('开始时间（可空，格式 YYYY-MM-DDTHH:mm:ss）', '') || '').trim();
                const expiresAt = (prompt('结束时间（可空，格式 YYYY-MM-DDTHH:mm:ss）', '') || '').trim();
                try {
                    const res = await fetch(`${API_BASE}/admin/announcements`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                        body: JSON.stringify({ title: title.trim(), content: content.trim(), entry_type: entryType, level, starts_at: startsAt || null, expires_at: expiresAt || null, activate: true })
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) {
                        Toast.success(data.message || '已创建');
                        SiteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(data.error || '创建失败');
                } catch (_) { Toast.error('网络错误'); }
            },
            async toggleAnnouncementActive(id, isActive) {
                try {
                    const res = await fetch(`${API_BASE}/admin/announcements/${id}`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                        body: JSON.stringify({ is_active: isActive })
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) {
                        Toast.success('状态已更新');
                        SiteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(data.error || '操作失败');
                } catch (_) { Toast.error('网络错误'); }
            },
            async deleteAnnouncement(id) {
                if (!confirm('确定删除此公告？')) return;
                try {
                    const res = await fetch(`${API_BASE}/admin/announcements/${id}`, {
                        method: 'DELETE',
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) {
                        Toast.success('已删除');
                        SiteNotice.load();
                        this.openAnnouncements();
                    } else Toast.error(data.error || '删除失败');
                } catch (_) { Toast.error('网络错误'); }
            },
            async openAuditLogs() {
                Modal.open('adminAuditModal');
                const body = document.getElementById('adminAuditBody');
                body.innerHTML = '加载中...';
                try {
                    const res = await fetch(`${API_BASE}/admin/audit-logs?limit=200`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    const logs = data.logs || [];
                    if (!res.ok) throw new Error(data.error || '加载失败');
                    if (!logs.length) {
                        body.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:1rem;">暂无日志</div>';
                        return;
                    }
                    body.innerHTML = logs.map(l => `
                        <div style="padding:0.45rem 0; border-bottom:1px dashed var(--border-color);">
                            <div style="font-size:0.82rem; color:var(--text-muted);">${new Date(l.created_at).toLocaleString()} · Admin#${l.admin_id}</div>
                            <div style="font-size:0.9rem;"><b>${escapeHtml(l.action || '')}</b> ${escapeHtml(l.target_type || '')}#${escapeHtml(String(l.target_id || ''))}</div>
                            ${l.details ? `<div style="font-size:0.8rem; color:var(--text-secondary);">${escapeHtml(l.details)}</div>` : ''}
                        </div>
                    `).join('');
                } catch (e) {
                    body.innerHTML = `<div style="color:var(--accent-red);">${e.message || '加载失败'}</div>`;
                }
            },
            async editGroupLinks() {
                try {
                    const res = await fetch(`${API_BASE}/admin/group-links`, {
                        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                    });
                    const data = await parseJsonSafe(res, {});
                    if (!res.ok) {
                        Toast.error(data.error || '读取群链接失败');
                        return;
                    }
                    const currentCo = data.co_create_url || '';
                    const currentCore = data.core_url || '';
                    const co = prompt('设置「共创群」Telegram 链接（留空=清空）', currentCo);
                    if (co === null) return;
                    const core = prompt('设置「核心群」Telegram 链接（留空=清空）', currentCore);
                    if (core === null) return;
                    const saveRes = await fetch(`${API_BASE}/admin/group-links`, {
                        method: 'PUT',
                        headers: {
                            'Content-Type': 'application/json',
                            'Authorization': `Bearer ${localStorage.getItem('token')}`
                        },
                        body: JSON.stringify({
                            co_create_url: (co || '').trim(),
                            core_url: (core || '').trim()
                        })
                    });
                    const saveData = await parseJsonSafe(saveRes, {});
                    if (!saveRes.ok) {
                        Toast.error(saveData.error || '保存失败');
                        return;
                    }
                    Toast.success(saveData.message || '群链接已更新');
                    GroupLinks.load();
                } catch (_) {
                    Toast.error('网络错误');
                }
            }
        };

        let tipAuthorPostId = null;
        let tipAuthorWallet = '';
        async function copyTextWithFallback(text, successMsg) {
            const safeText = (text || '').trim();
            if (!safeText) return false;
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    await navigator.clipboard.writeText(safeText);
                } else {
                    const ta = document.createElement('textarea');
                    ta.value = safeText;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                }
                if (successMsg && typeof Toast !== 'undefined') Toast.success(successMsg);
                return true;
            } catch (_) {
                return false;
            }
        }

        async function ensureWalletProvider(fallbackAddress) {
            const provider = window.BinanceChain || window.ethereum;
            if (provider) return provider;
            if (fallbackAddress) {
                await copyTextWithFallback(fallbackAddress, '已复制收款地址，可手动转账');
            }
            Toast.info('未检测到钱包，请用钱包 App 内置浏览器打开本站后再支付');
            return null;
        }

        const TipAuthor = {
            open(postId, authorWallet) {
                tipAuthorPostId = postId;
                tipAuthorWallet = (authorWallet || '').trim();
                const displayEl = document.getElementById('tipAuthorAddressDisplay');
                const copyBtn = document.getElementById('tipAuthorCopyBtn');
                const sendBtn = document.querySelector('#tipAuthorModal .btn-primary');
                if (displayEl) {
                    displayEl.textContent = tipAuthorWallet ? tipAuthorWallet : '作者未绑定钱包，暂无法打赏';
                    displayEl.style.color = tipAuthorWallet ? 'var(--accent-green)' : 'var(--text-muted)';
                }
                if (copyBtn) {
                    copyBtn.style.display = tipAuthorWallet ? 'inline-block' : 'none';
                }
                if (sendBtn) {
                    sendBtn.disabled = !tipAuthorWallet;
                    sendBtn.style.opacity = tipAuthorWallet ? '1' : '0.5';
                }
                const input = document.getElementById('tipAmountInput');
                if (input) input.value = '1';
                Modal.open('tipAuthorModal');
            },
            copyAddress() {
                if (!tipAuthorWallet) return;
                copyTextWithFallback(tipAuthorWallet, '已复制收款地址');
            },
            async send() {
                if (!tipAuthorPostId || !currentUser || !currentUser.address) {
                    Toast.error('请先登录（钱包）');
                    return;
                }
                if (!tipAuthorWallet) {
                    Toast.error('作者未绑定钱包，暂无法打赏');
                    return;
                }
                const amountStr = (document.getElementById('tipAmountInput').value || '1').trim();
                const amountUsdt = parseFloat(amountStr);
                if (isNaN(amountUsdt) || amountUsdt < 1) {
                    Toast.error('打赏金额至少 1 USDT');
                    return;
                }
                try {
                    const provider = await ensureWalletProvider(tipAuthorWallet);
                    if (!provider) return;
                    const web3 = new Web3(provider);
                    const cRes = await fetch(`${API_BASE}/config/fees`);
                    const config = await parseJsonSafe(cRes, {});
                    if (!cRes.ok || !config.usdt_contract) {
                        Toast.error('无法获取 USDT 合约配置');
                        return;
                    }
                    const amountRaw = web3.utils.toBN(web3.utils.toWei(amountUsdt.toString(), 'ether'));
                    const sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
                    const paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [tipAuthorWallet, amountRaw]);
                    const txData = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
                    const txHash = await provider.request({
                        method: 'eth_sendTransaction',
                        params: [{
                            to: config.usdt_contract,
                            from: currentUser.address,
                            value: '0x0',
                            data: txData,
                            gas: web3.utils.toHex(100000)
                        }]
                    });
                    if (!txHash) { Toast.error('打赏取消'); return; }
                    Toast.info('交易已发送，正在确认...');
                    const verifyRes = await fetch(`${API_BASE}/tips/verify`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                        body: JSON.stringify({ tx_hash: txHash, post_id: tipAuthorPostId })
                    });
                    const resp = await parseJsonSafe(verifyRes, {});
                    if (verifyRes.ok) {
                        Toast.success(`打赏成功！${resp.tip.author_receives_usdt} USDT 已直接转入作者钱包`);
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

        const Donate = {
            cachedConfig: null,
            async getConfig(forceRefresh=false) {
                if (!forceRefresh && this.cachedConfig) return this.cachedConfig;
                try {
                    const r = await fetch(`${API_BASE}/config/fees`, { cache: 'no-store' });
                    const c = await parseJsonSafe(r, {});
                    if (!r.ok) return null;
                    this.cachedConfig = c;
                    return c;
                } catch (_) {
                    return null;
                }
            },
            async openModal() {
                const c = await this.getConfig(true);
                const el = document.getElementById('donateAddress');
                if (el) el.textContent = (c && c.receive_address) ? c.receive_address : '暂不可用';
                if (!c || !c.receive_address || !c.usdt_contract) {
                    Toast.error('暂时无法获取收款配置，请稍后再试');
                }
                Modal.open('donateModal');
            },
            async send(amount) {
                const amountUsdt = typeof amount === 'number' ? amount : parseFloat(amount);
                if (isNaN(amountUsdt) || amountUsdt < 0.1) {
                    Toast.error('请输入有效金额（至少 0.1 USDT）');
                    return;
                }
                try {
                    const config = await this.getConfig();
                    if (!config || !config.receive_address || !config.usdt_contract) {
                        Toast.error('无法获取收款配置');
                        return;
                    }
                    if (document.getElementById('donateAddress')) {
                        document.getElementById('donateAddress').textContent = config.receive_address;
                    }
                    const provider = await ensureWalletProvider(config.receive_address);
                    if (!provider) return;
                    const web3 = new Web3(provider);
                    const accounts = await provider.request({ method: 'eth_requestAccounts' });
                    const from = accounts[0];
                    const amountRaw = web3.utils.toBN(web3.utils.toWei(amountUsdt.toString(), 'ether'));
                    const sig = web3.eth.abi.encodeFunctionSignature('transfer(address,uint256)');
                    const paramsEnc = web3.eth.abi.encodeParameters(['address', 'uint256'], [config.receive_address, amountRaw]);
                    const data = sig + (paramsEnc.startsWith('0x') ? paramsEnc.slice(2) : paramsEnc);
                    const txReq = {
                        to: config.usdt_contract,
                        from: from,
                        value: '0x0',
                        data: data,
                        gas: web3.utils.toHex(100000)
                    };
                    const chainIdNum = Number(config.chain_id || 56);
                    if (Number.isFinite(chainIdNum) && chainIdNum > 0) {
                        txReq.chainId = web3.utils.toHex(chainIdNum);
                    }
                    await provider.request({
                        method: 'eth_sendTransaction',
                        params: [txReq]
                    });
                    Toast.success(`感谢您的 ${amountUsdt} USDT 打赏！🙏`);
                    Modal.close('donateModal');
                } catch(e) {
                    if (e && e.code === 4001) Toast.error('已取消打赏');
                    else Toast.error(e.message || '打赏取消或失败');
                }
            }
        };

        let currentDetailPostId = null;
        let currentDetailRequestSeq = 0;
        const Modal = {
            open(id, opts = {}) {
                const overlay = document.getElementById(id);
                if (!overlay) return;
                if (id === 'postDetailModal') {
                    const anchorY = (opts && Number.isFinite(opts.anchorY)) ? Number(opts.anchorY) : null;
                    let offset = 0;
                    if (anchorY !== null) {
                        const overlayStyle = window.getComputedStyle(overlay);
                        const padTop = parseFloat(overlayStyle.paddingTop || '0') || 0;
                        const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
                        const desired = anchorY - padTop - 72;
                        const maxOffset = Math.max(0, viewportH - padTop - 220);
                        offset = Math.max(0, Math.min(desired, maxOffset));
                    }
                    overlay.style.setProperty('--detail-open-offset', `${Math.round(offset)}px`);
                }
                overlay.classList.add('active');
                overlay.scrollTop = 0;
                const modalEl = overlay.querySelector('.modal');
                if (modalEl) modalEl.scrollTop = 0;
            },
            close(id) {
                const overlay = document.getElementById(id);
                if (!overlay) return;
                if (id === 'postDetailModal') {
                    const modalScrollEl = document.querySelector('#postDetailModal .modal');
                    if (modalScrollEl && currentDetailPostId) {
                        const maxScroll = Math.max(0, modalScrollEl.scrollHeight - modalScrollEl.clientHeight);
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
                }
            },

            async openDetail(evtOrId, idMaybe) {
                let anchorY = null;
                if (evtOrId && typeof evtOrId === 'object' && typeof evtOrId.preventDefault === 'function') {
                    if (Number.isFinite(evtOrId.clientY) && Number(evtOrId.clientY) > 0) {
                        anchorY = Number(evtOrId.clientY);
                    } else {
                        const targetEl = evtOrId.currentTarget || evtOrId.target;
                        if (targetEl && typeof targetEl.getBoundingClientRect === 'function') {
                            const rect = targetEl.getBoundingClientRect();
                            const approx = rect.top + Math.min(rect.height * 0.42, 140);
                            if (Number.isFinite(approx)) anchorY = approx;
                        }
                    }
                    evtOrId.preventDefault();
                    evtOrId.stopPropagation();
                }
                if (!Number.isFinite(anchorY) || anchorY <= 0) {
                    if (Number.isFinite(lastPointerClientY) && lastPointerClientY > 0) {
                        anchorY = Number(lastPointerClientY);
                    } else if (document.activeElement && typeof document.activeElement.getBoundingClientRect === 'function') {
                        const activeRect = document.activeElement.getBoundingClientRect();
                        const activeApprox = activeRect.top + Math.min(activeRect.height * 0.5, 120);
                        if (Number.isFinite(activeApprox) && activeApprox > 0) anchorY = activeApprox;
                    }
                }
                const id = (evtOrId && typeof evtOrId === 'object') ? idMaybe : evtOrId;
                if (id == null || id === undefined) return;
                currentDetailPostId = id;
                const reqSeq = ++currentDetailRequestSeq;
                this.open('postDetailModal', { anchorY });
                const body = document.getElementById('postDetailBody');
                body.innerHTML = '加载中...';
                const modalScrollEl = document.querySelector('#postDetailModal .modal');
                if (modalScrollEl) modalScrollEl.scrollTop = 0;
                try {
                    const headers = {};
                    const token = localStorage.getItem('token');
                    if (token) headers['Authorization'] = `Bearer ${token}`;
                    const res = await fetch(`${API_BASE}/posts/${id}`, { headers });
                    const p = await parseJsonSafe(res, {});
                    if (reqSeq !== currentDetailRequestSeq || currentDetailPostId !== id) return;
                    if (!res.ok) {
                        if (res.status === 401) {
                            localStorage.removeItem('token');
                            currentUser = null;
                            UI.updateAuth();
                        }
                        body.innerHTML = `<div style="color:var(--text-muted); padding:1.5rem;">${p.error || '加载失败'}</div>`;
                        return;
                    }

                    const isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
                    let contentHtml = p.content;
                    let repostHtml = '';
                    if (p.original_post_id && p.original_post) {
                        contentHtml = p.repost_comment || '';
                        repostHtml = `
                            <div style="margin:1rem 0; padding:1rem; border:1px solid var(--border-color); border-radius:8px; background:var(--bg-secondary);">
                                <div style="font-weight:600; margin-bottom:0.5rem;">${p.original_post.title}</div>
                                <div style="font-size:0.9rem; color:var(--text-secondary);">${p.original_post.content}</div>
                            </div>
                        `;
                    }

                const escapeDataAttr = (s) => (s == null ? '' : String(s)).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                const renderComments = (comments, depth=0) => {
                    if (!comments || comments.length === 0) return '';
                    return comments.map(c => `
                        <div class="comment-item" style="margin-left: ${depth * 20}px; border-left: ${depth > 0 ? '2px solid var(--border-color)' : 'none'}; padding-left: ${depth > 0 ? '1rem' : '0'};">
                            <div class="comment-header">
                                <span>${escapeHtml((c.author && c.author.nickname) || '匿名')}</span>
                                <span>${new Date(c.created_at).toLocaleDateString()}</span>
                            </div>
                            <div style="margin-bottom: 0.5rem;">${mentionifyText(c.content || '')}</div>
                            <button class="btn btn-ghost" style="padding: 0.2rem 0.5rem; font-size: 0.75rem;" onclick="Interact.replyTo(${p.id}, ${c.id}, this.getAttribute('data-nickname'))" data-nickname="${escapeDataAttr((c.author && c.author.nickname) || '')}">↩ 回复</button>
                            ${c.replies ? renderComments(c.replies, depth + 1) : ''}
                        </div>
                    `).join('');
                };

                const commentsHtml = renderComments(p.comments);

                let adminControls = '';
                if (currentUser && currentUser.is_admin) {
                    adminControls = `
                        <div style="margin-top:1rem; padding-top:1rem; border-top:1px dashed var(--accent-red); color:var(--accent-red);">
                            <div style="margin-bottom:0.5rem; font-size:0.8rem; font-weight:bold;">👮 管理员操作</div>
                            <div style="display:flex; gap:0.5rem;">
                                <button class="btn btn-ghost" onclick="Interact.adminDelete(${p.id})" style="border-color:var(--accent-red); color:var(--accent-red);">删除帖子</button>
                                <button class="btn btn-ghost" onclick="Interact.adminToggleHide(${p.id})">${p.is_hidden ? '取消隐藏' : '隐藏帖子'}</button>
                                <button class="btn btn-ghost" onclick="Interact.adminToggleComments(${p.id})">${p.allow_comments ? '关闭评论' : '开启评论'}</button>
                                <button class="btn btn-ghost" onclick="Interact.adminTogglePin(${p.id}, ${p.is_pinned ? 'false' : 'true'})" style="border-color:var(--accent-gold); color:var(--accent-gold);">${p.is_pinned ? '取消置顶' : '设为置顶'}</button>
                            </div>
                        </div>
                    `;
                }

                const series = Array.isArray(p.series) ? p.series : [];
                const seriesHtml = series.length ? series.map((s) => `
                    <div class="series-block">
                        <div style="margin-bottom:0.35rem;">📚 所属系列：<a href="/series/${s.series_id}" data-no-transition="1" style="color:var(--accent-purple-light); text-decoration:underline;">${escapeHtml(s.title || '')}</a> · 第 ${s.order_index} 篇</div>
                        <div style="display:flex; gap:0.5rem; flex-wrap:wrap;">
                            ${s.prev_post_id ? `<button class="btn btn-ghost btn-sm" onclick="Modal.openDetail(event, ${s.prev_post_id})">⬅️ 上一篇</button>` : ''}
                            ${s.next_post_id ? `<button class="btn btn-ghost btn-sm" onclick="Modal.openDetail(event, ${s.next_post_id})">➡️ 下一篇</button>` : ''}
                        </div>
                    </div>
                `).join('') : '';
                const readState = detailScrollStore.read(p.id);
                const showResume = !!(readState && Number(readState.top || 0) > 100);
                const resumeHtml = showResume ? `
                    <div class="resume-strip">
                        <span class="resume-strip-text">上次阅读进度约 ${Number(readState.pct || 0)}%，可一键续读</span>
                        <div style="display:flex; gap:0.45rem;">
                            <button class="btn btn-ghost btn-sm" id="resumeReadBtn">恢复位置</button>
                            <button class="btn btn-ghost btn-sm" id="resumeReadResetBtn">从头开始</button>
                        </div>
                    </div>
                ` : '';

                    const authorWallet = escapeDataAttr((p.author && (p.author.wallet_address || p.author.address)) || '');
                    body.innerHTML = `
                    <h2 style="margin-bottom:0.5rem;">${escapeHtml(p.title)}</h2>
                    <div style="font-size:0.85rem; color:var(--text-muted); margin-bottom:1rem; display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">
                        ${p.is_special_announcement ? '<span style="color:var(--accent-orange); font-weight:700;">📜 长公告</span> |' : ''}
                        ${p.is_pinned ? '<span style="color:var(--accent-gold); font-weight:700;">📌 置顶</span> |' : ''}
                        发布者: ${escapeHtml(p.author.nickname)} ${UI.renderAuthorBadge(p.author)} ${p.author.id != null ? formatUserId(p.author.id) : ''} | 浏览: ${p.view_count}
                    </div>
                    ${resumeHtml}
                    <div class="post-detail-content">
                        ${contentHtml}
                        ${repostHtml}
                    </div>
                    <div class="on-chain-evidence" style="margin-top:1rem; padding:0.75rem; background:var(--bg-secondary); border-radius:8px; font-size:0.85rem;">
                        <div style="color:var(--text-muted); margin-bottom:0.5rem;">${isPermanent ? '✅ 已永久保存 · 链上可验' : 'ℹ️ 当前帖子暂未永存'}</div>
                        <div style="display:flex; flex-wrap:wrap; gap:0.5rem 1rem;">
                            ${p.tx_hash ? `<a href="https://bscscan.com/tx/${p.tx_hash}" target="_blank" rel="noopener" style="color:var(--accent-purple);">⛓ 支付凭证 BSCScan</a>` : '<span style="color:var(--text-muted);">无支付凭证</span>'}
                            ${p.ipfs_cid ? `<a href="https://arweave.net/${p.ipfs_cid}" target="_blank" rel="noopener" style="color:var(--accent-gold);">💾 永存档案</a>` : ''}
                        </div>
                    </div>
                    ${seriesHtml}

                    <div style="display:flex; gap:1rem; margin:1rem 0; border-top:1px solid var(--border-color); padding-top:1rem; flex-wrap:wrap;">
                        <button class="btn btn-ghost" onclick="Interact.like(${p.id})">😰 恐惧 (${p.likes_count})</button>
                        <button class="btn btn-ghost" onclick="Interact.bookmark(${p.id})">⭐ 收藏 (${p.is_bookmarked ? '已收' : ''})</button>
                        <button class="btn btn-ghost" onclick="Post.repost(${p.id})">🔄 转发</button>
                        ${currentUser && currentUser.id !== p.author.id ? `<button class="btn btn-ghost" style="color:var(--text-muted); font-size:0.85rem;" onclick="Interact.report(${p.id})">🚩 举报</button>` : ''}
                        ${currentUser && p.author.id !== currentUser.id ? `<button class="btn btn-ghost" style="color:var(--accent-gold);" data-wallet="${authorWallet}" onclick="TipAuthor.open(${p.id}, this.getAttribute('data-wallet') || '')">💰 打赏作者</button>` : ''}
                        ${(currentUser && (p.author.id === currentUser.id || (currentUser.is_admin)) && p.tx_hash && !p.ipfs_cid) ? `<button class="btn btn-ghost" style="color:var(--accent-gold);" onclick="Interact.syncArweave(${p.id})">💾 同步永存档案</button>` : ''}
                    </div>
                    <div class="series-block">
                        <div style="margin-bottom:0.35rem;">🙏 打赏感谢名单</div>
                        <div id="postTipsThanksList" style="font-size:0.82rem; color:var(--text-secondary);">加载中...</div>
                    </div>

                    ${adminControls}

                    <div class="comments-section">
                        <h4>评论</h4>
                        <div style="margin-bottom:1rem;">${commentsHtml}</div>
                        <div style="display:flex; gap:0.5rem; flex-direction: column;">
                            <div id="replyTarget" style="display: none; font-size: 0.8rem; color: var(--accent-purple); padding: 0.2rem 0;">
                                回复 @<span id="replyTargetName"></span> <button class="btn btn-ghost" style="padding: 0 0.3rem; height: auto;" onclick="Interact.cancelReply()">✕</button>
                            </div>
                            <div style="display: flex; gap: 0.5rem;">
                                <input type="text" id="commentInput" class="form-input" placeholder="${p.allow_comments ? '发表评论...' : '评论区已关闭'}" ${!p.allow_comments && (!currentUser || !currentUser.is_admin) ? 'disabled' : ''}>
                                <button class="btn btn-primary" onclick="Interact.comment(${p.id})" ${!p.allow_comments && (!currentUser || !currentUser.is_admin) ? 'disabled' : ''}>发送</button>
                            </div>
                        </div>
                    </div>
                `;
                    body.classList.remove('detail-body-enter');
                    void body.offsetWidth;
                    body.classList.add('detail-body-enter');
                    body.querySelectorAll('.post-detail-content img').forEach(function(im) {
                        im.setAttribute('referrerpolicy', 'no-referrer');
                        im.loading = 'lazy';
                    });
                    if (modalScrollEl) {
                        modalScrollEl.scrollTop = 0;
                        detailScrollStore.unbind(modalScrollEl);
                        requestAnimationFrame(() => {
                            modalScrollEl.scrollTop = 0;
                            detailScrollStore.bind(p.id, modalScrollEl);
                        });
                    }
                    const resumeBtn = document.getElementById('resumeReadBtn');
                    const resetBtn = document.getElementById('resumeReadResetBtn');
                    if (resumeBtn && modalScrollEl && readState) {
                        resumeBtn.onclick = () => {
                            const maxScroll = Math.max(0, modalScrollEl.scrollHeight - modalScrollEl.clientHeight);
                            modalScrollEl.scrollTop = Math.min(maxScroll, Math.max(0, Number(readState.top || 0)));
                            Toast.info('已恢复到上次阅读位置');
                        };
                    }
                    if (resetBtn && modalScrollEl) {
                        resetBtn.onclick = () => {
                            modalScrollEl.scrollTop = 0;
                            detailScrollStore.save(p.id, 0, Math.max(0, modalScrollEl.scrollHeight - modalScrollEl.clientHeight));
                        };
                    }
                    const tipsWrap = document.getElementById('postTipsThanksList');
                    if (tipsWrap) {
                        try {
                            const tipRes = await fetch(`${API_BASE}/posts/${p.id}/tips?page=1&per_page=12`);
                            const tipData = await parseJsonSafe(tipRes, {});
                            if (reqSeq !== currentDetailRequestSeq || currentDetailPostId !== id) return;
                            const tipItems = (tipData && tipData.items) || [];
                            if (!tipRes.ok || !tipItems.length) {
                                tipsWrap.textContent = '暂无打赏记录';
                            } else {
                                tipsWrap.innerHTML = tipItems.map((t) => {
                                    const nick = (t.from_user && t.from_user.nickname) || '匿名用户';
                                    const dateText = t.created_at ? new Date(t.created_at).toLocaleDateString() : '';
                                    return `<span style="display:inline-block; margin-right:0.45rem; margin-bottom:0.35rem; padding:0.18rem 0.42rem; border:1px solid var(--border-color); border-radius:999px;">${escapeHtml(nick)} ${escapeHtml(dateText)}</span>`;
                                }).join('');
                            }
                        } catch (_) {
                            tipsWrap.textContent = '加载失败';
                        }
                    }
                } catch (e) {
                    body.innerHTML = `<div style="color:var(--text-muted); padding:1.5rem;">${escapeHtml((e && e.message) || '加载失败')}</div>`;
                }
            }
        };

        const Interact = {
            currentReplyParentId: null,

            replyTo(postId, commentId, username) {
                this.currentReplyParentId = commentId;
                const name = (username != null && username !== '') ? username : '匿名';
                document.getElementById('replyTarget').style.display = 'block';
                document.getElementById('replyTargetName').textContent = name;
                document.getElementById('commentInput').focus();
                document.getElementById('commentInput').placeholder = `回复 @${name}...`;
            },

            cancelReply() {
                this.currentReplyParentId = null;
                document.getElementById('replyTarget').style.display = 'none';
                document.getElementById('commentInput').placeholder = '发表评论...';
            },

            async report(postId) {
                if (!currentUser) return Modal.open('loginModal');
                const reason = prompt('请简要说明举报原因（违规内容、广告、抄袭等）：');
                if (reason == null || !reason.trim()) return;
                if (reason.length > 500) { Toast.error('原因最多500字'); return; }
                try {
                    const res = await fetch(`${API_BASE}/reports`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                        body: JSON.stringify({ post_id: postId, reason: reason.trim() })
                    });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) { Toast.success(data.message || '举报已提交'); }
                    else Toast.error(data.error || '提交失败');
                } catch (e) { Toast.error('网络错误'); }
            },

            async like(id) { await this.do(`${API_BASE}/posts/${id}/like`); Modal.openDetail(id); },
            async bookmark(id) { await this.do(`${API_BASE}/posts/${id}/bookmark`); Modal.openDetail(id); },
            async syncArweave(id) {
                if (!currentUser) return Modal.open('loginModal');
                try {
                    const res = await fetch(`${API_BASE}/posts/${id}/sync-arweave`, { method: 'POST', headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` } });
                    const data = await parseJsonSafe(res, {});
                    if (res.ok) { Toast.success(data.message || '已同步永存档案'); Modal.openDetail(id); }
                    else Toast.error(data.error || '同步失败');
                } catch (e) { Toast.error('网络错误'); }
            },
            async comment(id) {
                const c = document.getElementById('commentInput').value;
                if(!c) return;
                const body = { content: c };
                if (this.currentReplyParentId) body.parent_id = this.currentReplyParentId;
                const res = await fetch(`${API_BASE}/posts/${id}/comments`, {
                    method: 'POST', headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}`},
                    body: JSON.stringify(body)
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok) { Toast.error(data.error || '评论失败'); return; }
                this.cancelReply();
                Modal.openDetail(id);
            },
            async do(url) {
                if(!currentUser) return Modal.open('loginModal');
                await fetch(url, { method: 'POST', headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`} });
            },

            async adminDelete(id) {
                if(!confirm('确定要删除这个帖子吗？此操作不可逆！')) return;
                const res = await fetch(`${API_BASE}/posts/${id}`, {
                    method: 'DELETE',
                    headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`}
                });
                if(res.ok) { Toast.success('已删除'); Modal.close('postDetailModal'); Post.load(); }
                else Toast.error('删除失败');
            },
            async adminToggleHide(id) {
                const res = await fetch(`${API_BASE}/admin/posts/${id}/hide`, {
                    method: 'POST', headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`}
                });
                if(res.ok) { Toast.success('状态已更新'); Modal.openDetail(id); Post.load(); }
            },
            async adminToggleComments(id) {
                const res = await fetch(`${API_BASE}/admin/posts/${id}/toggle-comments`, {
                    method: 'POST', headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`}
                });
                if(res.ok) { Toast.success('状态已更新'); Modal.openDetail(id); }
                else {
                    const d = await parseJsonSafe(res, {});
                    Toast.error(d.error || '操作失败');
                }
            },
            async adminTogglePin(id, pinned) {
                const res = await fetch(`${API_BASE}/admin/posts/${id}/pin`, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json', 'Authorization': `Bearer ${localStorage.getItem('token')}`},
                    body: JSON.stringify({ pinned, exclusive: true })
                });
                const data = await parseJsonSafe(res, {});
                if (res.ok) {
                    Toast.success(pinned ? '已置顶' : '已取消置顶');
                    await Post.loadPinnedGuide();
                    Modal.openDetail(id);
                    Post.load();
                } else {
                    Toast.error(data.error || '操作失败');
                }
            }
        };

        const Toast = window.Toast || {
            show(msg, type) {
                const t = document.createElement('div');
                t.className = `toast ${type}`;
                t.textContent = msg;
                document.getElementById('toastContainer').appendChild(t);
                setTimeout(()=>t.remove(), 3000);
            },
            success(m) { this.show(m, 'success'); },
            error(m) { this.show(m, 'error'); },
            info(m) { this.show(m, 'info'); },
            warning(m) { this.show(m, 'warning'); }
        };

        window.addEventListener('load', () => {
            Onboarding.bindClose();
            const c = document.getElementById('ghostFireContainer');
            const isMobile = window.innerWidth < 768;
            const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
            const lowPerfDevice = (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4)
                || (typeof navigator.deviceMemory !== 'undefined' && navigator.deviceMemory <= 4);
            if (reduceMotion || lowPerfDevice) document.body.classList.add('reduce-motion');

            const count = (reduceMotion || lowPerfDevice) ? 0 : (isMobile ? 3 : 6);
            if (c && count > 0) {
                for (let i = 0; i < count; i++) {
                    const d = document.createElement('div');
                    d.className = 'ghost-fire';
                    d.style.left = Math.random() * 100 + '%';
                    d.style.animationDelay = Math.random() * 5 + 's';
                    c.appendChild(d);
                }
            } else if (c) {
                c.style.display = 'none';
            }
            Auth.init();
            Post.loadPinnedGuide();
            Post.load();
            Post.initAutoLoad();
            const postId = new URLSearchParams(window.location.search).get('post');
            if (postId && /^\d+$/.test(postId)) {
                setTimeout(() => Modal.openDetail(parseInt(postId, 10)), 300);
            }
            document.getElementById('loginForm').onsubmit = (e) => {
                e.preventDefault();
                Auth.loginWeb2(document.getElementById('loginUsername').value, document.getElementById('loginPassword').value);
            };

            const mobileUtilityToggleBtn = document.getElementById('mobileUtilityToggleBtn');
            const mobileUtilityStack = document.getElementById('mobileUtilityStack');
            const mobileUtilityHost = document.getElementById('mobileUtilityHost');
            const mobileUtilityMount = document.getElementById('mobileUtilityMount');
            const sidebarEl = document.querySelector('.sidebar');
            const navSortCard = sidebarEl ? sidebarEl.querySelector('.nav-sort-card') : null;
            let mobileUtilityOpen = false;
            const relocateMobileUtility = () => {
                if (!mobileUtilityHost || !mobileUtilityMount || !sidebarEl || !navSortCard) return;
                const isMobileView = window.matchMedia('(max-width: 768px)').matches;
                if (isMobileView) {
                    if (mobileUtilityHost.parentElement !== mobileUtilityMount) {
                        mobileUtilityMount.appendChild(mobileUtilityHost);
                    }
                    return;
                }
                if (mobileUtilityHost.parentElement !== sidebarEl) {
                    if (navSortCard.nextSibling) sidebarEl.insertBefore(mobileUtilityHost, navSortCard.nextSibling);
                    else sidebarEl.appendChild(mobileUtilityHost);
                }
            };
            const applyMobileUtilityState = () => {
                if (!mobileUtilityToggleBtn || !mobileUtilityStack) return;
                const isMobileView = window.matchMedia('(max-width: 768px)').matches;
                if (!isMobileView) {
                    mobileUtilityStack.classList.add('is-open');
                    mobileUtilityToggleBtn.setAttribute('aria-expanded', 'true');
                    return;
                }
                mobileUtilityStack.classList.toggle('is-open', mobileUtilityOpen);
                mobileUtilityToggleBtn.setAttribute('aria-expanded', String(!!mobileUtilityOpen));
            };
            if (mobileUtilityToggleBtn && mobileUtilityStack) {
                mobileUtilityToggleBtn.onclick = () => {
                    mobileUtilityOpen = !mobileUtilityOpen;
                    applyMobileUtilityState();
                };
                const syncMobileUtility = () => {
                    relocateMobileUtility();
                    applyMobileUtilityState();
                };
                syncMobileUtility();
                window.addEventListener('resize', syncMobileUtility);
            }

            const searchInput = document.getElementById('searchInput');
            let searchTimeout;
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    clearTimeout(searchTimeout);
                    searchTimeout = setTimeout(() => {
                        const q = e.target.value.trim();
                        if (q) Post.load({q});
                        else Post.load({ q: '' });
                    }, 300);
                });
            }

            const applyFilterBtn = document.getElementById('searchFilterApplyBtn');
            const resetFilterBtn = document.getElementById('searchFilterResetBtn');
            const searchAdvancedBar = document.getElementById('searchAdvancedBar');
            const searchContainer = document.getElementById('searchContainer');
            const searchToggleBtn = document.getElementById('searchToggleBtn');
            const hasAdvancedValues = () => {
                const from = (document.getElementById('searchFromDate') || {}).value || '';
                const to = (document.getElementById('searchToDate') || {}).value || '';
                const tags = (document.getElementById('searchTags') || {}).value || '';
                const permanent = !!((document.getElementById('searchPermanentOnly') || {}).checked);
                return !!(from || to || tags.trim() || permanent);
            };
            const openAdvanced = () => {
                if (!searchAdvancedBar) return;
                searchAdvancedBar.classList.add('is-open');
            };
            const closeAdvanced = (force) => {
                if (!searchAdvancedBar) return;
                if (!force && hasAdvancedValues()) return;
                searchAdvancedBar.classList.remove('is-open');
            };
            if (applyFilterBtn) {
                applyFilterBtn.onclick = () => {
                    const filters = {
                        from_date: (document.getElementById('searchFromDate') || {}).value || '',
                        to_date: (document.getElementById('searchToDate') || {}).value || '',
                        permanent_only: !!((document.getElementById('searchPermanentOnly') || {}).checked),
                        tags: (document.getElementById('searchTags') || {}).value || ''
                    };
                    Post.load({ q: (searchInput || {}).value || '', filters: filters });
                    closeAdvanced(true);
                };
            }
            if (resetFilterBtn) {
                resetFilterBtn.onclick = () => {
                    const fromEl = document.getElementById('searchFromDate');
                    const toEl = document.getElementById('searchToDate');
                    const perEl = document.getElementById('searchPermanentOnly');
                    const tagsEl = document.getElementById('searchTags');
                    if (fromEl) fromEl.value = '';
                    if (toEl) toEl.value = '';
                    if (perEl) perEl.checked = false;
                    if (tagsEl) tagsEl.value = '';
                    Post.load({ q: (searchInput || {}).value || '', filters: { from_date: '', to_date: '', permanent_only: false, tags: '' } });
                    closeAdvanced(true);
                };
            }

            if (searchInput) {
                searchInput.addEventListener('focus', openAdvanced);
                searchInput.addEventListener('click', openAdvanced);
            }
            if (searchToggleBtn) {
                searchToggleBtn.onclick = () => {
                    if (searchAdvancedBar && searchAdvancedBar.classList.contains('is-open')) {
                        closeAdvanced(true);
                    } else {
                        openAdvanced();
                        if (searchInput) searchInput.focus();
                    }
                };
            }
            document.addEventListener('click', (e) => {
                if (!searchContainer || !searchAdvancedBar) return;
                if (!searchAdvancedBar.classList.contains('is-open')) return;
                if (searchContainer.contains(e.target)) return;
                closeAdvanced(true);
            });
            document.addEventListener('keydown', (e) => {
                if (e.key === 'Escape') closeAdvanced(true);
            });

            // Mobile: Close keyboard on 'Enter' or 'Search'
            if (searchInput) {
                searchInput.addEventListener('keyup', (e) => {
                    if(e.key === 'Enter') {
                        searchInput.blur();
                        closeAdvanced(true);
                    }
                });
                searchInput.addEventListener('search', () => {
                    searchInput.blur();
                    closeAdvanced(true);
                });
            }

            // Mobile: Close keyboard on scroll
            window.addEventListener('scroll', () => {
                if(searchInput && document.activeElement === searchInput) {
                    searchInput.blur();
                }
                closeAdvanced(true);
            });

            document.getElementById('logoutBtn').onclick = () => Auth.logout();
        });
