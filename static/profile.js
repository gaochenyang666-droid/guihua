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
            ? '<a class="btn btn-ghost" href="/?bind_wallet=1" data-no-transition="1" style="color:var(--accent-orange); border-color:rgba(249,115,22,0.55);">绑定钱包</a>'
            : '';
        area.innerHTML = '' +
            '<div style="display:flex; gap:0.5rem; flex-wrap:wrap;">' +
                '<a class="btn btn-ghost" href="/profile?user=' + profileKey + '" data-no-transition="1">我的主页</a>' +
                bindWalletBtn +
                '<button class="btn btn-ghost" type="button" onclick="localStorage.removeItem(\'token\'); localStorage.removeItem(\'login_at\'); navigateWithTransition(\'/\')">退出</button>' +
            '</div>';
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
            '<img src="' + escapeAttr(coverUrl) + '" class="post-cover" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement.classList.add(\'has-image\')" onerror="this.remove();this.parentElement.classList.remove(\'has-image\')">' +
        '</div>';
    }

    function showProfileError(msg, showBack) {
        var backHtml = showBack ? '<p style="margin-top:1rem;"><a href="/" class="btn btn-primary">返回首页</a></p>' : '';
        var area = document.getElementById('profileArea');
        if (!area) return;
        area.innerHTML = '<div style="text-align:center; padding: 2rem; color: var(--text-secondary);"><p style="color:var(--accent-red); margin-bottom:0.5rem;">' + escapeHtml(msg) + '</p>' + backHtml + '</div>';
    }

    function renderAchievementWallBody() {
        var wall = document.getElementById('achievementsWallBody');
        if (!wall) return;
        var state = myAchievementsState;
        if (!state || !Array.isArray(state.achievements)) {
            wall.innerHTML = '<div style="color:var(--text-muted); padding:0.8rem;">暂无成就数据</div>';
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
                    ? '<button class="btn btn-ghost btn-sm" style="border-color:var(--accent-red); color:var(--accent-red);" onclick="Achievements.quickReport()">快速举报</button>'
                    : '<span style="font-size:0.78rem; color:var(--text-muted);">等级不足，无法举报</span>';
            } else if (wearable) {
                if (!unlocked) {
                    actionHtml = '<span style="font-size:0.78rem; color:var(--text-muted);">' + (legacy ? '尚未满足解锁条件' : '未达佩戴等级') + '</span>';
                } else if (!canEquip) {
                    actionHtml = '<span style="font-size:0.78rem; color:var(--text-muted);">Lv.3 解锁佩戴按钮</span>';
                } else if (achievement.equipped) {
                    actionHtml = '<button class="btn btn-primary btn-sm" onclick="Achievements.equip(\'\')">取消佩戴</button>';
                } else {
                    actionHtml = '<button class="btn btn-ghost btn-sm" onclick="Achievements.equip(\'' + escapeAttr(achievement.key) + '\')">佩戴</button>';
                }
            } else if (achievement.key === 'wearable_unlock') {
                actionHtml = unlocked
                    ? '<span style="font-size:0.78rem; color:var(--accent-green);">已解锁佩戴能力</span>'
                    : '<span style="font-size:0.78rem; color:var(--text-muted);">Lv.3 解锁</span>';
            }
            return '' +
                '<div style="padding:0.75rem; border:1px solid ' + (unlocked ? 'rgba(16,185,129,0.35)' : 'var(--border-color)') + '; border-radius:12px; background:' + (unlocked ? 'rgba(16,185,129,0.08)' : 'rgba(255,255,255,0.02)') + ';">' +
                    '<div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:0.35rem;">' +
                        '<b>' + escapeHtml(achievement.title || '') + '</b>' +
                        '<span style="font-size:0.74rem; color:' + (unlocked ? 'var(--accent-green)' : 'var(--text-muted)') + ';">' + (legacy ? '旧成就 · ' : '') + lockedText + '</span>' +
                    '</div>' +
                    '<div style="font-size:0.82rem; color:var(--text-secondary); margin-bottom:0.55rem;">' + escapeHtml(achievement.description || '') + '</div>' +
                    '<div>' + actionHtml + '</div>' +
                '</div>';
        }).join('');
        var equippedTitle = achievementTitleByKey(state.equipped_key);
        wall.innerHTML = '' +
            '<div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:0.8rem; flex-wrap:wrap;">' +
                '<h3>🏆 我的成就安装墙</h3>' +
                '<span style="font-size:0.8rem; color:var(--text-secondary);">当前佩戴：' + (equippedTitle ? '<span style="color:var(--accent-gold);">' + escapeHtml(equippedTitle) + '</span>' : '未佩戴') + '</span>' +
            '</div>' +
            '<div style="font-size:0.82rem; color:var(--text-secondary); margin-bottom:0.7rem;">当前等级：' + (isAdminInfinite ? '<span style="color:var(--accent-gold);">∞（管理员）</span>' : escapeHtml(state.level_label || ('Lv.' + state.level))) + '</div>' +
            '<div style="display:grid; gap:0.7rem;">' + cards + '</div>';
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
            area.style.display = 'none';
            area.innerHTML = '';
            return;
        }
        area.style.display = 'block';
        area.innerHTML = '加载感谢名单...';
        try {
            var qs = new URLSearchParams({ page: '1', per_page: '24' });
            if (showAmount) qs.append('show_amount', '1');
            var result = await requestJson(API_BASE + '/users/' + userId + '/tips-received?' + qs.toString(), {
                auth: !!localStorage.getItem('token')
            });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                area.innerHTML = '<div style="color:var(--text-muted);">' + escapeHtml(data.error || '该用户未公开感谢名单') + '</div>';
                return;
            }
            var items = data.items || [];
            if (!items.length) {
                area.innerHTML = '<div style="color:var(--text-muted);">暂无打赏记录</div>';
                return;
            }
            area.innerHTML = '' +
                '<div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:0.6rem;">' +
                    '<b>🙏 感谢名单</b>' +
                    '<span style="font-size:0.78rem; color:var(--text-muted);">最近 ' + items.length + ' 条</span>' +
                '</div>' +
                '<div style="display:flex; flex-wrap:wrap; gap:0.4rem;">' +
                    items.map(function (it) {
                        var nick = (it.from_user && it.from_user.nickname) || '匿名用户';
                        var amount = (typeof it.amount_usdt !== 'undefined') ? (' · ' + Number(it.amount_usdt).toFixed(2) + ' USDT') : '';
                        return '<span style="padding:0.2rem 0.45rem; border:1px solid var(--border-color); border-radius:999px; font-size:0.8rem;">' + escapeHtml(nick) + escapeHtml(amount) + '</span>';
                    }).join('') +
                '</div>';
        } catch (_) {
            area.innerHTML = '<div style="color:var(--text-muted);">加载失败</div>';
        }
    }

    function renderSeriesList(seriesList) {
        var area = document.getElementById('seriesArea');
        if (!area) return;
        var list = Array.isArray(seriesList) ? seriesList : [];
        if (!list.length) {
            area.style.display = 'none';
            area.innerHTML = '';
            return;
        }
        area.style.display = 'block';
        area.innerHTML = '' +
            '<div style="display:flex; justify-content:space-between; align-items:center; gap:0.5rem; margin-bottom:0.6rem;">' +
                '<b>📚 系列 / 合集</b>' +
                '<span style="font-size:0.78rem; color:var(--text-muted);">' + list.length + ' 个系列</span>' +
            '</div>' +
            '<div style="display:grid; gap:0.5rem;">' +
                list.map(function (series) {
                    return '<a href="/series/' + series.id + '" class="btn btn-ghost btn-sm" data-no-transition="1" style="justify-content:space-between; text-decoration:none;"><span>' + escapeHtml(series.title || '') + '</span><span style="font-size:0.74rem; color:var(--text-muted);">查看目录</span></a>';
                }).join('') +
            '</div>';
    }

    function renderProfile(user, posts, seriesList) {
        displayedPosts = Array.isArray(posts) ? posts : [];
        displayedSeries = Array.isArray(seriesList) ? seriesList : displayedSeries;
        var avatarHtml = '<div class="avatar-lg">' + (user.avatar || '👻') + '</div>';
        var walletAddress = ((user.wallet_address || user.address || '') + '').trim();
        var walletAddressBtn = walletAddress
            ? '<button type="button" class="btn btn-ghost btn-sm" style="background:rgba(16,185,129,0.1); color:#10b981; border-color:rgba(16,185,129,0.4); min-height:24px; padding:2px 8px; font-size:0.72rem;" title="点击复制打赏地址" onclick="copyWalletAddress(\'' + escapeAttr(walletAddress) + '\')">打赏地址: ' + escapeHtml(walletAddress.substring(0, 6) + '...' + walletAddress.slice(-4)) + '</button>'
            : '';
        var isMe = !!(viewingOwnProfile || sameIdentity(currentUser, user));
        var showTipThanks = !!user.show_tip_thanks;

        document.getElementById('profileArea').innerHTML = '' +
            '<div class="profile-header" style="border:none; margin:0; background:transparent;">' +
                avatarHtml +
                '<div style="flex:1;">' +
                    '<div style="display:flex; justify-content:space-between; align-items:flex-start;">' +
                        '<h1 style="margin-bottom:0.5rem; display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">' +
                            '<span>' + escapeHtml(user.nickname) + '</span>' +
                            (user.equipped_achievement_key
                                ? '<span class="honor-badge" style="border-color:rgba(16,185,129,0.5); color:var(--accent-green);">🏆 ' + escapeHtml(achievementTitleByKey(user.equipped_achievement_key)) + '</span>'
                                : (user.honor_title ? '<span class="honor-badge">🏷 ' + escapeHtml(user.honor_title) + '</span>' : '')) +
                        '</h1>' +
                        (isMe ? '<div style="display:flex; gap:0.5rem; flex-wrap:wrap;"><button class="btn btn-ghost btn-sm" onclick="Achievements.openWall()">🏆 成就墙</button><button class="btn btn-ghost btn-sm" onclick="EditProfile.open()">✏️ 编辑资料</button>' + (currentUser.username ? '<button class="btn btn-ghost btn-sm" onclick="EditProfile.openChangePassword()">🔒 修改密码</button>' : '') + '</div>' : '') +
                    '</div>' +
                    '<div style="color:var(--text-secondary); font-size:0.9rem; margin-bottom:0.5rem; display:flex; align-items:center; gap:0.5rem; flex-wrap:wrap;">' +
                        (user.username ? user.username + ' · ' : '') +
                        ((typeof user.id !== 'undefined') ? formatUserId(user.id, user) : '') +
                        walletAddressBtn +
                    '</div>' +
                    (user.bio ? '<div style="margin-bottom:1rem; font-size:0.9rem; color:var(--text-primary); background:rgba(255,255,255,0.05); padding:0.5rem; border-radius:8px;">' + escapeHtml(user.bio) + '</div>' : '') +
                    '<div style="color:var(--text-secondary); font-size:0.82rem; margin-bottom:0.8rem;">' + (user.admin_infinite_level ? '🛡️ 管理员免签到（无限等级）' : ('📅 连续签到 ' + Number(user.checkin_streak || 0) + ' 天')) + '</div>' +
                    (isMe ? '<label style="display:flex; align-items:center; gap:0.45rem; margin-bottom:0.8rem; color:var(--text-secondary); font-size:0.82rem;"><input type="checkbox" id="showTipThanksToggle" ' + (showTipThanks ? 'checked' : '') + '> 公开展示感谢名单</label>' : '') +
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
                if (post.tx_hash) parts.push('<a href="https://bscscan.com/tx/' + post.tx_hash + '" target="_blank" rel="noopener" style="color:var(--accent-purple);">⛓ 支付凭证</a>');
                if (post.ipfs_cid) parts.push('<a href="https://arweave.net/' + post.ipfs_cid + '" target="_blank" rel="noopener" style="color:var(--accent-gold);">💾 永存档案</a>');
                return parts.length ? '<div style="margin-top:0.4rem; font-size:0.75rem;">链上证据: ' + parts.join(' · ') + '</div>' : '';
            }
            postsArea.innerHTML = displayedPosts.map(function (post) {
                return '' +
                    '<div class="post-item glass" onclick="navigateWithTransition(\'/post/' + post.id + '\')">' +
                        renderPostCover(post) +
                        '<div style="flex:1;">' +
                            '<div style="font-weight:bold; font-size:1.1rem; margin-bottom:0.3rem;">' + escapeHtml(post.title) + '</div>' +
                            '<div style="color:var(--text-secondary); font-size:0.85rem; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden;">' + escapeHtml((post.content || '').replace(/<[^>]*>?/gm, '')) + '</div>' +
                            '<div style="margin-top:0.5rem; font-size:0.8rem; color:var(--text-secondary);">📅 ' + new Date(post.created_at).toLocaleDateString() + ' · 💬 ' + post.comments_count + ' · ❤️ ' + post.likes_count + '</div>' +
                            proofLink(post) +
                        '</div>' +
                    '</div>';
            }).join('');
        } else {
            postsArea.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-secondary);">暂无发布记录</div>';
        }
    }

    async function loadUserPosts(username, softFail) {
        softFail = !!softFail;
        if (username == null || username === '') {
            if (softFail) {
                var postsArea = document.getElementById('postsArea');
                if (postsArea) postsArea.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-secondary);">暂无发布记录</div>';
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
                if (res.status === 401) localStorage.removeItem('token');
                var postsAreaOnFail = document.getElementById('postsArea');
                if (softFail) {
                    if (postsAreaOnFail) postsAreaOnFail.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-secondary);">' + escapeHtml(data.error || '加载失败') + '</div>';
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
                if (postsAreaOnError) postsAreaOnError.innerHTML = '<div style="text-align:center; padding:2rem; color:var(--text-secondary);">加载帖子失败，请刷新重试</div>';
            } else {
                showProfileError('加载帖子失败', true);
            }
        }
    }

    async function loadProfile() {
        var params = new URLSearchParams(window.location.search);
        var userParam = params.get('user');
        var token = localStorage.getItem('token');

        if (token) {
            try {
                var meResult = await requestJson(API_BASE + '/user/me', { check401: false });
                if (meResult.res.ok) {
                    currentUser = meResult.data;
                } else if (meResult.res.status === 401) {
                    localStorage.removeItem('token');
                }
            } catch (e) {
                console.error('Auth check failed', e);
            }
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

    window.addEventListener('load', loadProfile);
+})();
