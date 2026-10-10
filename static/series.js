(function () {
    'use strict';

    var API_BASE = window.location.origin + '/api';

    async function loadSeriesPage() {
        var parts = location.pathname.split('/').filter(Boolean);
        var id = Number(parts[parts.length - 1] || 0);
        if (!id) {
            document.getElementById('seriesMeta').textContent = '系列不存在';
            document.getElementById('seriesList').innerHTML = '';
            return;
        }
        try {
            var result = await apiJson(API_BASE + '/series/' + id, { auth: false, fallback: {} });
            var res = result.res;
            var data = result.data;
            if (!res.ok) {
                document.getElementById('seriesMeta').innerHTML = '<div class="state-error">' + escapeHtml((data && data.error) || '加载失败') + '</div>';
                document.getElementById('seriesList').innerHTML = '';
                return;
            }
            var s = data.series || {};
            var items = data.items || [];
            document.title = (s.title || '系列目录') + ' - 诡话';
            document.getElementById('seriesMeta').innerHTML =
                '<h2 class="series-page-title">📚 ' + escapeHtml(s.title || '') + '</h2>' +
                '<div class="series-page-description">' + escapeHtml(s.description || '暂无系列简介') + '</div>';
            if (!items.length) {
                document.getElementById('seriesList').innerHTML = '<div class="state-empty">该系列暂无可见帖子</div>';
                return;
            }
            document.getElementById('seriesList').innerHTML =
                '<h3 class="series-page-section-title">目录</h3>' +
                '<div class="series-page-list">' +
                items.map(function (it) {
                    var p = it.post || {};
                    return '<button class="btn btn-ghost series-open-post-btn series-open-post-btn-wide" data-post-id="' + p.id + '" type="button"><span>第 ' + it.order_index + ' 篇 · ' + escapeHtml(p.title || '') + '</span><span class="series-open-post-hint">查看</span></button>';
                }).join('') +
                '</div>';
            Array.prototype.forEach.call(document.querySelectorAll('.series-open-post-btn'), function (btn) {
                btn.addEventListener('click', function () {
                    var pid = Number(btn.getAttribute('data-post-id'));
                    if (!Number.isFinite(pid)) return;
                    navigateWithTransition('/?post=' + pid);
                });
            });
        } catch (_) {
            document.getElementById('seriesMeta').innerHTML = '<div class="state-error">网络错误</div>';
            document.getElementById('seriesList').innerHTML = '';
        }
    }

    window.addEventListener('load', function () {
        var backBtn = document.getElementById('seriesBackHomeBtn');
        if (backBtn) backBtn.addEventListener('click', function () {
            navigateWithTransition('/');
        });
        loadSeriesPage();
    });
})();
