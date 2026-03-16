#!/usr/bin/env python3
"""浏览器鉴权 smoke：验证 HttpOnly Cookie 登录、读取 me、退出。"""

from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar


def build_opener() -> urllib.request.OpenerDirector:
    jar = CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))


def request_json(opener: urllib.request.OpenerDirector, url: str, method: str = "GET", body: dict | None = None) -> tuple[int, dict, list[str]]:
    data = None
    headers = {"User-Agent": "guihua-browser-auth-smoke/1.0"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with opener.open(req, timeout=8) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace") or "{}")
            return resp.status, payload, resp.headers.get_all("Set-Cookie", [])
    except urllib.error.HTTPError as exc:  # type: ignore[name-defined]
        payload = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
        return exc.code, payload, exc.headers.get_all("Set-Cookie", [])


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
    if not any("guihua_auth=" in (line or "") for line in set_cookie_headers):
        print("browser_auth_cookie_missing=1", file=sys.stderr)
        return 1
    print("browser_auth_cookie_set_ok=1")

    status, me, _ = request_json(opener, base + "/api/user/me")
    if status != 200 or (me.get("username") != username and (me.get("user") or {}).get("username") != username):
        print(f"browser_auth_me_failed={status}:{me}", file=sys.stderr)
        return 1
    print("browser_auth_me_ok=1")

    status, out, clear_headers = request_json(opener, base + "/api/auth/logout", method="POST", body={})
    if status != 200:
        print(f"browser_auth_logout_failed={status}:{out}", file=sys.stderr)
        return 1
    if not any("guihua_auth=" in (line or "") for line in clear_headers):
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
