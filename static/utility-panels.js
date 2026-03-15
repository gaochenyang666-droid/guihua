(function () {
    'use strict';

    window.GHUtilityPanelsFactory = function GHUtilityPanelsFactory(deps) {
        var API_BASE = deps.API_BASE;
        var getCurrentUser = deps.getCurrentUser;
        var Toast = deps.Toast;
        var Modal = deps.Modal;
        var apiJson = window.apiJson;

        var Onboarding = {
            dismissedInMemory: false,
            defaultTasks() {
                return [
                    { key: 'login', title: '完成登录', done: !!getCurrentUser() },
                    { key: 'bind_wallet', title: '绑定钱包', done: false },
                    { key: 'daily_checkin', title: '完成今日签到', done: false },
                    { key: 'publish_first', title: '发布第一篇帖子', done: false },
                    { key: 'verify_archive', title: '查看永存证据', done: false },
                    { key: 'web2_bind_wallet', title: 'Web2 账号绑定钱包', done: false }
                ];
            },
            dismissedKey() {
                var user = getCurrentUser();
                var uid = user && user.id ? String(user.id) : 'guest';
                return 'onboarding_v3_dismissed_session_' + uid;
            },
            legacyDismissedKey() {
                var user = getCurrentUser();
                var uid = user && user.id ? String(user.id) : 'guest';
                return 'onboarding_v2_dismissed_' + uid;
            },
            hideCard() {
                var card = document.getElementById('onboardingCard');
                if (!card) return;
                card.hidden = true;
                card.style.display = 'none';
                card.setAttribute('aria-hidden', 'true');
            },
            showCard() {
                var card = document.getElementById('onboardingCard');
                if (!card) return;
                card.hidden = false;
                card.style.display = '';
                card.setAttribute('aria-hidden', 'false');
            },
            render(data) {
                var listEl = document.getElementById('onboardingTaskList');
                var progressEl = document.getElementById('onboardingProgress');
                var percentEl = document.getElementById('onboardingPercent');
                var ringEl = document.getElementById('onboardingRing');
                var tasks = Array.isArray(data && data.tasks) ? data.tasks : [];
                if (!tasks.length) tasks = this.defaultTasks();
                var totalRaw = Number(data && data.total);
                var doneRaw = Number(data && data.done_count);
                var total = Number.isFinite(totalRaw) && totalRaw >= 0 ? totalRaw : tasks.length;
                var doneFromTasks = tasks.reduce(function (n, t) { return n + (t && t.done ? 1 : 0); }, 0);
                var done = Number.isFinite(doneRaw) && doneRaw >= 0 ? doneRaw : doneFromTasks;
                var pct = total > 0 ? Math.round((done / total) * 100) : 0;

                if (progressEl) progressEl.textContent = done + '/' + total;
                if (percentEl) percentEl.textContent = pct + '%';
                if (ringEl) ringEl.style.setProperty('--progress', pct + '%');
                if (listEl) {
                    listEl.innerHTML = tasks.map(function (t) {
                        var isDone = !!t.done;
                        return '<div class="onboarding-task-item ' + (isDone ? 'is-done' : '') + '">' +
                            '<span class="onboarding-task-check">' + (isDone ? '✅' : '⬜️') + '</span><span>' + escapeHtml(t.title || '') + '</span>' +
                        '</div>';
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
                var btn = document.getElementById('onboardingCloseBtn');
                if (!btn || btn.dataset.bound === '1') return;
                btn.dataset.bound = '1';
                var self = this;
                var closeHandler = function (e) {
                    e.preventDefault();
                    e.stopPropagation();
                    self.dismiss();
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
                var card = document.getElementById('onboardingCard');
                if (!card) return;
                this.clearLegacyDismissFlag();
                this.bindClose();
                if (!getCurrentUser()) {
                    this.hideCard();
                    return;
                }
                if (this.isDismissed()) {
                    this.hideCard();
                    return;
                }
                this.render(null);
                try {
                    var token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    var result = await apiJson(API_BASE + '/onboarding/tasks', {
                        cache: 'no-store',
                        fallback: {}
                    });
                    var res = result.res;
                    var data = result.data;
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

        var Checkin = {
            hideCard() {
                var card = document.getElementById('checkinCard');
                if (!card) return;
                card.hidden = true;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('checkin', false);
                }
            },
            showCard() {
                var card = document.getElementById('checkinCard');
                if (!card) return;
                card.hidden = false;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('checkin', true);
                }
            },
            applyToCurrentUser(status) {
                var user = getCurrentUser();
                if (!user || !status) return;
                user.level = status.level;
                user.level_label = status.level_label || user.level_label;
                user.admin_infinite_level = !!status.admin_exempt;
                user.experience_points = status.experience_points;
                user.level_current_exp = status.level_current_exp;
                user.level_next_exp = status.level_next_exp;
                user.level_progress = status.level_progress;
                user.checkin_streak = status.streak;
            },
            render(status) {
                if (!status) {
                    this.hideCard();
                    return;
                }
                this.applyToCurrentUser(status);
                var already = !!status.already_checked;
                var adminExempt = !!status.admin_exempt;
                var streak = Number(status.streak || 0);
                var level = Number(status.level || 1);
                var levelLabel = status.level_label || ('Lv.' + Math.max(1, level));
                var exp = Number(status.experience_points || 0);
                var cur = Number(status.level_current_exp || 0);
                var next = Math.max(1, Number(status.level_next_exp || 1));
                var pct = Math.max(0, Math.min(100, Math.round((cur / next) * 100)));
                var reward = Math.max(0, Number(status.next_reward || 0));
                var bonusReward = Math.max(0, Number(status.next_bonus_reward || 0));

                var subtitleEl = document.getElementById('checkinSubtitle');
                var stateEl = document.getElementById('checkinState');
                var levelEl = document.getElementById('checkinLevel');
                var expEl = document.getElementById('checkinExp');
                var rewardEl = document.getElementById('checkinReward');
                var barEl = document.getElementById('checkinProgressBar');
                var btn = document.getElementById('checkinBtn');
                var tipEl = document.getElementById('checkinTip');
                var headerMetaEl = document.getElementById('checkinHeaderMeta');

                if (subtitleEl) subtitleEl.textContent = adminExempt ? '管理员免签到' : ('连续签到 ' + streak + ' 天');
                if (stateEl) {
                    stateEl.textContent = adminExempt ? '免签到' : (already ? '已签到' : '未签到');
                    stateEl.classList.toggle('is-done', already || adminExempt);
                }
                if (levelEl) levelEl.textContent = levelLabel;
                if (expEl) expEl.textContent = String(exp);
                if (rewardEl) rewardEl.textContent = '+' + reward;
                if (barEl) barEl.style.width = pct + '%';
                if (btn) {
                    btn.disabled = already || adminExempt;
                    btn.textContent = adminExempt ? '管理员免签到' : (already ? '今日已签到' : '立即签到');
                    btn.classList.toggle('btn-primary', !(already || adminExempt));
                }
                if (tipEl) {
                    if (adminExempt) tipEl.textContent = '管理员拥有全部签到权益（免签到）';
                    else if (bonusReward > 0) tipEl.textContent = '当前等级进度 ' + cur + '/' + next + ' · 下次连签奖励 +' + bonusReward;
                    else tipEl.textContent = '当前等级进度 ' + cur + '/' + next;
                }
                if (headerMetaEl) {
                    headerMetaEl.textContent = adminExempt ? '管理员免签到' : (already ? '今日已签到' : '显示详情');
                }

                this.showCard();
            },
            async load() {
                if (!getCurrentUser()) {
                    this.hideCard();
                    return;
                }
                try {
                    var token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    var result = await apiJson(API_BASE + '/checkin/status', {
                        cache: 'no-store',
                        fallback: {}
                    });
                    var res = result.res;
                    var data = result.data;
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
                if (!getCurrentUser()) {
                    Modal.open('loginModal');
                    return;
                }
                var btn = document.getElementById('checkinBtn');
                if (btn && btn.disabled) return;
                if (btn) {
                    btn.disabled = true;
                    btn.textContent = '签到中...';
                }
                try {
                    var result = await apiJson(API_BASE + '/checkin', {
                        method: 'POST',
                        fallback: {}
                    });
                    var res = result.res;
                    var data = result.data;
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

        var GroupLinks = {
            hideCard() {
                var card = document.getElementById('groupLinksCard');
                if (card) card.hidden = true;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('group', false);
                }
            },
            showCard() {
                var card = document.getElementById('groupLinksCard');
                if (card) card.hidden = false;
                if (window.UtilityPanels && typeof window.UtilityPanels.onCardVisibilityChange === 'function') {
                    window.UtilityPanels.onCardVisibilityChange('group', true);
                }
            },
            render(payload) {
                var listEl = document.getElementById('groupLinksList');
                var hintEl = document.getElementById('groupLinksHint');
                if (!listEl || !payload || !Array.isArray(payload.groups)) {
                    this.hideCard();
                    return;
                }
                var level = Number(payload.level || 1);
                var levelLabel = payload.level_label || ('Lv.' + Math.max(1, level));
                var adminExempt = !!payload.admin_infinite_level;
                if (hintEl) hintEl.textContent = adminExempt ? '管理员已解锁全部社群入口' : ('当前等级 ' + levelLabel + '，达标后自动解锁');
                listEl.innerHTML = payload.groups.map(function (g) {
                    var required = Number(g.required_level || 1);
                    if (g.unlocked && g.url) {
                        var safeUrl = escapeAttr(g.url);
                        return '<div class="onboarding-task-item"><span>✅</span><a href="' + safeUrl + '" target="_blank" rel="noopener" style="color:var(--accent-green); text-decoration:underline;">加入' + escapeHtml(g.title || '') + '</a></div>';
                    }
                    if (g.unlocked && !g.configured) {
                        return '<div class="onboarding-task-item"><span>🛠️</span><span>' + escapeHtml(g.title || '') + ' 链接待管理员配置</span></div>';
                    }
                    return '<div class="onboarding-task-item"><span>🔒</span><span>Lv.' + required + ' 解锁 ' + escapeHtml(g.title || '') + '</span></div>';
                }).join('');
                this.showCard();
            },
            async load() {
                if (!getCurrentUser()) {
                    this.hideCard();
                    return;
                }
                try {
                    var token = localStorage.getItem('token');
                    if (!token) {
                        this.hideCard();
                        return;
                    }
                    var result = await apiJson(API_BASE + '/group-links', {
                        cache: 'no-store',
                        fallback: {}
                    });
                    var res = result.res;
                    var data = result.data;
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

        var UtilityPanels = {
            _cards: {},
            _expandedKey: '',
            init() {
                this._cards = {
                    checkin: document.getElementById('checkinCard'),
                    group: document.getElementById('groupLinksCard'),
                    web3: document.getElementById('web3NoteCard')
                };
                var self = this;
                Array.from(document.querySelectorAll('[data-utility-trigger]')).forEach(function (trigger) {
                    trigger.addEventListener('click', function (ev) {
                        ev.preventDefault();
                        ev.stopPropagation();
                        var key = trigger.getAttribute('data-utility-trigger') || '';
                        if (!key) return;
                        self.toggle(key);
                    });
                });
                this.collapseAll();
            },
            setExpanded(key, expanded) {
                var card = this._cards[key];
                if (!card || card.hidden) return false;
                if (expanded) {
                    Object.keys(this._cards).forEach((otherKey) => {
                        var other = this._cards[otherKey];
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
                var card = this._cards[key];
                if (!card || card.hidden) {
                    if ((key === 'checkin' || key === 'group') && !getCurrentUser()) Toast.info('登录后可查看详情');
                    return false;
                }
                return this.setExpanded(key, !card.classList.contains('is-expanded'));
            },
            expand(key) {
                return this.setExpanded(key, true);
            },
            collapseAll() {
                Object.values(this._cards).forEach(function (card) {
                    if (!card || card.hidden) return;
                    card.classList.remove('is-expanded');
                });
                this._expandedKey = '';
                if (typeof window.__setUtilityQuickActive === 'function') window.__setUtilityQuickActive('');
            },
            onCardVisibilityChange(key, visible) {
                if (!visible) {
                    var card = this._cards[key];
                    if (card) card.classList.remove('is-expanded');
                    if (this._expandedKey === key) this._expandedKey = '';
                    if (typeof window.__setUtilityQuickActive === 'function' && !this._expandedKey) window.__setUtilityQuickActive('');
                }
            }
        };

        return {
            Onboarding: Onboarding,
            Checkin: Checkin,
            GroupLinks: GroupLinks,
            UtilityPanels: UtilityPanels
        };
    };
})();
