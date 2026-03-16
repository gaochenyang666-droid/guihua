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

from app import app, db, _new_user  # noqa: E402
from models import User, Post, Series, Report, Notification  # noqa: E402


ADMIN_USERNAME = "qa_sr_admin"
USER_USERNAME = "qa_sr_user"
PASSWORD = "123456"


def ensure_users():
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


def login(base, username):
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": username, "password": PASSWORD},
    )
    assert_ok(status, data, f"login:{username}")
    return data["token"]


def cleanup(ids):
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


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    ensure_users()
    ids = {}
    try:
        admin_token = login(base, ADMIN_USERNAME)
        user_token = login(base, USER_USERNAME)

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
            base + "/api/series",
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
        if not any(int(r.get("id", 0)) == int(ids["report_id"]) for r in data):
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
        cleanup(ids)


if __name__ == "__main__":
    raise SystemExit(main())
