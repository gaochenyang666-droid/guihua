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
                const currentUser = getCurrentUser();
                if (!select || !currentUser) return;
                try {
                    const result = await apiJson(`${apiBase}/series?mine=1&page=1&per_page=80`, { fallback: {} });
                    const data = result.data;
                    const items = (data && (data.items || data.series)) || [];
                    this.seriesItems = Array.isArray(items) ? items : [];
                    const currentVal = (preferId != null && preferId !== '') ? String(preferId) : getSeriesSelectValue();
                    select.innerHTML = `<option value="">不加入系列</option>${
                        this.seriesItems.map((s) => `<option value="${String(s.id)}">${escapeHtml(s.title || ('系列 #' + s.id))}</option>`).join('')
                    }`;
                    if (currentVal && this.seriesItems.some((s) => String(s.id) === currentVal)) {
                        select.value = currentVal;
                    } else {
                        select.value = '';
                    }
                } catch (_) {
                    if (select.options.length <= 1) {
                        select.innerHTML = '<option value="">不加入系列</option>';
                    }
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
                    Draft.save();
                } catch (e) {
                    Toast.error('创建系列失败: ' + ((e && e.message) || '网络错误'));
                }
            }
        };
    };
})();
