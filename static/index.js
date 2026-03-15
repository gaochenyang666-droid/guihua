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
                        bar.onclick = null;
                        bar.style.cursor = '';
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
                    bar.style.cursor = 'pointer';
                    bar.onclick = () => {
                        const t = (ann.entry_type === 'activity') ? 'activity' : 'announcement';
                        const next = `/notices?type=${encodeURIComponent(t)}`;
                        if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                        else window.location.href = next;
                    };
                    bar.hidden = false;
                } catch (_) {}
            }
        };

        const NoticeCenter = {
            async open(type) {
                const safeType = (type === 'activity') ? 'activity' : 'announcement';
                const next = `/notices?type=${encodeURIComponent(safeType)}`;
                if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                else window.location.href = next;
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
                return `onboarding_v3_dismissed_session_${uid}`;
            },
            legacyDismissedKey() {
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
                    return sessionStorage.getItem(this.dismissedKey()) === '1';
                } catch (_) {
                    return this.dismissedInMemory;
                }
            },
            clearLegacyDismissFlag() {
                try {
                    localStorage.removeItem(this.legacyDismissedKey());
                } catch (_) {}
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
                    sessionStorage.setItem(this.dismissedKey(), '1');
                } catch (_) {}
                this.hideCard();
            },
            async load() {
                const card = document.getElementById('onboardingCard');
                if (!card) return;
                this.clearLegacyDismissFlag();
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
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('checkin', false);
                }
            },
            showCard() {
                const card = document.getElementById('checkinCard');
                if (!card) return;
                card.hidden = false;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('checkin', true);
                }
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
                const headerMetaEl = document.getElementById('checkinHeaderMeta');

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
                if (headerMetaEl) {
                    headerMetaEl.textContent = adminExempt ? '管理员免签到' : (already ? '今日已签到' : '显示详情');
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
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('group', false);
                }
            },
            showCard() {
                const card = document.getElementById('groupLinksCard');
                if (card) card.hidden = false;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('group', true);
                }
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

        const UtilityPanels = {
            _cards: {},
            _expandedKey: '',
            init() {
                this._cards = {
                    checkin: document.getElementById('checkinCard'),
                    group: document.getElementById('groupLinksCard'),
                    web3: document.getElementById('web3NoteCard')
                };
                const triggers = Array.from(document.querySelectorAll('[data-utility-trigger]'));
                triggers.forEach((trigger) => {
                    trigger.addEventListener('click', (ev) => {
                        ev.preventDefault();
                        ev.stopPropagation();
                        const key = trigger.getAttribute('data-utility-trigger') || '';
                        if (!key) return;
                        this.toggle(key);
                    });
                });
                this.collapseAll();
            },
            _isVisibleCard(key) {
                const card = this._cards[key];
                return !!(card && !card.hidden);
            },
            setExpanded(key, expanded) {
                const card = this._cards[key];
                if (!card || card.hidden) return false;
                if (expanded) {
                    Object.keys(this._cards).forEach((otherKey) => {
                        const other = this._cards[otherKey];
                        if (!other || other.hidden) return;
                        other.classList.toggle('is-expanded', otherKey === key);
                    });
                    this._expandedKey = key;
                    if (typeof window.__setUtilityQuickActive === 'function') window.__setUtilityQuickActive(key);
                    return true;
                }
                card.classList.remove('is-expanded');
                if (this._expandedKey === key) this._expandedKey = '';
                if (typeof window.__setUtilityQuickActive === 'function') window.__setUtilityQuickActive('');
                return true;
            },
            toggle(key) {
                const card = this._cards[key];
                if (!card || card.hidden) {
                    if ((key === 'checkin' || key === 'group') && !currentUser) Toast.info('登录后可查看详情');
                    return false;
                }
                const nextExpanded = !card.classList.contains('is-expanded');
                return this.setExpanded(key, nextExpanded);
            },
            expand(key) {
                return this.setExpanded(key, true);
            },
            collapseAll() {
                Object.values(this._cards).forEach((card) => {
                    if (!card || card.hidden) return;
                    card.classList.remove('is-expanded');
                });
                this._expandedKey = '';
                if (typeof window.__setUtilityQuickActive === 'function') window.__setUtilityQuickActive('');
            },
            onCardVisibilityChange(key, visible) {
                if (!visible) {
                    const card = this._cards[key];
                    if (card) card.classList.remove('is-expanded');
                    if (this._expandedKey === key) this._expandedKey = '';
                    if (typeof window.__setUtilityQuickActive === 'function' && !this._expandedKey) window.__setUtilityQuickActive('');
                }
            }
        };
        window.UtilityPanels = UtilityPanels;

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
                if (id === 'loginModal') {
                    if (typeof openLoginPage === 'function') openLoginPage();
                    else window.location.href = '/login?next=' + encodeURIComponent(window.location.pathname + window.location.search + window.location.hash);
                    return;
                }
                const overlay = document.getElementById(id);
                if (!overlay) return;
                const modalEl = overlay.querySelector('.modal');
                if (id === 'postDetailModal') {
                    const anchorY = (opts && Number.isFinite(opts.anchorY)) ? Number(opts.anchorY) : null;
                    let offset = 0;
                    if (anchorY !== null) {
                        const overlayStyle = window.getComputedStyle(overlay);
                        const padTop = parseFloat(overlayStyle.paddingTop || '0') || 0;
                        const viewportH = window.innerHeight || document.documentElement.clientHeight || 0;
                        const desired = anchorY - padTop - 28;
                        const maxOffset = Math.max(0, viewportH - padTop - 140);
                        offset = Math.max(0, Math.min(desired, maxOffset));
                    }
                    overlay.style.setProperty('--detail-open-offset', `${Math.round(offset)}px`);
                    if (modalEl) modalEl.style.marginTop = `${Math.round(offset)}px`;
                }
                overlay.classList.add('active');
                overlay.scrollTop = 0;
                if (modalEl) modalEl.scrollTop = 0;
                const savedScrollY = (opts && Number.isFinite(opts.savedScrollY)) ? opts.savedScrollY : null;
                if (id === 'postDetailModal' && savedScrollY !== null) {
                    const restore = () => {
                        if (window.scrollY !== savedScrollY) window.scrollTo(0, savedScrollY);
                    };
                    requestAnimationFrame(restore);
                    setTimeout(restore, 50);
                    setTimeout(restore, 150);
                }
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
                    const modalEl = overlay.querySelector('.modal');
                    if (modalEl) modalEl.style.removeProperty('margin-top');
                }
            },

            async openDetail(evtOrId, idMaybe) {
                const isEventLike = !!(evtOrId && typeof evtOrId === 'object' && typeof evtOrId.preventDefault === 'function');
                if (isEventLike) {
                    evtOrId.preventDefault();
                    evtOrId.stopPropagation();
                }
                const targetIdRaw = isEventLike ? idMaybe : evtOrId;
                const targetId = Number(targetIdRaw);
                if (!Number.isFinite(targetId) || targetId <= 0) return;
                const next = `/post/${targetId}`;
                if (typeof navigateWithTransition === 'function') navigateWithTransition(next);
                else window.location.href = next;
            }
        };

        const Interact = {
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
                const id = Number(postId);
                if (!Number.isFinite(id) || id <= 0) return null;
                return (UI.renderedPosts || []).find((p) => Number(p.id) === id) || null;
            },

            syncFeedActionState(postId) {
                const id = Number(postId);
                if (!Number.isFinite(id) || id <= 0) return;
                const post = this.findRenderedPost(id);
                if (!post) return;
                const card = document.querySelector(`.timeline-item[data-post-id="${id}"]`);
                if (!card) return;
                const likeBtn = card.querySelector('[data-feed-action="like"]');
                const bookmarkBtn = card.querySelector('[data-feed-action="bookmark"]');
                if (likeBtn) likeBtn.innerHTML = `😰 <span>${Number(post.likes_count || 0)}</span>`;
                if (bookmarkBtn) {
                    bookmarkBtn.innerHTML = post.is_bookmarked ? '★ <span>已收</span>' : '⭐ <span>收藏</span>';
                    bookmarkBtn.setAttribute('title', post.is_bookmarked ? '取消收藏' : '收藏');
                    bookmarkBtn.setAttribute('aria-label', post.is_bookmarked ? '取消收藏' : '收藏');
                }
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

            async like(id) {
                if (!currentUser) return Modal.open('loginModal');
                const res = await fetch(`${API_BASE}/posts/${id}/like`, {
                    method: 'POST',
                    headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`}
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    Toast.error(data.error || data.message || '操作失败');
                    return;
                }
                const post = this.findRenderedPost(id);
                if (post) {
                    const isLiked = String((data && data.message) || '').toLowerCase().indexOf('unlike') === -1;
                    post.likes_count = Math.max(0, Number(post.likes_count || 0) + (isLiked ? 1 : -1));
                }
                this.syncFeedActionState(id);
            },
            async bookmark(id) {
                if (!currentUser) return Modal.open('loginModal');
                const res = await fetch(`${API_BASE}/posts/${id}/bookmark`, {
                    method: 'POST',
                    headers: {'Authorization': `Bearer ${localStorage.getItem('token')}`}
                });
                const data = await parseJsonSafe(res, {});
                if (!res.ok) {
                    Toast.error(data.error || data.message || '操作失败');
                    return;
                }
                const post = this.findRenderedPost(id);
                if (post) {
                    post.is_bookmarked = String((data && data.message) || '').toLowerCase().indexOf('unbook') === -1;
                }
                this.syncFeedActionState(id);
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
