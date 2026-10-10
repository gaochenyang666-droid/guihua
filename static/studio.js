(function () {
    'use strict';

        const API_BASE = window.location.origin + '/api';
        const apiJson = window.apiJson;
        const buildStudioSeries = window.GHStudioSeriesFactory;
        const buildStudioPublish = window.GHStudioPublishFactory;
        const buildStudioEditor = window.GHStudioEditorFactory;
        const buildStudioShell = window.GHStudioShellFactory;
        const Toast = window.Toast;
        let currentUser = null;

        let studioQuill = null;
        let lastEditorRange = null;

        function setDraftStatus(message, active) {
            const status = document.getElementById('draftStatus');
            if (!status) return;
            status.textContent = message || '';
            status.classList.toggle('is-active', !!active && !!message);
        }

        function setHidden(id, hidden) {
            const el = document.getElementById(id);
            if (!el) return null;
            if (hidden) el.setAttribute('hidden', '');
            else el.removeAttribute('hidden');
            return el;
        }

        const PENDING_POST_KEY = 'studio_pending_post';
        const Draft = {
            save() {
                if (!studioQuill) return;
                const title = document.getElementById('studioPostTitle').value;
                const content = studioQuill.root.innerHTML;
                const seriesId = ((document.getElementById('studioSeriesSelect') || {}).value || '').trim();
                if(title || content || seriesId) {
                    localStorage.setItem('studio_draft', JSON.stringify({title, content, series_id: seriesId || null, time: Date.now()}));
                    setDraftStatus('已自动保存 ' + new Date().toLocaleTimeString(), true);
                    setTimeout(() => setDraftStatus(document.getElementById('draftStatus') ? document.getElementById('draftStatus').textContent : '', false), 2000);
                }
            },
            load() {
                if (!studioQuill) return;
                try {
                    const d = JSON.parse(localStorage.getItem('studio_draft'));
                    if(d && (Date.now() - d.time < 24*60*60*1000)) {
                        if(d.title) document.getElementById('studioPostTitle').value = d.title;
                        if(d.content) studioQuill.clipboard.dangerouslyPasteHTML(d.content || '');
                        if (window.Studio && typeof window.Studio.loadSeriesOptions === 'function') {
                            window.Studio.loadSeriesOptions(d.series_id || '');
                        }
                        if(d.title || d.content || d.series_id) Toast.info('已自动恢复上次的草稿 📝');
                    }
                } catch(e) {}
            },
            clear() { localStorage.removeItem('studio_draft'); localStorage.removeItem(PENDING_POST_KEY); }
        };

        const Auth = {
            async init() {
                await this.fetchMe();
                if (!currentUser) {
                    Toast.info('请先登录');
                    if (typeof openLoginPage === 'function') openLoginPage('/studio');
                    else navigateWithTransition('/login?next=%2Fstudio');
                    return;
                }
                UI.updateAuth();
                Draft.load(); 
                if (window.Studio) Studio.loadPendingPost();
                Studio.updateFeeDisplay();
                Studio.loadSeriesOptions();
                
                document.getElementById('studioPostTitle').addEventListener('input', () => Draft.save());
                const seriesSelect = document.getElementById('studioSeriesSelect');
                if (seriesSelect) seriesSelect.addEventListener('change', () => Draft.save());
                if (studioQuill) studioQuill.on('text-change', () => Draft.save());
            },

            async fetchMe() {
                try {
                    const result = await apiJson(`${API_BASE}/user/me`, { fallback: {}, check401: false });
                    const res = result.res;
                    if (res.ok) {
                        currentUser = result.data;
                        if (window.authState && window.authState.markLoggedIn) window.authState.markLoggedIn();
                        if (!currentUser.is_admin && currentUser.type !== 'web3') {
                            alert('仅限 Web3 创作者或管理员进入');
                            navigateWithTransition('/');
                            return;
                        }
                    } else {
                        if (res.status === 401 && window.authState && window.authState.clear) window.authState.clear();
                        if (typeof openLoginPage === 'function') openLoginPage('/studio');
                        else navigateWithTransition('/login?next=%2Fstudio');
                    }
                } catch(e) { console.error(e); }
            }
        };

        const studioDeps = {
            apiBase: API_BASE,
            apiJson,
            getCurrentUser: () => currentUser,
            getQuill: () => studioQuill,
            setQuill: (value) => { studioQuill = value; },
            getLastEditorRange: () => lastEditorRange,
            setLastEditorRange: (value) => { lastEditorRange = value; },
            getSeriesSelectValue: () => {
                const select = document.getElementById('studioSeriesSelect');
                if (!select) return '';
                return (select.value || '').trim();
            },
            Draft,
            setHidden,
            escapeHtml,
            Toast,
            handle401,
            navigateWithTransition
        };

        const Studio = Object.assign({
            currentStep: 1,
            isPublishing: false,
            logInterval: null,
            timeoutId: null,
            pendingTxHash: null,
            seriesItems: [],

            nextStep(step) {
                if (this.currentStep === 1) {
                    const title = document.getElementById('studioPostTitle').value;
                    const content = studioQuill ? studioQuill.getText().trim() : '';
                    if(!title.trim() || !content) return Toast.error('请填写标题和正文');
                }
                if (step === 3) {
                    this.checkWalletEnv();
                }

                document.getElementById(`step${this.currentStep}`).classList.remove('active');
                document.getElementById(`stepIndicator${this.currentStep}`).classList.remove('active');
                
                this.currentStep = step;
                
                document.getElementById(`step${this.currentStep}`).classList.add('active');
                document.getElementById(`stepIndicator${this.currentStep}`).classList.add('active');
            },

            async runPrecheck() {
                if (!currentUser) return { ok: false, issues: ['登录已失效，请重新登录'], warnings: [] };
                const title = document.getElementById('studioPostTitle').value || '';
                const content = studioQuill ? studioQuill.root.innerHTML : '';
                try {
                    const result = await apiJson(`${API_BASE}/posts/precheck`, {
                        method: 'POST',
                        body: { title, content },
                        fallback: {}
                    });
                    const res = result.res;
                    const data = result.data;
                    if (!res.ok) return { ok: false, issues: [data.error || '发布前检查失败'], warnings: [] };
                    return data;
                } catch (e) {
                    return { ok: false, issues: ['发布前检查网络异常'], warnings: [] };
                }
            },

            prevStep(step) {
                document.getElementById(`step${this.currentStep}`).classList.remove('active');
                document.getElementById(`stepIndicator${this.currentStep}`).classList.remove('active');
                
                this.currentStep = step;
                
                document.getElementById(`step${this.currentStep}`).classList.add('active');
                document.getElementById(`stepIndicator${this.currentStep}`).classList.add('active');
            },

            async updateFeeDisplay() {
                const el = document.getElementById('studioFeeDisplay');
                if (!el) return;
                try {
                    const result = await apiJson(`${API_BASE}/config/fees`, { auth: false, fallback: {} });
                    if (result.res.ok) {
                        const cfg = result.data;
                        const usdt = (cfg.fee_usdt != null ? cfg.fee_usdt : (Number(cfg.fee) / 1e18)).toFixed(2);
                        el.textContent = cfg.fee_currency === 'USDT' ? `${usdt} USDT` : `${usdt} USDT`;
                    } else {
                        el.textContent = '以支付时为准';
                    }
                } catch (e) {
                    el.textContent = '以支付时为准';
                }
            },

            seriesSelectValue() {
                const select = document.getElementById('studioSeriesSelect');
                if (!select) return '';
                return (select.value || '').trim();
            },

            }
        }, buildStudioSeries ? buildStudioSeries(studioDeps) : {}, buildStudioPublish ? buildStudioPublish(studioDeps) : {});

        const UI = {
            updateAuth() {
                const userMenu = document.getElementById('userMenu');
                if (currentUser) {
                    if (userMenu) {
                        userMenu.hidden = false;
                        userMenu.style.display = 'flex';
                    }
                    let displayName = currentUser.nickname || (currentUser.address ? currentUser.address.substring(0, 6) : '');
                    const nameEl = document.getElementById('userDisplayName');
                    if (nameEl) nameEl.textContent = displayName;
                    const badgeEl = document.getElementById('userIdBadge');
                    if (badgeEl && currentUser.id != null) badgeEl.innerHTML = formatUserId(currentUser.id, currentUser);
                    const avatarEl = document.getElementById('userAvatarEmoji');
                    if (avatarEl) avatarEl.textContent = currentUser.avatar || '👻';
                }
            }
        };

        const Modal = {
            close(id) { document.getElementById(id).classList.remove('active'); }
        };

        const StudioEditor = buildStudioEditor ? buildStudioEditor(studioDeps) : null;
        const StudioShell = buildStudioShell ? buildStudioShell({
            initQuill: () => StudioEditor && StudioEditor.initQuill(),
            bindStaticActions: () => Studio.bindStaticActions(),
            initAuth: () => Auth.init()
        }) : null;

        window.addEventListener('load', () => {
            if (StudioShell && typeof StudioShell.init === 'function') StudioShell.init();
        });

    window.Studio = Studio;
    window.Auth = Auth;
    window.UI = UI;
    window.Modal = Modal;
})();
