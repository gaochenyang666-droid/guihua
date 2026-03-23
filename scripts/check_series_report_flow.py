#!/usr/bin/env python3
"""系列/举报 smoke：创建系列、加帖排序、发举报、管理员处理并检查通知。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

try:
    from _ssl_skip import maybe_disable_ssl_verify
except ImportError:
    def maybe_disable_ssl_verify():
        pass


try:
    from scripts._acceptance_auth import get_admin_token as _get_accept_admin_token, get_user_token as _get_accept_user_token
except ImportError:
    try:
        from _acceptance_auth import get_admin_token as _get_accept_admin_token, get_user_token as _get_accept_user_token  # type: ignore
    except ImportError:
        _get_accept_admin_token = None  # type: ignore
        _get_accept_user_token = None  # type: ignore

try:
    from scripts._contract import require_keys as _require_keys
except ImportError:
    try:
        from _contract import require_keys as _require_keys  # type: ignore
    except ImportError:
        _require_keys = None  # type: ignore


ADMIN_USERNAME = "qa_sr_admin"
USER_USERNAME = "qa_sr_user"
PASSWORD = "123456"


def _is_remote_base(base: str) -> bool:
    return "127.0.0.1" not in base and "localhost" not in base




def _load_local_ctx():
    from app import app, db, _new_user  # noqa: E402
    return app, db, _new_user

def _load_series_models():
    from models import User, Post, Series, Report, Notification  # noqa: E402
    return User, Post, Series, Report, Notification

def _remote_credentials():
    admin_user = os.environ.get("GUIHUA_ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("GUIHUA_ADMIN_PASSWORD", "").strip()
    user_user = os.environ.get("GUIHUA_USER_USERNAME", "").strip() or admin_user
    user_pass = os.environ.get("GUIHUA_USER_PASSWORD", "").strip() or admin_pass
    return (admin_user or None, admin_pass or None, user_user or None, user_pass or None)


def ensure_users():
    app, db, _new_user = _load_local_ctx()
    User, Post, Series, Report, Notification = _load_series_models()
    with app.app_context():
        admin = User.query.filter_by(username=ADMIN_USERNAME).first()
        if not admin:
            admin = _new_user(username=ADMIN_USERNAME, nickname=ADMIN_USERNAME, is_admin=True, avatar='👑')
            db.session.add(admin)
        admin.set_password(PASSWORD)
        admin.is_admin = True

        user = User.query.filter_by(username=USER_USERNAME).first()
        if not user:
            user = _new_user(username=USER_USERNAME, nickname=USER_USERNAME, is_admin=False, avatar='👻')
            db.session.add(user)
        user.set_password(PASSWORD)
        user.is_admin = False
        db.session.commit()


def http_json(url, method="GET", token=None, payload=None):
    headers = {"User-Agent": "guihua-series-report-smoke/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(body or "{}")
        except json.JSONDecodeError:
            data = {"error": body}
        return exc.code, data


def assert_ok(status, data, label):
    if not (200 <= status < 300):
        raise AssertionError(f"{label}: status={status} data={data}")


def login(base, username, password=None):
    pwd = password if password is not None else PASSWORD
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": username, "password": pwd},
    )
    assert_ok(status, data, f"login:{username}")
    return data["token"]


def cleanup(ids):
    app, db, _new_user = _load_local_ctx()
    User, Post, Series, Report, Notification = _load_series_models()
    with app.app_context():
        if ids.get("series_id"):
            row = db.session.get(Series, ids["series_id"])
            if row:
                db.session.delete(row)
        if ids.get("report_id"):
            row = db.session.get(Report, ids["report_id"])
            if row:
                db.session.delete(row)
        if ids.get("notification_id"):
            row = db.session.get(Notification, ids["notification_id"])
            if row:
                db.session.delete(row)
        if ids.get("post_id"):
            row = db.session.get(Post, ids["post_id"])
            if row:
                db.session.delete(row)
        db.session.commit()


def cleanup_remote(base, ids, admin_token):
    if ids.get("post_id"):
        http_json(base + f"/api/posts/{ids['post_id']}", method="DELETE", token=admin_token)
    if ids.get("series_id"):
        http_json(base + f"/api/series/{ids['series_id']}", method="DELETE", token=admin_token)


def main():
    maybe_disable_ssl_verify()
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    is_remote = _is_remote_base(base)
    admin_username, user_username = ADMIN_USERNAME, USER_USERNAME
    admin_password = user_password = PASSWORD
    if is_remote:
        if _get_accept_admin_token and _get_accept_user_token:
            admin_token = _get_accept_admin_token(base)
            user_token = _get_accept_user_token(base, allow_fallback_to_admin=True)
        else:
            creds = _remote_credentials()
            if not creds[0] or not creds[1]:
                print("series_report_flow_error=远程环境请设置 GUIHUA_ADMIN_TOKEN（推荐）或 GUIHUA_ADMIN_USERNAME 与 GUIHUA_ADMIN_PASSWORD", file=sys.stderr)
                return 1
            admin_username, admin_password = creds[0], creds[1]
            user_username = creds[2] or admin_username
            user_password = creds[3] or admin_password
            admin_token = login(base, admin_username, admin_password)
            user_token = login(base, user_username, user_password) if user_username != admin_username else admin_token

    if not is_remote:
        ensure_users()
    ids = {}
    try:
        if not is_remote:
            admin_token = login(base, admin_username, admin_password)
            user_token = login(base, user_username, user_password) if user_username != admin_username else admin_token

        status, data = http_json(
            base + "/api/posts",
            method="POST",
            token=admin_token,
            payload={"title": f"QA 系列帖 {int(time.time())}", "content": "<p>series smoke</p>"},
        )
        assert_ok(status, data, "create seed post")
        ids["post_id"] = ((data.get("post") or {}).get("id"))
        print("series_post_seed_ok=1")

        status, data = http_json(
            base + "/api/series/",
            method="POST",
            token=admin_token,
            payload={"title": f"QA 系列 {int(time.time())}", "description": "smoke", "is_public": True},
        )
        assert_ok(status, data, "create series")
        ids["series_id"] = ((data.get("series") or {}).get("id"))
        print("series_create_ok=1")

        status, data = http_json(
            base + f"/api/series/{ids['series_id']}/posts",
            method="POST",
            token=admin_token,
            payload={"post_id": ids["post_id"]},
        )
        assert_ok(status, data, "add post to series")
        status, data = http_json(
            base + f"/api/series/{ids['series_id']}/order",
            method="PATCH",
            token=admin_token,
            payload={"post_ids": [ids["post_id"]]},
        )
        assert_ok(status, data, "reorder series")
        print("series_order_ok=1")

        status, data = http_json(
            base + "/api/reports",
            method="POST",
            token=user_token,
            payload={"post_id": ids["post_id"], "reason": "qa smoke report"},
        )
        assert_ok(status, data, "create report")
        ids["report_id"] = data.get("id")
        print("report_create_ok=1")

        status, data = http_json(base + "/api/admin/reports", token=admin_token)
        assert_ok(status, data, "list reports")
        # 兼容返回结构：可能是 list，也可能是 {items:[...]}
        reports = data
        if isinstance(data, dict) and "items" in data:
            reports = data.get("items") or []
        if not isinstance(reports, list):
            raise AssertionError(f"list reports: unexpected shape: {type(reports).__name__}")
        if _require_keys and reports:
            _require_keys("report item", reports[0], ["id"])
        if not any(int((r.get("id", 0) if isinstance(r, dict) else 0) or 0) == int(ids["report_id"]) for r in reports):
            raise AssertionError("report missing in admin list")
        status, data = http_json(
            base + f"/api/admin/reports/{ids['report_id']}",
            method="PUT",
            token=admin_token,
            payload={"status": "resolved", "admin_notes": "qa resolved"},
        )
        assert_ok(status, data, "resolve report")
        print("report_resolve_ok=1")

        status, data = http_json(base + "/api/notifications", token=user_token)
        assert_ok(status, data, "user notifications")
        notifs = data.get("notifications") or []
        report_notif = next((n for n in notifs if n.get("type") == "report_result"), None)
        if not report_notif:
            raise AssertionError("report result notification missing")
        ids["notification_id"] = report_notif.get("id")
        print("report_notify_ok=1")
        print("series_report_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"series_report_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        if is_remote:
            try:
                if 'admin_token' in locals():
                    cleanup_remote(base, ids, admin_token)
            except Exception:
                pass
        else:
            cleanup(ids)


if __name__ == "__main__":
    raise SystemExit(main())
