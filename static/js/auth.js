/**
 * 身份验证模块：登录状态、fetchMe、logout，供各页共用
 * 依赖：ApiClient（或全局 API_BASE + localStorage.token）、Toast、handle401
 */
(function () {
    'use strict';

    var currentUser = null;

    function getApiBase() {
        return (typeof window.API_BASE !== 'undefined') ? window.API_BASE : (window.location.origin + '/api');
    }

    async function fetchMe() {
        var token = typeof ApiClient !== 'undefined' ? ApiClient.getToken() : (localStorage.getItem('token') || '');
        if (!token) return null;
        try {
            var url = getApiBase() + '/user/me';
            var headers = { 'Authorization': 'Bearer ' + token };
            var res = await fetch(url, { headers: headers });
            if (typeof handle401 !== 'undefined' && handle401(res)) return null;
            if (res.ok) {
                currentUser = await res.json();
                if (typeof window !== 'undefined') window.currentUser = currentUser;
                return currentUser;
            }
            logout();
            return null;
        } catch (e) {
            return null;
        }
    }

    function logout() {
        try { localStorage.removeItem('token'); } catch (e) {}
        try { localStorage.removeItem('login_at'); } catch (e) {}
        try { sessionStorage.removeItem('login_expiry_warned'); } catch (e) {}
        currentUser = null;
        if (typeof window !== 'undefined') window.currentUser = null;
        if (typeof Toast !== 'undefined') Toast.info('已退出');
    }

    function getCurrentUser() {
        return currentUser;
    }

    function setCurrentUser(user) {
        currentUser = user;
        if (typeof window !== 'undefined') window.currentUser = user;
    }

    window.AuthCore = {
        fetchMe: fetchMe,
        logout: logout,
        getCurrentUser: getCurrentUser,
        setCurrentUser: setCurrentUser
    };
})();
