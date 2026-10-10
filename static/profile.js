(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';
    var currentUser = null;
    var displayedUser = null;
    var displayedPosts = [];
    var displayedSeries = [];
    var tempAvatar = null;
    var myAchievementsState = null;
    var viewingOwnProfile = false;
    var apiJson = window.apiJson;
    var escapeAttr = window.escapeAttr;
    var escapeHtml = window.escapeHtml;

    var ACHIEVEMENT_META = {
        report_privilege: { title: '举报权限', min_level: 2, wearable: false },
        wearable_unlock: { title: '成就佩戴权限', min_level: 3, wearable: false },
        co_create_group: { title: '共创群资格', min_level: 5, wearable: true },
        core_group: { title: '核心群资格', min_level: 10, wearable: true }
    };

    function normalizeToken(s) {
        return s == null ? '' : String(s).trim().toLowerCase();
    }

    function sameIdentity(a, b) {
        if (!a || !b) return false;
        if (a.id != null && b.id != null && String(a.id) === String(b.id)) return true;
        var aUsername = normalizeToken(a.username);
        var bUsername = normalizeToken(b.username);
        if (aUsername && bUsername && aUsername === bUsername) return true;
        var aAddress = normalizeToken(a.address || a.wallet_address);
        var bAddress = normalizeToken(b.address || b.wallet_address);
        if (aAddress && bAddress && aAddress === bAddress) return true;
        return false;
    }

    function queryIsCurrentUser(queryToken, user) {
        var q = normalizeToken(queryToken);
        if (!q || !user) return false;
        var username = normalizeToken(user.username);
        var address = normalizeToken(user.address || user.wallet_address);
        return (username && q === username) || (address && q === address);
    }

    function toastError(msg) {
        if (window.Toast && Toast.error) Toast.error(msg || '操作失败');
    }

    function toastSuccess(msg) {
        if (window.Toast && Toast.success) Toast.success(msg || '操作成功');
    }

    async function requestJson(url, opts) {
        return apiJson(url, Object.assign({ fallback: {} }, opts || {}));
    }

    function renderMyActions() {
        var area = document.getElementById('myActions');
        if (!area) return;
        if (!currentUser) {
            area.innerHTML = '<a class="btn btn-primary" href="/login?next=%2Fprofile" data-no-transition="1">登录</a>';
            return;
        }
        var profileKey = encodeURIComponent(currentUser.username || currentUser.address || currentUser.id || '');
        var bindWalletBtn = !currentUser.address
            ? '<a class="btn btn-ghost profile-bind-wallet-btn" href="/?bind_wallet=1" data-no-transition="1">绑定钱包</a>'
            : '';
        area.innerHTML = '' +
            '<div class="profile-actions-row">' +
                '<a class="btn btn-ghost" href="/profile?user=' + profileKey + '" data-no-transition="1">我的主页</a>' +
                bindWalletBtn +
                '<button class="btn btn-ghost" type="button" id="profileLogoutBtn">退出</button>' +
            '</div>';
        var logoutBtn = document.getElementById('profileLogoutBtn');
        if (logoutBtn) {
            logoutBtn.addEventListener('click', async function () {
                try { await apiJson(API_BASE + '/auth/logout', { method: 'POST', auth: false, check401: false, fallback: {} }); } catch (_) {}
                if (window.authState && window.authState.clear) window.authState.clear();
                navigateWithTransition('/');
            });
        }
    }

    function achievementTitleByKey(key) {
        if (!key) return '';
        if (myAchievementsState && Array.isArray(myAchievementsState.achievements)) {
            var found = myAchievementsState.achievements.find(function (item) {
                return item && item.key === key;
            });
            if (found && found.title) return found.title;
        }
        var meta = ACHIEVEMENT_META[key];
        return meta ? meta.title : key;
    }

    async function copyWalletAddress(address) {
        var val = (address || '').trim();
        if (!val) return;
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(val);
            } else {
                var ta = document.createElement('textarea');
                ta.value = val;
                ta.style.position = 'fixed';
                ta.style.opacity = '0';
                document.body.appendChild(ta);
                ta.focus();
                ta.select();
                document.execCommand('copy');
                document.body.removeChild(ta);
            }
            toastSuccess('打赏地址已复制');
        } catch (_) {
            toastError('复制失败，请手动复制');
        }
    }
    window.copyWalletAddress = copyWalletAddress;

    function resolvePostCoverUrl(post) {
        function normalize(val) {
            if (typeof val !== 'string') return null;
            var trimmed = val.trim();
            if (!trimmed || trimmed === '/static/images/hua_cover.jpg') return null;
            return trimmed;
        }
        var html = post && post.content ? String(post.content) : '';
        if (html) {
            var reg = /<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/i;
            var matched = html.match(reg);
            if (matched && matched[1]) {
                var fromHtml = normalize(matched[1]);
                if (fromHtml) return fromHtml;
            }
        }
        var images = post && post.images;
        if (Array.isArray(images)) {
            for (var i = 0; i < images.length; i += 1) {
                var found = normalize(images[i]);
                if (found) return found;
            }
        } else if (typeof images === 'string') {
            var raw = images.trim();
            if (raw) {
                if (raw.startsWith('[')) {
                    try {
                        var parsed = JSON.parse(raw);
                        if (Array.isArray(parsed)) {
                            for (var j = 0; j < parsed.length; j += 1) {
                                var parsedFound = normalize(parsed[j]);
                                if (parsedFound) return parsedFound;
                            }
                        }
                    } catch (_) {}
                } else {
                    var directFound = normalize(raw);
                    if (directFound) return directFound;
                }
            }
        }
        return null;
    }

    function renderPostCover(post) {
        var coverUrl = resolvePostCoverUrl(post);
        if (!coverUrl) {
            return '<div class="post-cover-wrap is-fallback"><div class="post-cover-placeholder">📝</div></div>';
        }
        return '<div class="post-cover-wrap">' +
            '<div class="post-cover-placeholder">📝</div>' +
            '<img src="' + escapeAttr(coverUrl) + '" class="post-cover js-profile-post-cover" loading="lazy" decoding="async" referrerpolicy="no-referrer">' +
        '</div>';
    }

    function wireProfileDynamicUi() {
        document.querySelectorAll('.js-profile-post-cover').forEach(function (img) {
            if (img.dataset.bound === '1') return;
            img.dataset.bound = '1';
            img.addEventListener('load', function () {
                if (img.parentElement) img.parentElement.classList.add('has-image');
            });
            img.addEventListener('error', function () {
                if (img.parentElement) img.parentElement.classList.remove('has-image');
                img.remove();
            });
        });
        document.querySelectorAll('[data-wallet-copy]').forEach(function (btn) {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', function () {
                copyWalletAddress(btn.getAttribute('data-wallet-copy') || '');
            });
        });
        document.querySelectorAll('[data-profile-action]').forEach(function (btn) {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', function () {
                var action = btn.getAttribute('data-profile-action') || '';
                if (action === 'open-wall') Achievements.openWall();
                if (action === 'edit-profile') EditProfile.open();
                if (action === 'change-password') EditProfile.openChangePassword();
            });
        });
        document.querySelectorAll('[data-achievement-action]').forEach(function (btn) {
            if (btn.dataset.bound === '1') return;
            btn.dataset.bound = '1';
            btn.addEventListener('click', function () {
                var action = btn.getAttribute('data-achievement-action') || '';
                if (action === 'quick-report') Achievements.quickReport();
                if (action === 'equip') Achievements.equip(btn.getAttribute('data-achievement-key') || '');
                if (action === 'unequip') Achievements.equip('');
            });
        });
        document.querySelectorAll('[data-profile-post-id]').forEach(function (card) {
            if (card.dataset.bound === '1') return;
            card.dataset.bound = '1';
            card.addEventListener('click', function () {
                var postId = card.getAttribute('data-profile-post-id') || '';
                if (postId) navigateWithTransition('/post/' + postId);
            });
        });
    }

    function showProfileError(msg, showBack) {
        var backHtml = showBack ? '<p class="profile-error-actions"><a href="/" class="btn btn-primary">返回首页</a></p>' : '';
        var area = document.getElementById('profileArea');
        if (!area) return;
        area.innerHTML = '<div class="state-error profile-state-card"><p class="profile-error-message">' + escapeHtml(msg) + '</p>' + backHtml + '</div>';
    }

    function renderAchievementWallBody() {
        var wall = document.getElementById('achievementsWallBody');
        if (!wall) return;
        var state = myAchievementsState;
        if (!state || !Array.isArray(state.achievements)) {
            wall.innerHTML = '<div class="state-empty profile-achievement-empty">暂无成就数据</div>';
            return;
        }
        var canEquip = !!state.can_equip;
        var isAdminInfinite = !!state.admin_infinite_level;
        var cards = state.achievements.map(function (achievement) {
            var unlocked = !!achievement.unlocked;
            var wearable = !!achievement.wearable;
            var legacy = !!achievement.legacy;
            var lockedText = unlocked ? '已解锁' : (legacy ? '未解锁' : ('Lv.' + achievement.min_level + ' 解锁'));
            var actionHtml = '';
            if (achievement.key === 'report_privilege') {
                actionHtml = unlocked
                    ? '<button class="btn btn-ghost btn-sm profile-achievement-report-btn" data-achievement-action="quick-report" type="button">快速举报</button>'
                    : '<span class="profile-achievement-note">等级不足，无法举报</span>';
            } else if (wearable) {
                if (!unlocked) {
                    actionHtml = '<span class="profile-achievement-note">' + (legacy ? '尚未满足解锁条件' : '未达佩戴等级') + '</span>';
                } else if (!canEquip) {
                    actionHtml = '<span class="profile-achievement-note">Lv.3 解锁佩戴按钮</span>';
                } else if (achievement.equipped) {
                    actionHtml = '<button class="btn btn-primary btn-sm" data-achievement-action="unequip" type="button">取消佩戴</button>';
                } else {
                    actionHtml = '<button class="btn btn-ghost btn-sm" data-achievement-action="equip" data-achievement-key="' + escapeAttr(achievement.key) + '" type="button">佩戴</button>';
                }
            } else if (achievement.key === 'wearable_unlock') {
                actionHtml = unlocked
                    ? '<span class="profile-achievement-note is-unlocked">已解锁佩戴能力</span>'
                    : '<span class="profile-achievement-note">Lv.3 解锁</span>';
            }
            return '' +
                '<div class="profile-achievement-card' + (unlocked ? ' is-unlocked' : '') + '">' +
                    '<div class="profile-achievement-header">' +
                        '<b>' + escapeHtml(achievement.title || '') + '</b>' +
                        '<span class="profile-achievement-status' + (unlocked ? ' is-unlocked' : '') + '">' + (legacy ? '旧成就 · ' : '') + lockedText + '</span>' +
                    '</div>' +
                    '<div class="profile-achievement-description">' + escapeHtml(achievement.description || '') + '</div>' +
                    '<div>' + actionHtml + '</div>' +
                '</div>';
        }).join('');
        var equippedTitle = achievementTitleByKey(state.equipped_key);
        wall.innerHTML = '' +
            '<div class="profile-achievement-wall-head">' +
                '<h3>🏆 我的成就安装墙</h3>' +
                '<span class="profile-achievement-equipped">当前佩戴：' + (equippedTitle ? '<span class="profile-achievement-equipped-title">' + escapeHtml(equippedTitle) + '</span>' : '未佩戴') + '</span>' +
            '</div>' +
            '<div class="profile-achievement-level">当前等级：' + (isAdminInfinite ? '<span class="profile-achievement-equipped-title">∞（管理员）</span>' : escapeHtml(state.level_label || ('Lv.' + state.level))) + '</div>' +
            '<div class="profile-achievement-grid">' + cards + '</div>';
        wireProfileDynamicUi();
    }

    async function loadAchievements() {
        if (!currentUser) return;
        try {
            var result = await requestJson(API_BASE + '/achievements');
            if (!result.res.ok) return;
            myAchievementsState = result.data;
            renderAchievementWallBody();
            if (displayedUser && currentUser && sameIdentity(displayedUser, currentUser)) {
                renderProfile(displayedUser, displayedPosts, displayedSeries);
            }
        } catch (_) {}
    }

    async function loadTipThanks(userId, canShow, showAmount) {
        var area = document.getElementById('tipThanksArea');
        if (!area) return;
        if (!canShow) {
            area.hidden = true;
            area.innerHTML = '';
            return;
        }
        area.hidden = false;
        area.innerHTML = '加载感谢名单...';
        try {
            var qs = new URLSearchParams({ page: '1', per_page: '24' });
            if (showAmount) qs.append('show_amount', '1');
            var result = await requestJson(API_BASE + '/users/' + userId + '/tips-received?' + qs.toString());
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                area.innerHTML = '<div class="state-error profile-inline-state">' + escapeHtml(data.error || '该用户未公开感谢名单') + '</div>';
                return;
            }
            var items = data.items || [];
            if (!items.length) {
                area.innerHTML = '<div class="state-empty profile-inline-state">暂无打赏记录</div>';
                return;
            }
            area.innerHTML = '' +
                '<div class="profile-section-head-inline">' +
                    '<b>🙏 感谢名单</b>' +
                    '<span class="profile-section-count">最近 ' + items.length + ' 条</span>' +
                '</div>' +
                '<div class="profile-pill-list">' +
                    items.map(function (it) {
                        var nick = (it.from_user && it.from_user.nickname) || '匿名用户';
                        var amount = (typeof it.amount_usdt !== 'undefined') ? (' · ' + Number(it.amount_usdt).toFixed(2) + ' USDT') : '';
                        return '<span class="profile-pill-item">' + escapeHtml(nick) + escapeHtml(amount) + '</span>';
                    }).join('') +
                '</div>';
        } catch (_) {
            area.innerHTML = '<div class="state-error profile-inline-state">加载失败</div>';
        }
    }

    function renderSeriesList(seriesList) {
        var area = document.getElementById('seriesArea');
        if (!area) return;
        var list = Array.isArray(seriesList) ? seriesList : [];
        if (!list.length) {
            area.hidden = true;
            area.innerHTML = '';
            return;
        }
        area.hidden = false;
        area.innerHTML = '' +
            '<div class="profile-section-head-inline">' +
                '<b>📚 系列 / 合集</b>' +
                '<span class="profile-section-count">' + list.length + ' 个系列</span>' +
            '</div>' +
            '<div class="profile-series-list">' +
                list.map(function (series) {
                    return '<a href="/series/' + series.id + '" class="btn btn-ghost btn-sm profile-series-link" data-no-transition="1"><span>' + escapeHtml(series.title || '') + '</span><span class="profile-series-link-meta">查看目录</span></a>';
                }).join('') +
            '</div>';
    }

    function renderProfile(user, posts, seriesList) {
        displayedPosts = Array.isArray(posts) ? posts : [];
        displayedSeries = Array.isArray(seriesList) ? seriesList : displayedSeries;
        var avatarHtml = '<div class="avatar-lg">' + (user.avatar || '👻') + '</div>';
        var walletAddress = ((user.wallet_address || user.address || '') + '').trim();
        var walletAddressBtn = walletAddress
            ? '<button type="button" class="btn btn-ghost btn-sm profile-wallet-copy-btn" title="点击复制打赏地址" data-wallet-copy="' + escapeAttr(walletAddress) + '">打赏地址: ' + escapeHtml(walletAddress.substring(0, 6) + '...' + walletAddress.slice(-4)) + '</button>'
            : '';
        var isMe = !!(viewingOwnProfile || sameIdentity(currentUser, user));
        var showTipThanks = !!user.show_tip_thanks;

        document.getElementById('profileArea').innerHTML = '' +
            '<div class="profile-header profile-header-shell">' +
                avatarHtml +
                '<div class="profile-main-col">' +
                    '<div class="profile-header-topline">' +
                        '<h1 class="profile-title-row">' +
                            '<span>' + escapeHtml(user.nickname) + '</span>' +
                            (user.equipped_achievement_key
                                ? '<span class="honor-badge honor-badge-achievement">🏆 ' + escapeHtml(achievementTitleByKey(user.equipped_achievement_key)) + '</span>'
                                : (user.honor_title ? '<span class="honor-badge">🏷 ' + escapeHtml(user.honor_title) + '</span>' : '')) +
                        '</h1>' +
                        (isMe ? '<div class="profile-header-actions"><button class="btn btn-ghost btn-sm" data-profile-action="open-wall" type="button">🏆 成就墙</button><button class="btn btn-ghost btn-sm" data-profile-action="edit-profile" type="button">✏️ 编辑资料</button>' + (currentUser.username ? '<button class="btn btn-ghost btn-sm" data-profile-action="change-password" type="button">🔒 修改密码</button>' : '') + '</div>' : '') +
                    '</div>' +
                    '<div class="profile-meta-row">' +
                        (user.username ? user.username + ' · ' : '') +
                        ((typeof user.id !== 'undefined') ? formatUserId(user.id, user) : '') +
                        walletAddressBtn +
                    '</div>' +
                    (user.bio ? '<div class="profile-bio-card">' + escapeHtml(user.bio) + '</div>' : '') +
                    '<div class="profile-streak-note">' + (user.admin_infinite_level ? '🛡️ 管理员免签到（无限等级）' : ('📅 连续签到 ' + Number(user.checkin_streak || 0) + ' 天')) + '</div>' +
                    (isMe ? '<label class="profile-tip-toggle"><input type="checkbox" id="showTipThanksToggle" ' + (showTipThanks ? 'checked' : '') + '> 公开展示感谢名单</label>' : '') +
                    '<div class="stats">' +
                        '<div class="stat-item"><div class="stat-val">' + (user.posts_count || posts.length) + '</div><div class="stat-label">发帖</div></div>' +
                        '<div class="stat-item"><div class="stat-val">' + (user.likes_count || 0) + '</div><div class="stat-label">获赞</div></div>' +
                        '<div class="stat-item"><div class="stat-val">' + escapeHtml(user.level_label || ('Lv.' + Math.max(1, Number(user.level || 1)))) + '</div><div class="stat-label">等级</div></div>' +
                        '<div class="stat-item"><div class="stat-val">' + Number(user.experience_points || 0) + '</div><div class="stat-label">经验</div></div>' +
                    '</div>' +
                '</div>' +
            '</div>';

        if (isMe) {
            var toggle = document.getElementById('showTipThanksToggle');
            if (toggle) {
                toggle.onchange = async function () {
                    try {
                        var result = await requestJson(API_BASE + '/user/settings', {
                            method: 'PUT',
                            body: { show_tip_thanks: !!toggle.checked }
                        });
                        var res = result.res;
                        var data = result.data;
                        if (!res.ok) {
                            toastError(data.error || '保存失败');
                            toggle.checked = !toggle.checked;
                            return;
                        }
                        if (currentUser) currentUser.show_tip_thanks = !!toggle.checked;
                        if (displayedUser) displayedUser.show_tip_thanks = !!toggle.checked;
                        loadTipThanks(user.id, true, true);
                    } catch (_) {
                        toastError('网络错误');
                        toggle.checked = !toggle.checked;
                    }
                };
            }
        }

        loadTipThanks(user.id, isMe || showTipThanks, isMe);
        renderSeriesList(displayedSeries);
        var postsArea = document.getElementById('postsArea');
        if (!postsArea) return;
        if (displayedPosts && displayedPosts.length > 0) {
            function proofLink(post) {
                var parts = [];
                if (post.tx_hash) parts.push('<a href="https://bscscan.com/tx/' + post.tx_hash + '" target="_blank" rel="noopener" class="profile-proof-link">⛓ 支付凭证</a>');
                if (post.ipfs_cid) parts.push('<a href="https://arweave.net/' + post.ipfs_cid + '" target="_blank" rel="noopener" class="profile-proof-link is-archive">💾 永存档案</a>');
                return parts.length ? '<div class="profile-proof-links">链上证据: ' + parts.join(' · ') + '</div>' : '';
            }
            postsArea.innerHTML = displayedPosts.map(function (post) {
                return '' +
                    '<div class="post-item glass" data-profile-post-id="' + post.id + '">' +
                        renderPostCover(post) +
                        '<div class="profile-post-body">' +
                            '<div class="profile-post-title">' + escapeHtml(post.title) + '</div>' +
                            '<div class="profile-post-excerpt">' + escapeHtml((post.content || '').replace(/<[^>]*>?/gm, '')) + '</div>' +
                            '<div class="profile-post-meta">📅 ' + new Date(post.created_at).toLocaleDateString() + ' · 💬 ' + post.comments_count + ' · ❤️ ' + post.likes_count + '</div>' +
                            proofLink(post) +
                        '</div>' +
                    '</div>';
            }).join('');
            wireProfileDynamicUi();
        } else {
            postsArea.innerHTML = '<div class="state-empty profile-state-card">暂无发布记录</div>';
        }
    }

    function bindProfileModals() {
        var editModal = document.getElementById('editProfileModal');
        if (editModal) {
            editModal.addEventListener('click', function (event) {
                if (event.target === editModal) EditProfile.close();
            });
        }
        var changePasswordModal = document.getElementById('changePasswordModal');
        if (changePasswordModal) {
            changePasswordModal.addEventListener('click', function (event) {
                if (event.target === changePasswordModal) EditProfile.closeChangePassword();
            });
        }
        var achievementsModal = document.getElementById('achievementsModal');
        if (achievementsModal) {
            achievementsModal.addEventListener('click', function (event) {
                if (event.target === achievementsModal) Achievements.closeWall();
            });
        }
        var bindClick = function (id, handler) {
            var node = document.getElementById(id);
            if (node) node.addEventListener('click', handler);
        };
        bindClick('editProfileCloseBtn', function () { EditProfile.close(); });
        bindClick('editProfileRandomAvatarBtn', function () { EditProfile.randomizeAvatar(); });
        bindClick('editProfileSaveBtn', function () { EditProfile.save(); });
        bindClick('changePasswordCloseBtn', function () { EditProfile.closeChangePassword(); });
        bindClick('changePasswordSubmitBtn', function () { EditProfile.submitChangePassword(); });
        bindClick('achievementsCloseBtn', function () { Achievements.closeWall(); });
    }

    async function loadUserPosts(username, softFail) {
        softFail = !!softFail;
        if (username == null || username === '') {
            if (softFail) {
                var postsArea = document.getElementById('postsArea');
                if (postsArea) postsArea.innerHTML = '<div class="state-empty profile-state-card">暂无发布记录</div>';
                return;
            }
            showProfileError('缺少用户标识', true);
            return;
        }
        try {
            var result = await requestJson(API_BASE + '/users/' + encodeURIComponent(username), {
                auth: false
            });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                if (softFail && currentUser) {
                    var fallbackKey = currentUser.username || currentUser.address || currentUser.id;
                    if (fallbackKey && String(fallbackKey) !== String(username)) {
                        return loadUserPosts(fallbackKey, false);
                    }
                }
                if (res.status === 401 && window.authState && window.authState.clear) window.authState.clear();
                var postsAreaOnFail = document.getElementById('postsArea');
                if (softFail) {
                    if (postsAreaOnFail) postsAreaOnFail.innerHTML = '<div class="state-error profile-state-card">' + escapeHtml(data.error || '加载失败') + '</div>';
                } else {
                    showProfileError(data.error || '用户不存在或已注销', true);
                }
                return;
            }
            if (data.user) {
                displayedUser = data.user;
                if (currentUser && sameIdentity(currentUser, data.user)) viewingOwnProfile = true;
                renderProfile(data.user, data.posts || [], data.series || []);
                if (currentUser && sameIdentity(currentUser, data.user)) loadAchievements();
            }
        } catch (_) {
            var postsAreaOnError = document.getElementById('postsArea');
            if (softFail) {
                if (postsAreaOnError) postsAreaOnError.innerHTML = '<div class="state-error profile-state-card">加载帖子失败，请刷新重试</div>';
            } else {
                showProfileError('加载帖子失败', true);
            }
        }
    }

    async function loadProfile() {
        var params = new URLSearchParams(window.location.search);
        var userParam = params.get('user');
        try {
            var meResult = await requestJson(API_BASE + '/user/me', { check401: false });
            if (meResult.res.ok) {
                currentUser = meResult.data;
                if (window.authState && window.authState.markLoggedIn) window.authState.markLoggedIn();
            } else if (meResult.res.status === 401 && window.authState && window.authState.clear) {
                window.authState.clear();
            }
        } catch (e) {
            console.error('Auth check failed', e);
        }
        renderMyActions();

        if (!userParam) {
            if (!currentUser) {
                if (typeof openLoginPage === 'function') openLoginPage('/profile');
                else navigateWithTransition('/login?next=%2Fprofile');
                return;
            }
            viewingOwnProfile = true;
            displayedUser = currentUser;
            renderProfile(currentUser, [], []);
            loadAchievements();
            loadUserPosts(currentUser.username || currentUser.address || currentUser.id, true);
            return;
        }

        viewingOwnProfile = queryIsCurrentUser(userParam, currentUser);
        try {
            var result = await requestJson(API_BASE + '/users/' + encodeURIComponent(userParam), { auth: false });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                showProfileError(data.error || '用户不存在或已注销', true);
                return;
            }
            displayedUser = data.user;
            if (currentUser && sameIdentity(currentUser, data.user)) viewingOwnProfile = true;
            renderProfile(data.user, data.posts, data.series || []);
            if (currentUser && sameIdentity(currentUser, data.user)) loadAchievements();
        } catch (e) {
            showProfileError((e && e.message) || '加载失败', true);
        }
    }

    var Achievements = {
        openWall: function () {
            var modal = document.getElementById('achievementsModal');
            if (!modal) return;
            modal.classList.add('active');
            var wallBody = document.getElementById('achievementsWallBody');
            if (wallBody) wallBody.scrollTop = 0;
            renderAchievementWallBody();
            if (!myAchievementsState) loadAchievements();
        },
        closeWall: function () {
            var modal = document.getElementById('achievementsModal');
            if (!modal) return;
            modal.classList.remove('active');
        },
        equip: async function (key) {
            if (!currentUser) return;
            try {
                var result = await requestJson(API_BASE + '/achievements/equip', {
                    method: 'POST',
                    body: { key: key || '' }
                });
                var res = result.res;
                var data = result.data;
                if (!res.ok) {
                    toastError(data.error || '操作失败');
                    return;
                }
                myAchievementsState = data.status || null;
                if (myAchievementsState && myAchievementsState.equipped_key !== undefined) {
                    currentUser.equipped_achievement_key = myAchievementsState.equipped_key || null;
                    if (displayedUser && sameIdentity(displayedUser, currentUser)) {
                        displayedUser.equipped_achievement_key = currentUser.equipped_achievement_key;
                    }
                }
                if (displayedUser && sameIdentity(displayedUser, currentUser)) {
                    renderProfile(displayedUser, displayedPosts, displayedSeries);
                }
                renderAchievementWallBody();
                toastSuccess(data.message || '佩戴状态已更新');
            } catch (_) {
                toastError('网络错误');
            }
        },
        quickReport: async function () {
            if (!currentUser) return;
            var reason = prompt('可选：补充举报说明（最多 460 字）') || '';
            try {
                var result = await requestJson(API_BASE + '/reports/priority', {
                    method: 'POST',
                    body: { reason: reason.trim() }
                });
                var res = result.res;
                var data = result.data;
                if (!res.ok) {
                    toastError(data.error || '提交失败');
                    return;
                }
                toastSuccess(data.message || '已提交举报');
            } catch (_) {
                toastError('网络错误');
            }
        }
    };
    window.Achievements = Achievements;

    var EditProfile = {
        open: function () {
            if (!currentUser) return;
            document.getElementById('editNickname').value = currentUser.nickname;
            document.getElementById('editBio').value = currentUser.bio || '';
            var avatarEl = document.getElementById('previewAvatar');
            avatarEl.innerHTML = currentUser.avatar || '👻';
            document.getElementById('editProfileModal').classList.add('active');
        },
        close: function () {
            document.getElementById('editProfileModal').classList.remove('active');
        },
        randomizeAvatar: function () {
            var emojis = ['👻', '💀', '👽', '👾', '🤖', '🎃', '🧛', '🧟', '🧞', '🧝', '🧙', '🧚', '🧜', '👼', '👿', '👺', '👹', '🤡', '💩', '🦄'];
            var randomEmoji = emojis[Math.floor(Math.random() * emojis.length)];
            document.getElementById('previewAvatar').textContent = randomEmoji;
            tempAvatar = true;
        },
        save: async function () {
            var nickname = document.getElementById('editNickname').value;
            var bio = document.getElementById('editBio').value;
            var avatar = document.getElementById('previewAvatar').textContent;
            try {
                var result = await requestJson(API_BASE + '/user/me', {
                    method: 'PUT',
                    body: { nickname: nickname, bio: bio, avatar: avatar }
                });
                if (result.res.ok) {
                    currentUser = result.data.user;
                    displayedUser = currentUser;
                    viewingOwnProfile = true;
                    renderMyActions();
                    renderProfile(currentUser, displayedPosts, displayedSeries);
                    loadUserPosts(currentUser.username || currentUser.address || currentUser.id, true);
                    this.close();
                    tempAvatar = false;
                } else {
                    toastError('更新失败');
                }
            } catch (e) {
                console.error(e);
                toastError('网络错误');
            }
        },
        openChangePassword: function () {
            document.getElementById('cpOldPasswordIn').value = '';
            document.getElementById('cpNewPasswordIn').value = '';
            document.getElementById('cpConfirmPasswordIn').value = '';
            document.getElementById('changePasswordModal').classList.add('active');
        },
        closeChangePassword: function () {
            document.getElementById('changePasswordModal').classList.remove('active');
        },
        submitChangePassword: async function () {
            var oldP = document.getElementById('cpOldPasswordIn').value;
            var newP = document.getElementById('cpNewPasswordIn').value;
            var confirmP = document.getElementById('cpConfirmPasswordIn').value;
            if (!oldP || !newP) {
                toastError('请填写当前密码和新密码');
                return;
            }
            if (newP !== confirmP) {
                toastError('两次新密码不一致');
                return;
            }
            if (newP.length < 6) {
                toastError('新密码至少6位');
                return;
            }
            try {
                var result = await requestJson(API_BASE + '/user/password', {
                    method: 'PUT',
                    body: { old_password: oldP, new_password: newP }
                });
                var res = result.res;
                var data = result.data;
                if (res.ok) {
                    toastSuccess(data.message || '密码已修改');
                    this.closeChangePassword();
                } else {
                    toastError(data.error || '修改失败');
                }
            } catch (_) {
                toastError('网络错误');
            }
        }
    };
    window.EditProfile = EditProfile;

    window.addEventListener('load', function () {
        bindProfileModals();
        loadProfile();
    });
})();
