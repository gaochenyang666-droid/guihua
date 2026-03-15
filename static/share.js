(function () {
    'use strict';

    function getShareUrl(postId) {
        var id = Number(postId);
        if (!Number.isFinite(id) || id <= 0) return '';
        return window.location.origin + '/post/' + id;
    }

    function getShareText(title) {
        var cleanTitle = String(title || '').trim();
        return cleanTitle ? ('「' + cleanTitle + '」') : '来看看这篇灵异帖';
    }

    async function share(refOrPostId, titleMaybe) {
        var postId = null;
        var title = '';
        if (refOrPostId && typeof refOrPostId === 'object' && typeof refOrPostId.getAttribute === 'function') {
            postId = Number(refOrPostId.getAttribute('data-post-id'));
            title = refOrPostId.getAttribute('data-title') || '';
        } else {
            postId = Number(refOrPostId);
            title = String(titleMaybe || '');
        }
        var url = getShareUrl(postId);
        if (!url) return false;
        var text = getShareText(title);
        if (navigator.share) {
            try {
                await navigator.share({
                    title: title || '诡话',
                    text: text,
                    url: url
                });
                return true;
            } catch (err) {
                if (err && err.name === 'AbortError') return false;
            }
        }
        if (typeof copyTextWithFallback === 'function') {
            var copied = await copyTextWithFallback(url, '已复制帖子链接');
            if (!copied && window.Toast && Toast.error) Toast.error('分享失败，请稍后重试');
            return copied;
        }
        return false;
    }

    function openXShare(postId, title) {
        var url = getShareUrl(postId);
        if (!url) return;
        var text = getShareText(title);
        var intent = 'https://x.com/intent/tweet?text=' + encodeURIComponent(text) + '&url=' + encodeURIComponent(url);
        window.open(intent, '_blank', 'noopener,noreferrer');
    }

    window.GHShare = {
        getShareUrl: getShareUrl,
        getShareText: getShareText,
        share: share,
        openXShare: openXShare
    };
})();
