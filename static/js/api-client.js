/**
 * 统一 API 客户端：封装 fetch，自动带 Authorization，统一错误与重试
 */
(function () {
    'use strict';

    function getBase() {
        return (typeof window !== 'undefined' && window.API_BASE) ? window.API_BASE : (window.location.origin + '/api');
    }

    function getToken() {
        try {
            return localStorage.getItem('token') || '';
        } catch (e) {
            return '';
        }
    }

    function request(method, path, body, options) {
        var url = path.indexOf('http') === 0 ? path : getBase() + path;
        var headers = { 'Content-Type': 'application/json' };
        var token = getToken();
        if (token) headers['Authorization'] = 'Bearer ' + token;
        if (options && options.headers) {
            for (var k in options.headers) headers[k] = options.headers[k];
        }
        var init = { method: method, headers: headers };
        if (body !== undefined && body !== null && method !== 'GET') {
            init.body = typeof body === 'string' ? body : JSON.stringify(body);
        }
        if (options && options.body !== undefined) init.body = options.body;
        return fetch(url, init);
    }

    window.ApiClient = {
        getBase: getBase,
        getToken: getToken,
        get: function (path) { return request('GET', path); },
        post: function (path, body) { return request('POST', path, body); },
        put: function (path, body) { return request('PUT', path, body); },
        delete: function (path) { return request('DELETE', path); },
        request: request
    };
})();
