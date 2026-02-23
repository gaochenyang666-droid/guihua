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
            container.style.cssText = 'position:fixed;top:1rem;right:1rem;z-index:99999;display:flex;flex-direction:column;gap:0.5rem;pointer-events:none;';
            document.body.appendChild(container);
        }
        return container;
    }

    function show(message, type) {
        type = type || 'info';
        var el = document.createElement('div');
        el.className = 'toast toast-' + type;
        el.setAttribute('role', 'alert');
        el.textContent = message;
        el.style.cssText = 'padding:0.6rem 1rem;border-radius:8px;background:var(--bg-secondary, #1f2937);color:var(--text-primary, #f9fafb);font-size:0.9rem;box-shadow:0 4px 12px rgba(0,0,0,0.3);pointer-events:auto;max-width:320px;';
        if (type === 'success') el.style.borderLeft = '4px solid #10b981';
        else if (type === 'error') el.style.borderLeft = '4px solid #ef4444';
        else if (type === 'warning') el.style.borderLeft = '4px solid #f59e0b';
        else el.style.borderLeft = '4px solid #3b82f6';
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
