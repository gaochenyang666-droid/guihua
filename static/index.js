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
                            const addAdminAction = (el) => {
                                if (el.parentNode !== userMenuAdmin) userMenuAdmin.appendChild(el);
                            };
                            addAdminAction(usersBtn);
                            addAdminAction(reportsBtn);
                            addAdminAction(annBtn);
                            addAdminAction(groupBtn);
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
            parseJsonSafe,
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
            parseJsonSafe,
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
            Modal,
            parseJsonSafe
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
            parseJsonSafe,
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
            parseJsonSafe,
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

        window.addEventListener('load', () => {
            try {
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
                const next = `/post/${parseInt(postId, 10)}`;
                window.location.replace(next);
                return;
            }
            const loginForm = document.getElementById('loginForm');
            if (loginForm) {
                loginForm.onsubmit = (e) => {
                    e.preventDefault();
                    const un = document.getElementById('loginUsername');
                    const pw = document.getElementById('loginPassword');
                    if (un && pw) Auth.loginWeb2(un.value, pw.value);
                };
            }
            const navbarEl = document.getElementById('mainNavbar');
            const mobileNavToggleBtn = document.getElementById('mobileNavToggleBtn');
            const mobileNavPanel = document.getElementById('mobileNavPanel');
            const isMobileNav = () => window.matchMedia('(max-width: 768px)').matches;
            const closeMobileNav = () => {
                if (!navbarEl) return;
                navbarEl.classList.remove('mobile-nav-open');
                if (mobileNavToggleBtn) mobileNavToggleBtn.setAttribute('aria-expanded', 'false');
            };
            const openMobileNav = () => {
                if (!navbarEl) return;
                navbarEl.classList.add('mobile-nav-open');
                if (mobileNavToggleBtn) mobileNavToggleBtn.setAttribute('aria-expanded', 'true');
            };
            if (navbarEl && mobileNavToggleBtn && mobileNavPanel) {
                mobileNavToggleBtn.onclick = (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    if (!isMobileNav()) return;
                    if (navbarEl.classList.contains('mobile-nav-open')) closeMobileNav();
                    else openMobileNav();
                };
                mobileNavPanel.addEventListener('click', (e) => {
                    if (!isMobileNav()) return;
                    const target = e.target;
                    if (!(target instanceof Element)) return;
                    if (target.closest('.search-container') || target.closest('#searchAdvancedBar')) return;
                    if (target.closest('button, a')) closeMobileNav();
                });
                document.addEventListener('click', (e) => {
                    if (!isMobileNav()) return;
                    if (!navbarEl.contains(e.target)) closeMobileNav();
                });
                document.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape') closeMobileNav();
                });
                const handleNavbarResize = debounce(() => {
                    if (!isMobileNav()) closeMobileNav();
                }, 180);
                window.addEventListener('resize', handleNavbarResize, { passive: true });
            }

            const mobileUtilityToggleBtn = document.getElementById('mobileUtilityToggleBtn');
            const mobileUtilityStack = document.getElementById('mobileUtilityStack');
            const mobileUtilityHost = document.getElementById('mobileUtilityHost');
            const mobileQuickActions = document.getElementById('mobileQuickActions');
            const leftSidebarEl = document.querySelector('.sidebar-left');
            const rightSidebarEl = document.getElementById('rightSidebar');
            const navSortCard = leftSidebarEl ? leftSidebarEl.querySelector('.nav-sort-card') : null;
            let mobileUtilityOpen = !window.matchMedia('(max-width: 768px)').matches;
            const quickActionButtons = mobileQuickActions ? Array.from(mobileQuickActions.querySelectorAll('.mobile-quick-btn[data-panel]')) : [];
            const setQuickButtonActive = (panel) => {
                if (!quickActionButtons.length) return;
                quickActionButtons.forEach((btn) => {
                    btn.classList.toggle('is-active', !!panel && btn.getAttribute('data-panel') === panel);
                });
            };
            window.__setUtilityQuickActive = setQuickButtonActive;
            UtilityPanels.init();
            const relocateMobileUtility = () => {
                if (!mobileUtilityHost || !navSortCard) return;
                const isMobileView = window.matchMedia('(max-width: 768px)').matches;
                if (!isMobileView) {
                    if (rightSidebarEl && mobileUtilityHost.parentElement !== rightSidebarEl) {
                        rightSidebarEl.appendChild(mobileUtilityHost);
                    }
                    return;
                }
                if (!leftSidebarEl) return;
                const anchorNode = isMobileView
                    ? (mobileQuickActions && mobileQuickActions.parentElement === leftSidebarEl ? mobileQuickActions : navSortCard)
                    : navSortCard;
                if (mobileUtilityHost.parentElement !== leftSidebarEl) {
                    if (anchorNode && anchorNode.nextSibling) leftSidebarEl.insertBefore(mobileUtilityHost, anchorNode.nextSibling);
                    else leftSidebarEl.appendChild(mobileUtilityHost);
                    return;
                }
                if (anchorNode && mobileUtilityHost.previousSibling !== anchorNode) {
                    if (anchorNode.nextSibling) leftSidebarEl.insertBefore(mobileUtilityHost, anchorNode.nextSibling);
                    else leftSidebarEl.appendChild(mobileUtilityHost);
                }
            };
            const applyMobileUtilityState = () => {
                if (!mobileUtilityStack) return;
                const isMobileView = window.matchMedia('(max-width: 768px)').matches;
                if (!isMobileView) {
                    mobileUtilityStack.classList.add('is-open');
                    if (mobileUtilityToggleBtn) mobileUtilityToggleBtn.setAttribute('aria-expanded', 'true');
                    setQuickButtonActive('');
                    return;
                }
                if (mobileUtilityToggleBtn) {
                    mobileUtilityStack.classList.toggle('is-open', mobileUtilityOpen);
                    mobileUtilityToggleBtn.setAttribute('aria-expanded', String(!!mobileUtilityOpen));
                    if (!mobileUtilityOpen) {
                        UtilityPanels.collapseAll();
                        setQuickButtonActive('');
                    }
                } else {
                    mobileUtilityOpen = true;
                    mobileUtilityStack.classList.add('is-open');
                }
            };
            if (mobileUtilityToggleBtn && mobileUtilityStack) {
                mobileUtilityToggleBtn.onclick = () => {
                    mobileUtilityOpen = !mobileUtilityOpen;
                    if (mobileUtilityOpen) UtilityPanels.collapseAll();
                    applyMobileUtilityState();
                };
            }
            if (mobileUtilityStack && mobileUtilityHost) {
                const syncMobileUtility = () => {
                    relocateMobileUtility();
                    applyMobileUtilityState();
                };
                syncMobileUtility();
                window.addEventListener('resize', debounce(syncMobileUtility, 160), { passive: true });
            }
            if (quickActionButtons.length) {
                quickActionButtons.forEach((btn) => {
                    btn.onclick = () => {
                        const panel = btn.getAttribute('data-panel') || '';
                        if (!panel) return;
                        if (mobileUtilityToggleBtn && !mobileUtilityOpen) {
                            mobileUtilityOpen = true;
                            applyMobileUtilityState();
                        } else if (mobileUtilityStack && !mobileUtilityStack.classList.contains('is-open')) {
                            mobileUtilityStack.classList.add('is-open');
                        }
                        const card = document.querySelector(`[data-utility-key="${panel}"]`);
                        const alreadyOpen = !!(card && card.classList.contains('is-expanded'));
                        if (alreadyOpen) {
                            UtilityPanels.collapseAll();
                            return;
                        }
                        const ok = UtilityPanels.expand(panel);
                        if (!ok) return;
                        const target = document.querySelector(`[data-utility-key="${panel}"]`);
                        if (target) {
                            requestAnimationFrame(() => {
                                try {
                                    target.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                                } catch (_) {}
                            });
                        }
                    };
                });
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
            const handleWindowScroll = () => {
                if(searchInput && document.activeElement === searchInput) {
                    searchInput.blur();
                }
                closeAdvanced(true);
            };
            window.addEventListener('scroll', handleWindowScroll, { passive: true });

            const logoutBtn = document.getElementById('logoutBtn');
            if (logoutBtn) logoutBtn.onclick = () => Auth.logout();
            } catch (err) {
                console.error('[诡话] 首页初始化错误:', err);
            }
        });
