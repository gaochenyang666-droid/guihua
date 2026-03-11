/**
 * 统一 Toast：success / error / info / warning，供 index/studio/profile 共用
 */
(function () {
    'use strict';

    var container = null;

    function ensureContainer() {
        if (container) return container;
        container = document.getElementById('toastContainer');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toastContainer';
            container.className = 'toast-container';
            document.body.appendChild(container);
        }
        return container;
    }

    function show(message, type) {
        type = type || 'info';
        var el = document.createElement('div');
        el.className = 'toast ' + type;
        el.setAttribute('role', 'alert');
        el.textContent = message;
        ensureContainer().appendChild(el);
        setTimeout(function () {
            if (el.parentNode) el.parentNode.removeChild(el);
        }, 3500);
    }

    window.Toast = {
        success: function (m) { show(m, 'success'); },
        error: function (m) { show(m, 'error'); },
        info: function (m) { show(m, 'info'); },
        warning: function (m) { show(m, 'warning'); }
    };
})();
