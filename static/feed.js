(function () {
    'use strict';

    window.GHFeedFactory = function GHFeedFactory(deps) {
        var API_BASE = deps.API_BASE;
        var parseJsonSafe = deps.parseJsonSafe;
        var stripHtml = deps.stripHtml;
        var escapeAttr = deps.escapeAttr;
        var prefersReducedMotionUi = deps.prefersReducedMotionUi;
        var Modal = deps.Modal;
        var getUI = deps.getUI;
        var getCurrentUser = deps.getCurrentUser;

        var feedUi = {
            expandedPostIds: new Set(),
            renderedPosts: [],
            getPostTitleText(post) {
                return ((post && post.title) ? String(post.title) : '').trim();
            },
            getPostBodyText(post) {
                return stripHtml((post && post.content) || '').trim();
            },
            shouldCollapseSummary(text) {
                return !!(text && text.length > 220);
            },
            formatSummaryHtml(text) {
                return escapeHtml(text || '').replace(/\n/g, '<br>');
            },
            renderTopComment(post) {
                var tc = post && post.top_comment;
                if (!tc || !tc.content) return '';
                var author = tc.author || {};
                var nick = escapeHtml(author.nickname || '匿名');
                var snippet = escapeHtml(String(tc.content || '').replace(/\s+/g, ' ').trim()).slice(0, 56);
                var likes = Number(tc.likes_count || 0);
                return '' +
                    '<div class="timeline-top-comment" onclick="Modal.openDetail(event, ' + post.id + ')">' +
                        '<span class="timeline-top-comment-label">热评</span>' +
                        '<span class="timeline-top-comment-text">@' + nick + ': ' + snippet + (snippet.length >= 56 ? '...' : '') + '</span>' +
                        '<span class="timeline-top-comment-like">👍 ' + likes + '</span>' +
                    '</div>';
            },
            togglePostExpand(ev, postId) {
                if (ev && typeof ev.preventDefault === 'function') ev.preventDefault();
                if (ev && typeof ev.stopPropagation === 'function') ev.stopPropagation();
                var id = Number(postId);
                if (!Number.isFinite(id)) return;
                if (this.expandedPostIds.has(id)) this.expandedPostIds.delete(id);
                else this.expandedPostIds.add(id);
                if (!Array.isArray(this.renderedPosts) || !this.renderedPosts.length) return;
                var y = window.scrollY || window.pageYOffset || 0;
                this.renderPosts(this.renderedPosts, false);
                requestAnimationFrame(function () {
                    if (window.scrollY !== y) window.scrollTo(0, y);
                });
            },
            resolveDisplayImages(post) {
                var removedLegacyCover = '/static/images/hua_cover.jpg';
                var normalize = function (val) {
                    if (typeof val !== 'string') return null;
                    var trimmed = val.trim();
                    if (!trimmed || trimmed === removedLegacyCover) return null;
                    return trimmed;
                };
                var out = [];
                var seen = new Set();
                var pushOne = function (val) {
                    var found = normalize(val);
                    if (!found || seen.has(found)) return;
                    seen.add(found);
                    out.push(found);
                };
                var html = (post && post.content) ? String(post.content) : '';
                if (html) {
                    var reg = /<img\b[^>]*\bsrc\s*=\s*["']([^"']+)["'][^>]*>/gi;
                    var match;
                    while ((match = reg.exec(html)) !== null) {
                        pushOne(match[1]);
                        if (out.length >= 9) break;
                    }
                }
                var images = post && post.images;
                if (Array.isArray(images)) {
                    images.forEach(function (it) { pushOne(it); });
                } else if (typeof images === 'string') {
                    var raw = images.trim();
                    if (raw) {
                        if (raw.startsWith('[')) {
                            try {
                                var parsed = JSON.parse(raw);
                                if (Array.isArray(parsed)) parsed.forEach(function (it) { pushOne(it); });
                            } catch (_) {}
                        } else {
                            pushOne(raw);
                        }
                    }
                }
                return out;
            },
            renderCover(imageUrl) {
                if (!imageUrl) {
                    return '<div class="post-image-wrap is-fallback"><div class="post-image-placeholder">暂无图片</div></div>';
                }
                var imgSrc = escapeAttr(imageUrl);
                return '' +
                    '<div class="post-image-wrap">' +
                        '<span class="post-image-skeleton" aria-hidden="true"></span>' +
                        '<div class="post-image-placeholder">加载中</div>' +
                        '<img src="' + imgSrc + '" class="post-image" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement.classList.add(\'has-image\');this.parentElement.classList.remove(\'is-fallback\')" onerror="this.remove();this.parentElement.classList.add(\'is-fallback\')">' +
                    '</div>';
            },
            renderImageGallery(imageUrls) {
                if (!Array.isArray(imageUrls) || !imageUrls.length) return '';
                var shown = imageUrls.slice(0, 3);
                var more = Math.max(0, imageUrls.length - shown.length);
                if (shown.length === 1) return this.renderCover(shown[0]);
                return shown.map(function (src, idx) {
                    var safe = escapeAttr(src);
                    var mask = (more > 0 && idx === shown.length - 1) ? '<span class="timeline-more-mask">+' + more + '</span>' : '';
                    return '' +
                        '<div class="timeline-thumb-wrap">' +
                            '<span class="post-image-skeleton" aria-hidden="true"></span>' +
                            '<div class="post-image-placeholder">图片</div>' +
                            '<img src="' + safe + '" class="post-image" loading="lazy" decoding="async" referrerpolicy="no-referrer" onload="this.parentElement.classList.add(\'has-image\')" onerror="this.remove();this.parentElement.classList.add(\'is-fallback\')">' +
                            mask +
                        '</div>';
                }).join('');
            },
            renderAvatar(user) {
                return '<div class="user-avatar-emoji post-avatar">' + (user.avatar || '👻') + '</div>';
            },
            equippedTitleByKey(key) { return window.equippedTitleByKey(key); },
            renderAuthorBadge(user) { return window.renderAuthorBadge(user); },
            renderPostCard(p, idx, append) {
                var reduceMotion = prefersReducedMotionUi();
                var stagger = reduceMotion ? 0 : (append ? 0 : Math.min((idx % 8) * 24, 168));
                var itemClass = append ? 'masonry-item timeline-item-wrap' : 'masonry-item is-entering timeline-item-wrap';
                var displayImages = this.resolveDisplayImages(p);
                var coverHtml = this.renderImageGallery(displayImages);
                var coverClass = displayImages.length > 1
                    ? 'timeline-cover timeline-cover-gallery count-' + Math.min(displayImages.length, 3)
                    : 'timeline-cover timeline-cover-single';
                var author = p.author || { nickname: '用户', avatar: '👻' };
                var titleText = this.getPostTitleText(p);
                var bodyText = this.getPostBodyText(p);
                var shouldCollapse = this.shouldCollapseSummary(bodyText);
                var expanded = this.expandedPostIds.has(Number(p.id));
                var summaryVisible = shouldCollapse && !expanded ? (bodyText.slice(0, 220).trimEnd() + '...') : bodyText;
                var summaryHtml = this.formatSummaryHtml(summaryVisible);
                var isWeb3 = p.post_type === 1 || p.tx_hash;
                var isPermanent = !!(p.is_permanent || p.tx_hash || p.ipfs_cid || p.is_on_chain || p.post_type === 1);
                var isSpecial = !!p.is_special_announcement;
                var badges = [
                    p.is_pinned ? '<span class="timeline-tag tag-pin">📌 置顶</span>' : '',
                    isSpecial ? '<span class="timeline-tag tag-special">📜 长公告</span>' : '',
                    isWeb3 ? '<span class="timeline-tag tag-web3">Web3</span>' : '',
                    isPermanent ? '<span class="timeline-tag tag-permanent">已永存</span>' : ''
                ].filter(Boolean).join('');
                return '' +
                    '<div class="' + itemClass + '" style="--stagger:' + stagger + 'ms;">' +
                        '<article class="timeline-item glass" data-post-id="' + Number(p.id) + '" onclick="Modal.openDetail(event, ' + p.id + ')">' +
                            '<div class="timeline-head">' +
                                '<div class="timeline-author">' +
                                    this.renderAvatar(author) +
                                    '<div class="timeline-author-meta">' +
                                        '<div class="timeline-author-line">' +
                                            '<span class="timeline-author-name">' + escapeHtml(author.nickname || '用户') + '</span>' +
                                            this.renderAuthorBadge(author) +
                                            (author.id != null ? formatUserId(author.id, author) : '') +
                                        '</div>' +
                                        '<div class="timeline-author-sub">浏览 ' + Number(p.view_count || 0) + (p.comments_count ? (' · 评论 ' + Number(p.comments_count || 0)) : '') + '</div>' +
                                    '</div>' +
                                '</div>' +
                            '</div>' +
                            (badges ? ('<div class="timeline-tags">' + badges + '</div>') : '') +
                            '<h3 class="timeline-title">' + escapeHtml(titleText || '（无标题）') + '</h3>' +
                            '<div class="timeline-body">' + (summaryHtml || '（无正文）') + '</div>' +
                            this.renderTopComment(p) +
                            (shouldCollapse ? ('<button class="timeline-expand-btn" onclick="UI.togglePostExpand(event, ' + p.id + ')">' + (expanded ? '收起正文' : '展开阅读') + '</button>') : '') +
                            (displayImages.length ? ('<div class="' + coverClass + '" onclick="Modal.openDetail(event, ' + p.id + ')">' + coverHtml + '</div>') : '') +
                            '<div class="timeline-actions">' +
                                '<button class="btn btn-ghost btn-sm timeline-action-btn timeline-action-count" data-feed-action="like" title="恐惧" aria-label="恐惧" onclick="Interact.like(' + p.id + '); event.stopPropagation();">😰 <span>' + Number(p.likes_count || 0) + '</span></button>' +
                                '<button class="btn btn-ghost btn-sm timeline-action-btn" data-feed-action="bookmark" title="' + (p.is_bookmarked ? '取消收藏' : '收藏') + '" aria-label="' + (p.is_bookmarked ? '取消收藏' : '收藏') + '" onclick="Interact.bookmark(' + p.id + '); event.stopPropagation();">' + (p.is_bookmarked ? '★ <span>已收</span>' : '⭐ <span>收藏</span>') + '</button>' +
                                '<button class="btn btn-ghost btn-sm timeline-action-btn" title="分享" aria-label="分享" data-post-id="' + Number(p.id) + '" data-title="' + escapeAttr(titleText || '') + '" onclick="Interact.share(this); event.stopPropagation();">↗ <span>分享</span></button>' +
                                '<button class="btn btn-ghost btn-sm timeline-action-btn" title="查看详情" aria-label="查看详情" onclick="Modal.openDetail(event, ' + p.id + '); event.stopPropagation();">💬 <span>详情</span></button>' +
                            '</div>' +
                        '</article>' +
                    '</div>';
            },
            renderPosts(posts, append) {
                var grid = document.getElementById('postGrid');
                if (!append) this.renderedPosts = Array.isArray(posts) ? posts.slice() : [];
                else if (Array.isArray(posts) && posts.length) this.renderedPosts = (this.renderedPosts || []).concat(posts);
                if (!grid) {
                    var loadingElMissing = document.getElementById('loadingArea');
                    if (loadingElMissing) loadingElMissing.style.display = 'none';
                    return;
                }
                var html = (posts || []).map((p, idx) => this.renderPostCard(p, idx, append)).join('');
                if (append) grid.insertAdjacentHTML('beforeend', html);
                else grid.innerHTML = html;
                Post.prepareReveal(grid, append);
                var loadingEl = document.getElementById('loadingArea');
                if (loadingEl) loadingEl.style.display = 'none';
            },
            handleNav(el, sort) {
                document.querySelectorAll('.nav-item').forEach(function (i) { i.classList.remove('active'); });
                el.classList.add('active');
                Post.load({ sort: sort });
            }
        };

        var Post = {
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
            revealObserver: null,
            hasAdvancedFilters() {
                var f = this.currentFilters || {};
                return !!((f.from_date || '').trim() || (f.to_date || '').trim() || (f.tags || '').trim() || f.permanent_only);
            },
            ensureRevealObserver() {
                if (this.revealObserver || !('IntersectionObserver' in window)) return this.revealObserver;
                this.revealObserver = new IntersectionObserver((entries) => {
                    entries.forEach((entry) => {
                        if (!entry.isIntersecting) return;
                        var el = entry.target;
                        if (!(el instanceof Element)) return;
                        el.classList.add('is-visible');
                        this.revealObserver.unobserve(el);
                    });
                }, {
                    root: null,
                    rootMargin: '120px 0px 160px 0px',
                    threshold: 0.01
                });
                return this.revealObserver;
            },
            prepareReveal(grid, append) {
                if (!grid) return;
                var enteringItems = Array.from(grid.querySelectorAll('.masonry-item.is-entering:not(.is-visible)'));
                if (!enteringItems.length) return;
                if (prefersReducedMotionUi()) {
                    enteringItems.forEach(function (item) { item.classList.add('is-visible'); });
                    return;
                }
                var observer = this.ensureRevealObserver();
                if (!observer) {
                    enteringItems.forEach(function (item) { item.classList.add('is-visible'); });
                    return;
                }
                enteringItems.forEach((item, idx) => {
                    if (!append && idx < 4) {
                        item.classList.add('is-visible');
                        return;
                    }
                    observer.observe(item);
                });
            },
            async loadPinnedGuide() {
                try {
                    var res = await fetch(API_BASE + '/posts/pinned');
                    var data = await parseJsonSafe(res, {});
                    var banner = document.getElementById('pinnedGuideBanner');
                    var titleEl = document.getElementById('pinnedGuideTitle');
                    var previewEl = document.getElementById('pinnedGuidePreview');
                    var extraEl = document.getElementById('pinnedGuideExtra');
                    var btn = document.getElementById('pinnedGuideOpenBtn');
                    var toggleBtn = document.getElementById('pinnedGuideToggleBtn');
                    if (!banner || !titleEl || !btn || !previewEl || !extraEl || !toggleBtn) return;
                    var post = data && data.post;
                    if (!res.ok || !post || !post.id) {
                        banner.hidden = true;
                        this.pinnedPostId = null;
                        return;
                    }
                    var plainText = stripHtml(post.content || '');
                    var preview = plainText.length > 70 ? (plainText.slice(0, 70) + '...') : plainText;
                    this.pinnedPostId = post.id;
                    titleEl.textContent = post.title || '站点使用指南';
                    previewEl.textContent = preview || '点击查看站点功能与使用流程。';
                    extraEl.textContent = plainText || '该帖子用于向新访客解释站点功能与运作方式。';
                    extraEl.hidden = true;
                    toggleBtn.textContent = '展开简介';
                    toggleBtn.onclick = function () {
                        var isHidden = extraEl.hidden;
                        extraEl.hidden = !isHidden;
                        toggleBtn.textContent = isHidden ? '收起简介' : '展开简介';
                    };
                    btn.onclick = function (ev) { Modal.openDetail(ev, post.id); };
                    banner.hidden = false;
                } catch (_) {}
            },
            async load(params) {
                params = params || {};
                if (this.isLoading || this.isFetching) return;
                this.isLoading = true;
                this.isFetching = true;
                var postGridEl = document.getElementById('postGrid');
                var loadingEl = document.getElementById('loadingArea');
                var UI = getUI();
                if (!postGridEl) {
                    this.isLoading = false;
                    this.isFetching = false;
                    return;
                }
                try {
                    if (params.sort || params.q !== undefined || params.filters) {
                        this.currentPage = 1;
                        postGridEl.innerHTML = '';
                        if (UI && UI.expandedPostIds) UI.expandedPostIds.clear();
                        if (UI) UI.renderedPosts = [];
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
                    var qParams = new URLSearchParams();
                    qParams.append('page', this.currentPage);
                    qParams.append('sort', this.currentSort);
                    if (this.currentQuery) qParams.append('q', this.currentQuery);
                    if (this.currentFilters.from_date) qParams.append('from_date', this.currentFilters.from_date);
                    if (this.currentFilters.to_date) qParams.append('to_date', this.currentFilters.to_date);
                    if (this.currentFilters.permanent_only) qParams.append('permanent_only', '1');
                    if (this.currentFilters.tags) qParams.append('tags', this.currentFilters.tags);
                    var headers = {};
                    var token = localStorage.getItem('token');
                    if (token) headers.Authorization = 'Bearer ' + token;
                    var endpoint = API_BASE + '/posts';
                    if (this.currentQuery || this.hasAdvancedFilters()) endpoint = API_BASE + '/search';
                    var res = await fetch(endpoint + '?' + qParams.toString(), { headers: headers });
                    var data = await parseJsonSafe(res, {});
                    if (!res.ok) {
                        var msg = (data && data.error) || (res.status >= 500 ? '服务暂时不可用，请稍后重试' : ('请求失败(' + res.status + ')'));
                        throw new Error(msg);
                    }
                    if (data.posts) {
                        if (this.currentPage === 1) {
                            postGridEl.innerHTML = '';
                            if (data.posts.length === 0) {
                                var emptyMsg = '这里一片荒芜，什么也没有...';
                                var emptyBtn = this.currentQuery ? '<button class="btn btn-ghost" onclick="Post.load()" style="margin-top:1rem;">返回全部</button>' : '';
                                if (this.currentSort === 'bookmarks') {
                                    if (!token) {
                                        emptyMsg = '请先登录后查看收藏';
                                        emptyBtn = '<button class="btn btn-primary" onclick="Modal.open(\'loginModal\')" style="margin-top:1rem;">去登录</button>';
                                    } else {
                                        emptyMsg = '暂无收藏，去首页逛逛吧';
                                        emptyBtn = '<button class="btn btn-ghost" onclick="UI.handleNav(document.querySelector(\'[data-sort=new]\'), \'new\')" style="margin-top:1rem;">看最新</button>';
                                    }
                                }
                                postGridEl.innerHTML =
                                    '<div style="grid-column: 1 / -1; text-align: center; padding: 4rem 1rem; color: var(--text-muted);">' +
                                        '<div style="font-size: 3rem; margin-bottom: 1rem;">' + (this.currentSort === 'bookmarks' ? '⭐' : '👻') + '</div>' +
                                        '<p>' + emptyMsg + '</p>' +
                                        emptyBtn +
                                    '</div>';
                            }
                        }
                        UI.renderPosts(data.posts, this.currentPage > 1);
                        if (data.pages) {
                            this.totalPages = data.pages;
                            var loadMore = document.getElementById('loadMoreArea');
                            if (loadMore) loadMore.style.display = this.currentPage < this.totalPages ? 'block' : 'none';
                        }
                    }
                } catch (e) {
                    if (this.currentPage === 1 && loadingEl) {
                        var errMsg = (e && e.message) || '网络异常或服务暂时不可用';
                        loadingEl.innerHTML = '<div style="color:var(--text-muted); padding:1.5rem;">' + errMsg + '</div><button class="btn btn-ghost" onclick="Post.load()" style="margin-top:0.5rem;">重试</button>';
                    }
                } finally {
                    this.isLoading = false;
                    this.isFetching = false;
                    if (loadingEl) loadingEl.style.display = 'none';
                }
            },
            loadMore() {
                if (this.currentPage < this.totalPages) {
                    this.currentPage += 1;
                    this.load();
                }
            },
            initAutoLoad() {
                var sentinel = document.getElementById('loadMoreArea');
                if (!sentinel || this.autoLoadObserver) return;
                this.autoLoadObserver = new IntersectionObserver((entries) => {
                    var entry = entries && entries[0];
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
                if (!getCurrentUser()) return Modal.open('loginModal');
                var content = prompt('转发附言:');
                if (content === null) return;
                var res = await fetch(API_BASE + '/posts/' + id + '/repost', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer ' + localStorage.getItem('token')
                    },
                    body: JSON.stringify({ content: content })
                });
                if (res.ok) {
                    if (window.Toast && Toast.success) Toast.success('转发成功');
                    this.load();
                } else {
                    var data = await parseJsonSafe(res, {});
                    if (window.Toast && Toast.error) Toast.error(data.error || '转发失败');
                }
            }
        };

        return {
            Post: Post,
            feedUi: feedUi
        };
    };
})();
