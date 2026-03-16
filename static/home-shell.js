(function () {
    'use strict';

    window.GHHomeShellFactory = function GHHomeShellFactory(deps) {
        var Auth = deps.Auth;
        var Post = deps.Post;
        var UtilityPanels = deps.UtilityPanels;
        var Onboarding = deps.Onboarding;
        var debounce = deps.debounce;

        return {
            init() {
                Onboarding.bindClose();

                var c = document.getElementById('ghostFireContainer');
                var isMobile = window.innerWidth < 768;
                var reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
                var lowPerfDevice = (navigator.hardwareConcurrency && navigator.hardwareConcurrency <= 4)
                    || (typeof navigator.deviceMemory !== 'undefined' && navigator.deviceMemory <= 4);
                if (reduceMotion || lowPerfDevice) document.body.classList.add('reduce-motion');

                var count = (reduceMotion || lowPerfDevice) ? 0 : (isMobile ? 3 : 6);
                if (c && count > 0) {
                    for (var i = 0; i < count; i++) {
                        var d = document.createElement('div');
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

                var postId = new URLSearchParams(window.location.search).get('post');
                if (postId && /^\d+$/.test(postId)) {
                    window.location.replace('/post/' + parseInt(postId, 10));
                    return;
                }

                var loginForm = document.getElementById('loginForm');
                if (loginForm) {
                    loginForm.onsubmit = function (e) {
                        e.preventDefault();
                        var un = document.getElementById('loginUsername');
                        var pw = document.getElementById('loginPassword');
                        if (un && pw) Auth.loginWeb2(un.value, pw.value);
                    };
                }

                this.bindNavbar();
                this.bindUtilityPanels();
                this.bindSearch();

                var logoutBtn = document.getElementById('logoutBtn');
                if (logoutBtn) logoutBtn.onclick = function () { Auth.logout(); };
            },

            bindNavbar() {
                var navbarEl = document.getElementById('mainNavbar');
                var mobileNavToggleBtn = document.getElementById('mobileNavToggleBtn');
                var desktopNavToggleBtn = document.getElementById('desktopNavToggleBtn');
                var mobileNavPanel = document.getElementById('mobileNavPanel');
                var isMobileNav = function () { return window.matchMedia('(max-width: 768px)').matches; };
                var isDesktopNav = function () { return window.matchMedia('(min-width: 1024px)').matches; };
                var closeMobileNav = function () {
                    if (!navbarEl) return;
                    navbarEl.classList.remove('mobile-nav-open');
                    if (mobileNavToggleBtn) mobileNavToggleBtn.setAttribute('aria-expanded', 'false');
                };
                var openMobileNav = function () {
                    if (!navbarEl) return;
                    navbarEl.classList.add('mobile-nav-open');
                    if (mobileNavToggleBtn) mobileNavToggleBtn.setAttribute('aria-expanded', 'true');
                };
                var closeDesktopNav = function () {
                    if (!navbarEl) return;
                    navbarEl.classList.remove('desktop-nav-open');
                    if (desktopNavToggleBtn) desktopNavToggleBtn.setAttribute('aria-expanded', 'false');
                };
                var openDesktopNav = function () {
                    if (!navbarEl) return;
                    navbarEl.classList.add('desktop-nav-open');
                    if (desktopNavToggleBtn) desktopNavToggleBtn.setAttribute('aria-expanded', 'true');
                };
                if (!(navbarEl && mobileNavPanel)) return;

                if (mobileNavToggleBtn) {
                    mobileNavToggleBtn.onclick = function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        if (!isMobileNav()) return;
                        if (navbarEl.classList.contains('mobile-nav-open')) closeMobileNav();
                        else openMobileNav();
                    };
                }
                if (desktopNavToggleBtn) {
                    desktopNavToggleBtn.onclick = function (e) {
                        e.preventDefault();
                        e.stopPropagation();
                        if (!isDesktopNav()) return;
                        if (navbarEl.classList.contains('desktop-nav-open')) closeDesktopNav();
                        else openDesktopNav();
                    };
                }
                mobileNavPanel.addEventListener('click', function (e) {
                    if (!isMobileNav()) return;
                    var target = e.target;
                    if (!(target instanceof Element)) return;
                    if (target.closest('.search-container') || target.closest('#searchAdvancedBar')) return;
                    if (target.closest('button, a')) closeMobileNav();
                });
                document.addEventListener('click', function (e) {
                    if (isMobileNav()) {
                        if (!navbarEl.contains(e.target)) closeMobileNav();
                        return;
                    }
                    if (isDesktopNav() && !navbarEl.contains(e.target)) closeDesktopNav();
                });
                document.addEventListener('keydown', function (e) {
                    if (e.key === 'Escape') closeMobileNav();
                    if (e.key === 'Escape') closeDesktopNav();
                });
                var handleNavbarResize = debounce(function () {
                    if (!isMobileNav()) closeMobileNav();
                    if (!isDesktopNav()) closeDesktopNav();
                }, 180);
                window.addEventListener('resize', handleNavbarResize, { passive: true });
            },

            bindUtilityPanels() {
                var mobileUtilityToggleBtn = document.getElementById('mobileUtilityToggleBtn');
                var mobileUtilityStack = document.getElementById('mobileUtilityStack');
                var mobileUtilityHost = document.getElementById('mobileUtilityHost');
                var mobileUtilityMount = document.getElementById('mobileUtilityMount');
                var leftSidebarEl = document.querySelector('.sidebar-left');
                var rightSidebarEl = document.getElementById('rightSidebar');
                var mobileUtilityOpen = !window.matchMedia('(max-width: 768px)').matches;

                UtilityPanels.init();

                var relocateMobileUtility = function () {
                    if (!mobileUtilityHost) return;
                    var isMobileView = window.matchMedia('(max-width: 768px)').matches;
                    if (!isMobileView) {
                        if (rightSidebarEl && mobileUtilityHost.parentElement !== rightSidebarEl) {
                            rightSidebarEl.appendChild(mobileUtilityHost);
                        }
                        return;
                    }
                    var targetParent = mobileUtilityMount || leftSidebarEl;
                    if (!targetParent) return;
                    if (mobileUtilityHost.parentElement !== targetParent) {
                        targetParent.appendChild(mobileUtilityHost);
                    }
                };

                var applyMobileUtilityState = function () {
                    if (!mobileUtilityStack) return;
                    var isMobileView = window.matchMedia('(max-width: 768px)').matches;
                    if (!isMobileView) {
                        mobileUtilityStack.classList.add('is-open');
                        if (mobileUtilityToggleBtn) mobileUtilityToggleBtn.setAttribute('aria-expanded', 'true');
                        return;
                    }
                    if (mobileUtilityToggleBtn) {
                        mobileUtilityStack.classList.toggle('is-open', mobileUtilityOpen);
                        mobileUtilityToggleBtn.setAttribute('aria-expanded', String(!!mobileUtilityOpen));
                        if (!mobileUtilityOpen) {
                            UtilityPanels.collapseAll();
                        }
                    } else {
                        mobileUtilityOpen = true;
                        mobileUtilityStack.classList.add('is-open');
                    }
                };

                if (mobileUtilityToggleBtn && mobileUtilityStack) {
                    mobileUtilityToggleBtn.onclick = function () {
                        mobileUtilityOpen = !mobileUtilityOpen;
                        if (mobileUtilityOpen) UtilityPanels.collapseAll();
                        applyMobileUtilityState();
                    };
                }
                if (mobileUtilityStack && mobileUtilityHost) {
                    var syncMobileUtility = function () {
                        relocateMobileUtility();
                        applyMobileUtilityState();
                    };
                    syncMobileUtility();
                    window.addEventListener('resize', debounce(syncMobileUtility, 160), { passive: true });
                }
            },

            bindSearch() {
                var searchInput = document.getElementById('searchInput');
                var searchTimeout;
                if (searchInput) {
                    searchInput.addEventListener('input', function (e) {
                        clearTimeout(searchTimeout);
                        searchTimeout = setTimeout(function () {
                            var q = e.target.value.trim();
                            if (q) Post.load({ q: q });
                            else Post.load({ q: '' });
                        }, 300);
                    });
                }

                var applyFilterBtn = document.getElementById('searchFilterApplyBtn');
                var resetFilterBtn = document.getElementById('searchFilterResetBtn');
                var searchAdvancedBar = document.getElementById('searchAdvancedBar');
                var searchContainer = document.getElementById('searchContainer');
                var searchToggleBtn = document.getElementById('searchToggleBtn');
                var hasAdvancedValues = function () {
                    var from = (document.getElementById('searchFromDate') || {}).value || '';
                    var to = (document.getElementById('searchToDate') || {}).value || '';
                    var tags = (document.getElementById('searchTags') || {}).value || '';
                    var permanent = !!((document.getElementById('searchPermanentOnly') || {}).checked);
                    return !!(from || to || tags.trim() || permanent);
                };
                var openAdvanced = function () {
                    if (!searchAdvancedBar) return;
                    searchAdvancedBar.classList.add('is-open');
                };
                var closeAdvanced = function (force) {
                    if (!searchAdvancedBar) return;
                    if (!force && hasAdvancedValues()) return;
                    searchAdvancedBar.classList.remove('is-open');
                };
                if (applyFilterBtn) {
                    applyFilterBtn.onclick = function () {
                        var filters = {
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
                    resetFilterBtn.onclick = function () {
                        var fromEl = document.getElementById('searchFromDate');
                        var toEl = document.getElementById('searchToDate');
                        var perEl = document.getElementById('searchPermanentOnly');
                        var tagsEl = document.getElementById('searchTags');
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
                    searchToggleBtn.onclick = function () {
                        if (searchAdvancedBar && searchAdvancedBar.classList.contains('is-open')) {
                            closeAdvanced(true);
                        } else {
                            openAdvanced();
                            if (searchInput) searchInput.focus();
                        }
                    };
                }
                document.addEventListener('click', function (e) {
                    if (!searchContainer || !searchAdvancedBar) return;
                    if (!searchAdvancedBar.classList.contains('is-open')) return;
                    if (searchContainer.contains(e.target)) return;
                    closeAdvanced(true);
                });
                document.addEventListener('keydown', function (e) {
                    if (e.key === 'Escape') closeAdvanced(true);
                });
                if (searchInput) {
                    searchInput.addEventListener('keyup', function (e) {
                        if (e.key === 'Enter') {
                            searchInput.blur();
                            closeAdvanced(true);
                        }
                    });
                    searchInput.addEventListener('search', function () {
                        searchInput.blur();
                        closeAdvanced(true);
                    });
                }
                var handleWindowScroll = function () {
                    if (searchInput && document.activeElement === searchInput) searchInput.blur();
                    closeAdvanced(true);
                };
                window.addEventListener('scroll', handleWindowScroll, { passive: true });
            }
        };
    };
})();
