        const API_BASE = window.location.origin + '/api';
        let currentUser = null;
        const getCurrentUser = () => currentUser;
        const setCurrentUser = (user) => { currentUser = user; window.currentUser = user; };
        window.currentUser = currentUser;
        const stripHtml = (s) => (s == null ? '' : String(s)).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim();
        const escapeAttr = window.escapeAttr;
        const escapeDataAttr = window.escapeAttr;
        const parseJsonSafe = window.parseJsonSafe;
        const debounce = (fn, wait = 180) => {
            let timer = null;
            return (...args) => {
                if (timer) clearTimeout(timer);
                timer = window.setTimeout(() => {
                    timer = null;
                    fn(...args);
                }, wait);
            };
        };
        const prefersReducedMotionUi = () => !!(document.body && document.body.classList.contains('reduce-motion'));
        const fetchJsonSafe = async (url, options = {}, cfg = {}) => {
            const conf = cfg || {};
            const fallback = Object.prototype.hasOwnProperty.call(conf, 'fallback') ? conf.fallback : {};
            const errorMessage = conf.errorMessage || '请求失败';
            const checkUnauthorized = !!conf.checkUnauthorized;
            const result = await window.apiJson(url, Object.assign({}, options, {
                fallback,
                check401: checkUnauthorized
            }));
            const res = result.res;
            const data = result.data;
            if (conf.throwOnNotOk && !res.ok) {
                const e = new Error((data && data.error) || `${errorMessage}(${res.status})`);
                e.status = res.status;
                e.data = data;
                e.response = res;
                throw e;
            }
            return { res, data };
        };
        const mentionifyText = window.mentionifyText;
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

        let Auth;
        let Post;
        let UI;
        let Modal;
        let Interact;
        let Donate;
        let TipAuthor;
        let copyTextWithFallback;
        let Notification;
        let SiteNotice;
        let NoticeCenter;
        let Onboarding;
        let Checkin;
        let GroupLinks;
        let UtilityPanels;
        let Admin;

        UI = {
            updateAuth() {
                const authBtns = document.getElementById('authButtons');
                const userMenu = document.getElementById('userMenu');
                const userMenuMain = document.getElementById('userMenuMain');
                const userMenuAdmin = document.getElementById('userMenuAdmin');
                const userMenuAdminSection = document.getElementById('userMenuAdminSection');
                if (!authBtns || !userMenu || !userMenuMain || !userMenuAdmin || !userMenuAdminSection) {
                    this.syncLeftProfile();
                    Onboarding.load();
                    Checkin.load();
                    GroupLinks.load();
                    return;
                }

                if (currentUser) {
                    authBtns.style.display = 'none';
                    userMenu.style.display = 'flex';
                    const userDisplayNameEl = document.getElementById('userDisplayName');
                    if (userDisplayNameEl) userDisplayNameEl.textContent = currentUser.nickname;

                    let notifBtn = document.getElementById('notifBtn');
                    if(!notifBtn) {
                        notifBtn = document.createElement('div');
                        notifBtn.id = 'notifBtn';
                        notifBtn.style.position = 'relative';
                        notifBtn.style.cursor = 'pointer';
                        notifBtn.style.marginRight = '0.5rem';
                        notifBtn.innerHTML = '<span style="font-size:1.2rem;">🔔</span><div id="notifBadge" style="position:absolute; top:-2px; right:-2px; width:8px; height:8px; background:var(--accent-red); border-radius:50%; display:none;"></div>';
                        notifBtn.onclick = () => {
                            if (typeof navigateWithTransition === 'function') navigateWithTransition('/notifications');
                            else window.location.href = '/notifications';
                        };
                    }
                    if (notifBtn.parentNode !== userMenuMain) userMenuMain.insertBefore(notifBtn, userMenuMain.firstChild || null);
                    Notification.load();

                    let profileLink = document.getElementById('profileLink');
                    if(!profileLink) {
                        profileLink = document.createElement('a');
                        profileLink.id = 'profileLink';
                        profileLink.className = 'btn btn-ghost';
                        profileLink.style.padding = '0.3rem 0.6rem';
                        profileLink.style.fontSize = '0.8rem';
                        profileLink.textContent = '👤 我的主页';
                    }
                    profileLink.href = `/profile?user=${currentUser.username || currentUser.address}`;
                    if (profileLink.parentNode !== userMenuMain) userMenuMain.appendChild(profileLink);

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
                    }
                    if (bindBtn.parentNode !== userMenuMain) userMenuMain.appendChild(bindBtn);
                    const logoutBtn = document.getElementById('logoutBtn');
                    if (logoutBtn) userMenuMain.appendChild(logoutBtn);

                    if(bindBtn && currentUser.address) bindBtn.style.display = 'none';
                    else if (bindBtn) bindBtn.style.display = 'inline-flex';

                    if(currentUser.is_admin) {
                        userMenuAdminSection.hidden = false;
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
                            const pendingBtn = document.createElement('button');
                            pendingBtn.id = 'adminPendingBtn';
                            pendingBtn.className = 'btn btn-ghost';
                            pendingBtn.style.color = 'var(--accent-orange)';
                            pendingBtn.style.borderColor = 'var(--accent-orange)';
                            pendingBtn.textContent = '🧷 待发布';
                            pendingBtn.onclick = Admin.openPendingPublications;
                            const addAdminAction = (el) => {
                                if (el.parentNode !== userMenuAdmin) userMenuAdmin.appendChild(el);
                            };
                            addAdminAction(usersBtn);
                            addAdminAction(reportsBtn);
                            addAdminAction(annBtn);
                            addAdminAction(groupBtn);
                            addAdminAction(pendingBtn);
                            addAdminAction(auditBtn);
                            addAdminAction(statsBtn);
                        }
                    } else {
                        userMenuAdminSection.hidden = true;
                    }

                    if(currentUser.avatar) {
                        const avatarEl = document.getElementById('userAvatarEmoji');
                        if (avatarEl) avatarEl.textContent = currentUser.avatar;
                    }
                } else {
                    authBtns.style.display = 'flex';
                    userMenu.style.display = 'none';
                }
                this.syncLeftProfile();
                Onboarding.load();
                Checkin.load();
                GroupLinks.load();
            },
            syncLeftProfile() {
                const avatarEl = document.getElementById('leftProfileAvatar');
                const nameEl = document.getElementById('leftProfileName');
                const subEl = document.getElementById('leftProfileSub');
                const btnEl = document.getElementById('leftProfileBtn');
                const bindBtnEl = document.getElementById('leftBindWalletBtn');
                if (!avatarEl || !nameEl || !subEl || !btnEl) return;
                if (!currentUser) {
                    avatarEl.textContent = '👻';
                    nameEl.textContent = '游客';
                    subEl.textContent = '登录后可查看个人中心';
                    btnEl.textContent = '登录 / 进入个人页';
                    if (bindBtnEl) bindBtnEl.hidden = true;
                    return;
                }
                avatarEl.textContent = currentUser.avatar || '👻';
                nameEl.textContent = currentUser.nickname || currentUser.username || '用户';
                const lv = currentUser.level_label || (currentUser.level ? `Lv.${currentUser.level}` : 'Lv.1');
                subEl.textContent = `${lv} · ${currentUser.experience_points || 0} EXP`;
                btnEl.textContent = '查看个人页';
                if (bindBtnEl) {
                    const needBindWallet = !currentUser.address;
                    bindBtnEl.hidden = !needBindWallet;
                    bindBtnEl.textContent = 'Web2 绑定钱包';
                    bindBtnEl.onclick = () => Auth.bindWallet();
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

        const modalInteractModule = window.GHModalInteractFactory({
            API_BASE,
            getCurrentUser,
            Toast,
            detailScrollStore,
            navigateWithTransition,
            getUI: () => UI
        });
        Modal = modalInteractModule.Modal;
        Interact = modalInteractModule.Interact;
        Donate = modalInteractModule.Donate;
        TipAuthor = modalInteractModule.TipAuthor;
        copyTextWithFallback = modalInteractModule.copyTextWithFallback;
        window.Modal = Modal;
        window.Interact = Interact;
        window.Donate = Donate;
        window.TipAuthor = TipAuthor;
        window.copyTextWithFallback = copyTextWithFallback;

        const noticeModule = window.GHHomeNoticesFactory({
            API_BASE,
            getCurrentUser,
            fetchJsonSafe,
            Modal,
            navigateWithTransition
        });
        Notification = noticeModule.Notification;
        SiteNotice = noticeModule.SiteNotice;
        NoticeCenter = noticeModule.NoticeCenter;
        window.Notification = Notification;
        window.SiteNotice = SiteNotice;
        window.NoticeCenter = NoticeCenter;

        const utilityModule = window.GHUtilityPanelsFactory({
            API_BASE,
            getCurrentUser,
            Toast,
            Modal
        });
        Onboarding = utilityModule.Onboarding;
        Checkin = utilityModule.Checkin;
        GroupLinks = utilityModule.GroupLinks;
        UtilityPanels = utilityModule.UtilityPanels;
        window.Onboarding = Onboarding;
        window.Checkin = Checkin;
        window.GroupLinks = GroupLinks;
        window.UtilityPanels = UtilityPanels;

        Admin = window.GHAdminFactory({
            API_BASE,
            fetchJsonSafe,
            parseJsonSafe,
            Toast,
            Modal,
            getSiteNotice: () => SiteNotice,
            getGroupLinks: () => GroupLinks
        });
        window.Admin = Admin;

        const feedModule = window.GHFeedFactory({
            API_BASE,
            stripHtml,
            escapeAttr,
            prefersReducedMotionUi,
            Modal,
            getUI: () => UI,
            getCurrentUser
        });
        Post = feedModule.Post;
        Object.assign(UI, feedModule.feedUi);

        Auth = window.GHAuthFactory({
            API_BASE,
            getCurrentUser,
            setCurrentUser,
            fetchJsonSafe,
            handle401,
            Toast,
            Modal,
            Post,
            UI,
            SiteNotice,
            Onboarding,
            Checkin,
            GroupLinks,
            Notification,
            copyTextWithFallback,
            navigateWithTransition
        });

        const homeShell = window.GHHomeShellFactory({
            Auth,
            Post,
            UtilityPanels,
            Onboarding,
            debounce
        });

        window.addEventListener('load', () => {
            try {
            homeShell.init();
            } catch (err) {
                console.error('[诡话] 首页初始化错误:', err);
            }
        });
