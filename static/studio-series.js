(function () {
    'use strict';

    window.GHStudioSeriesFactory = function GHStudioSeriesFactory(deps) {
        const {
            apiBase,
            apiJson,
            getCurrentUser,
            getSeriesSelectValue,
            Draft,
            escapeHtml,
            Toast
        } = deps;

        return {
            async loadSeriesOptions(preferId) {
                const select = document.getElementById('studioSeriesSelect');
                const root = document.getElementById('studioView');
                const currentUser = getCurrentUser();
                if (!select || !currentUser) return;
                [
                    '#studioPostTags',
                    '#studioTagInput',
                    '#studioTagsInput',
                    '[data-field="tags"]',
                    '.studio-tags-group',
                    '.studio-tag-group'
                ].forEach((selector) => {
                    if (!root) return;
                    root.querySelectorAll(selector).forEach((node) => {
                        const group = node.closest('.form-group') || node.closest('.studio-meta-grid-full') || node;
                        if (group && group.parentNode) group.parentNode.removeChild(group);
                    });
                });
                if (root) {
                    root.querySelectorAll('.form-group, .studio-meta-grid-full').forEach((node) => {
                        const text = (node.textContent || '').replace(/\s+/g, '');
                        if (text.includes('标签') && !node.querySelector('#studioSeriesSelect')) {
                            node.remove();
                        }
                    });
                }
                let help = document.getElementById('studioSeriesHelp');
                if (!help && select.parentNode) {
                    help = document.createElement('div');
                    help.id = 'studioSeriesHelp';
                    help.className = 'form-help studio-series-help';
                    select.insertAdjacentElement('afterend', help);
                }
                select.disabled = true;
                try {
                    const result = await apiJson(`${apiBase}/series?mine=1&page=1&per_page=80`, { fallback: {} });
                    const data = result.data;
                    const items = (data && (data.items || data.series)) || [];
                    this.seriesItems = Array.isArray(items) ? items : [];
                    const currentVal = (preferId != null && preferId !== '') ? String(preferId) : getSeriesSelectValue();
                    select.innerHTML = `<option value="">${this.seriesItems.length ? '不加入系列' : '暂无系列，点右侧新建'}</option>${
                        this.seriesItems.map((s) => `<option value="${String(s.id)}">${escapeHtml(s.title || ('系列 #' + s.id))}</option>`).join('')
                    }`;
                    if (currentVal && this.seriesItems.some((s) => String(s.id) === currentVal)) {
                        select.value = currentVal;
                    } else {
                        select.value = '';
                    }
                    if (help) {
                        help.textContent = this.seriesItems.length
                            ? `已加载 ${this.seriesItems.length} 个系列，可选中后发布到对应合集。`
                            : '你还没有系列，点击右侧“新建系列”即可立即创建。';
                    }
                } catch (_) {
                    if (select.options.length <= 1) {
                        select.innerHTML = '<option value="">暂时无法加载系列</option>';
                    }
                    if (help) {
                        help.textContent = '系列列表加载失败，可稍后重试或直接新建系列。';
                    }
                } finally {
                    select.disabled = false;
                }
            },

            async quickCreateSeries() {
                if (!getCurrentUser()) return;
                const title = (prompt('请输入系列标题（120字内）') || '').trim();
                if (!title) return;
                const description = (prompt('可选：系列简介（可留空）') || '').trim();
                try {
                    const result = await apiJson(`${apiBase}/series/`, {
                        method: 'POST',
                        body: { title, description, is_public: true },
                        fallback: {}
                    });
                    const res = result.res;
                    const data = result.data;
                    if (!res.ok) {
                        Toast.error(data.error || '创建系列失败');
                        return;
                    }
                    Toast.success(data.message || '系列已创建');
                    const sid = data && data.series ? data.series.id : '';
                    await this.loadSeriesOptions(sid ? String(sid) : '');
                    if (sid) {
                        const select = document.getElementById('studioSeriesSelect');
                        if (select) select.value = String(sid);
                    }
                    Draft.save();
                } catch (e) {
                    Toast.error('创建系列失败: ' + ((e && e.message) || '网络错误'));
                }
            }
        };
    };
})();
