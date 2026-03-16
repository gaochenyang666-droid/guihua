(function () {
    'use strict';

    window.GHPostLightboxFactory = function () {
        function createState() {
            return {
                items: [],
                index: 0
            };
        }

        function ensureOverlay(handlers) {
            var existing = document.getElementById('postImageLightbox');
            if (existing) return existing;
            var overlay = document.createElement('div');
            overlay.id = 'postImageLightbox';
            overlay.className = 'post-image-lightbox';
            overlay.hidden = true;
            overlay.innerHTML = '' +
                '<button class="post-image-lightbox-close" type="button" aria-label="关闭看图" data-action="close-lightbox">✕</button>' +
                '<button class="post-image-lightbox-nav prev" type="button" aria-label="上一张" data-action="prev-lightbox">‹</button>' +
                '<div class="post-image-lightbox-stage">' +
                    '<img class="post-image-lightbox-img" alt="帖子图片预览">' +
                    '<div class="post-image-lightbox-meta" id="postImageLightboxMeta"></div>' +
                '</div>' +
                '<button class="post-image-lightbox-nav next" type="button" aria-label="下一张" data-action="next-lightbox">›</button>';
            document.body.appendChild(overlay);
            overlay.addEventListener('click', function (evt) {
                if (evt.target === overlay && handlers && handlers.close) handlers.close();
            });
            Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="close-lightbox"]'), function (btn) {
                btn.addEventListener('click', function () {
                    if (handlers && handlers.close) handlers.close();
                });
            });
            Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="prev-lightbox"]'), function (btn) {
                btn.addEventListener('click', function (evt) {
                    evt.stopPropagation();
                    if (handlers && handlers.shift) handlers.shift(-1);
                });
            });
            Array.prototype.forEach.call(overlay.querySelectorAll('[data-action="next-lightbox"]'), function (btn) {
                btn.addEventListener('click', function (evt) {
                    evt.stopPropagation();
                    if (handlers && handlers.shift) handlers.shift(1);
                });
            });
            return overlay;
        }

        function render(state) {
            var overlay = document.getElementById('postImageLightbox');
            if (!overlay || !state.items.length) return;
            var img = overlay.querySelector('.post-image-lightbox-img');
            var meta = document.getElementById('postImageLightboxMeta');
            var prevBtn = overlay.querySelector('[data-action="prev-lightbox"]');
            var nextBtn = overlay.querySelector('[data-action="next-lightbox"]');
            var item = state.items[state.index] || {};
            if (img) {
                img.src = item.src || '';
                img.alt = item.alt || '帖子图片预览';
            }
            if (meta) meta.textContent = state.items.length > 1 ? ('第 ' + (state.index + 1) + ' / ' + state.items.length + ' 张') : '点击空白处关闭';
            if (prevBtn) prevBtn.hidden = state.items.length <= 1;
            if (nextBtn) nextBtn.hidden = state.items.length <= 1;
        }

        function open(state, index) {
            var overlay = ensureOverlay({
                close: function () { close(); },
                shift: function (delta) { shift(state, delta); }
            });
            if (!overlay || !state.items.length) return;
            state.index = Math.max(0, Math.min(Number(index) || 0, state.items.length - 1));
            render(state);
            overlay.hidden = false;
            document.body.classList.add('lightbox-open');
        }

        function close() {
            var overlay = document.getElementById('postImageLightbox');
            if (!overlay) return;
            overlay.hidden = true;
            document.body.classList.remove('lightbox-open');
        }

        function shift(state, delta) {
            if (!state.items.length) return;
            state.index = (state.index + delta + state.items.length) % state.items.length;
            render(state);
        }

        function bindContentImages(body, state) {
            if (!body) return;
            var contentImages = body.querySelectorAll('.post-detail-content img');
            state.items = [];
            Array.prototype.forEach.call(contentImages, function (im, idx) {
                im.setAttribute('referrerpolicy', 'no-referrer');
                im.loading = 'lazy';
                im.decoding = 'async';
                im.classList.add('post-detail-image');
                im.setAttribute('data-lightbox-index', String(idx));
                state.items.push({
                    src: im.getAttribute('src') || '',
                    alt: im.getAttribute('alt') || ('帖子图片 ' + (idx + 1))
                });
                im.addEventListener('click', function (evt) {
                    evt.preventDefault();
                    open(state, idx);
                });
            });
        }

        function handleKeydown(state, evt) {
            var overlay = document.getElementById('postImageLightbox');
            if (!overlay || overlay.hidden) return;
            if (evt.key === 'Escape') {
                evt.preventDefault();
                close();
            } else if (evt.key === 'ArrowLeft') {
                evt.preventDefault();
                shift(state, -1);
            } else if (evt.key === 'ArrowRight') {
                evt.preventDefault();
                shift(state, 1);
            }
        }

        return {
            createState: createState,
            bindContentImages: bindContentImages,
            handleKeydown: handleKeydown,
            open: open
        };
    };
})();
