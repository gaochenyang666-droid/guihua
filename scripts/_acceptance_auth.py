#!/usr/bin/env python3
"""Release suite 远程验收鉴权工具。

优先使用环境变量提供的 token，避免频繁登录触发限流：

- GUIHUA_ADMIN_TOKEN
- GUIHUA_USER_TOKEN（可选）

兼容旧方式（fallback）：

- GUIHUA_ADMIN_USERNAME / GUIHUA_ADMIN_PASSWORD
- GUIHUA_USER_USERNAME / GUIHUA_USER_PASSWORD（可选，不设置则默认复用 admin）
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def _http_json(url: str, method: str = "GET", token: str | None = None, payload: dict | None = None, timeout: int = 10):
    headers = {"User-Agent": "guihua-release-suite/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body or "{}")
        except json.JSONDecodeError:
            data = {"error": body}
        return exc.code, data


def _login_with_password(base: str, username: str, password: str) -> str:
    # 多脚本串行跑时容易遇到 login rate limit，做轻量重试提升稳定性。
    last = None
    for attempt in range(5):
        status, data = _http_json(
            base.rstrip("/") + "/api/auth/web2/login",
            method="POST",
            payload={"username": username, "password": password},
            timeout=10,
        )
        last = (status, data)
        if status == 429:
            time.sleep(0.8 * (attempt + 1))
            continue
        if not (200 <= status < 300):
            raise AssertionError(f"login:{username}: status={status} data={data}")
        token = (data.get("token") or "").strip()
        if not token:
            raise AssertionError(f"login:{username}: missing token")
        return token
    raise AssertionError(f"login:{username}: status=429 data={(last or {})}")


def get_admin_token(base: str) -> str:
    token = _env("GUIHUA_ADMIN_TOKEN")
    if token:
        return token
    username = _env("GUIHUA_ADMIN_USERNAME")
    password = _env("GUIHUA_ADMIN_PASSWORD")
    if username and password:
        return _login_with_password(base, username, password)
    raise AssertionError("远程验收需要 GUIHUA_ADMIN_TOKEN，或 GUIHUA_ADMIN_USERNAME + GUIHUA_ADMIN_PASSWORD")


def get_user_token(base: str, *, allow_fallback_to_admin: bool = True) -> str:
    token = _env("GUIHUA_USER_TOKEN")
    if token:
        return token
    username = _env("GUIHUA_USER_USERNAME")
    password = _env("GUIHUA_USER_PASSWORD")
    if username and password:
        return _login_with_password(base, username, password)
    if allow_fallback_to_admin:
        return get_admin_token(base)
    raise AssertionError("需要 GUIHUA_USER_TOKEN，或 GUIHUA_USER_USERNAME + GUIHUA_USER_PASSWORD")

