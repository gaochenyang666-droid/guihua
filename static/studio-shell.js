(function () {
    'use strict';

    window.GHStudioShellFactory = function GHStudioShellFactory(deps) {
        const {
            initQuill,
            bindStaticActions,
            initAuth
        } = deps;

        return {
            init() {
                initQuill();
                const c = document.getElementById('ghostFireContainer');
                if (c && !c.dataset.initialized) {
                    c.dataset.initialized = '1';
                    for (let i = 0; i < 6; i++) {
                        const d = document.createElement('div');
                        d.className = 'ghost-fire';
                        d.style.left = Math.random() * 100 + '%';
                        d.style.animationDelay = Math.random() * 5 + 's';
                        c.appendChild(d);
                    }
                }
                bindStaticActions();
                initAuth();
            }
        };
    };
})();
