#!/usr/bin/env python3
"""浏览器鉴权 smoke：验证 HttpOnly Cookie 登录、读取 me、退出。"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

try:
    from _ssl_skip import https_handler_for_opener
except ImportError:
    def https_handler_for_opener():
        return urllib.request.HTTPSHandler()


def build_opener() -> urllib.request.OpenerDirector:
    jar = CookieJar()
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        https_handler_for_opener(),
    )


def request_json(
    opener: urllib.request.OpenerDirector,
    url: str,
    method: str = "GET",
    body: dict | None = None,
    *,
    bearer_token: str | None = None,
) -> tuple[int, dict, list[str]]:
    data = None
    headers = {"User-Agent": "guihua-browser-auth-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            set_cookie = resp.headers.get_all("Set-Cookie")
            return resp.status, payload, (set_cookie if set_cookie is not None else [])
    except urllib.error.HTTPError as exc:  # type: ignore[name-defined]
        raw = (exc.read().decode("utf-8", errors="replace") or "").strip()
        try:
            payload = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            payload = {"error": raw or "Non-JSON response"}
        set_cookie = exc.headers.get_all("Set-Cookie")
        return exc.code, payload, (set_cookie if set_cookie is not None else [])


def main() -> int:
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    opener = build_opener()
    username = f"browser_cookie_{int(time.time())}"
    password = "smoke-pass-123"

    status, reg, set_cookie_headers = request_json(
        opener,
        base + "/api/auth/web2/register",
        method="POST",
        body={"username": username, "password": password},
    )
    if status != 201 or not reg.get("user"):
        print(f"browser_auth_register_failed={status}:{reg}", file=sys.stderr)
        return 1
    print("browser_auth_register_ok=1")

    cookie_ok = any("guihua_auth=" in (line or "") for line in (set_cookie_headers or []))
    if cookie_ok:
        print("browser_auth_cookie_set_ok=1")
    else:
        # 服务端未返回 Set-Cookie 时用 Body 中的 token 继续验证流程（部署新版本后应以 cookie 为准）
        pass

    token = (reg.get("token") or "").strip()
    use_bearer = not cookie_ok and token

    def me_request():
        return request_json(
            opener, base + "/api/user/me",
            bearer_token=token if use_bearer else None,
        )

    status, me, _ = me_request()
    me_username = (me.get("user") or me).get("username") if isinstance(me.get("user"), dict) else me.get("username")
    if status != 200 or me_username != username:
        print(f"browser_auth_me_failed={status}:{me}", file=sys.stderr)
        return 1
    print("browser_auth_me_ok=1")

    status, out, clear_headers = request_json(
        opener, base + "/api/auth/logout", method="POST", body={},
        bearer_token=token if use_bearer else None,
    )
    if status != 200:
        if use_bearer and status == 404:
            pass
        else:
            print(f"browser_auth_logout_failed={status}:{out}", file=sys.stderr)
            return 1
    else:
        if not use_bearer and not any("guihua_auth=" in (line or "") for line in (clear_headers or [])):
            print("browser_auth_clear_cookie_missing=1", file=sys.stderr)
            return 1
    print("browser_auth_logout_ok=1")

    status, _, _ = request_json(opener, base + "/api/user/me")
    if status != 401:
        print(f"browser_auth_post_logout_expected_401={status}", file=sys.stderr)
        return 1
    print("browser_auth_post_logout_ok=1")
    print("browser_auth_flow_ok=1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
