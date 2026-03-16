#!/usr/bin/env python3
"""发帖链路 smoke：管理员直发 + 预检查 + check_tx 已发布状态。"""

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
from models import User, Post  # noqa: E402


ADMIN_USERNAME = "qa_post_admin"
PASSWORD = "123456"


def ensure_admin():
    with app.app_context():
        admin = User.query.filter_by(username=ADMIN_USERNAME).first()
        if not admin:
            admin = _new_user(username=ADMIN_USERNAME, nickname=ADMIN_USERNAME, is_admin=True, avatar='👑')
            admin.set_password(PASSWORD)
            db.session.add(admin)
        else:
            admin.nickname = ADMIN_USERNAME
            admin.is_admin = True
            admin.set_password(PASSWORD)
        db.session.commit()


def http_json(url, method="GET", token=None, payload=None):
    headers = {"User-Agent": "guihua-post-smoke/1.0"}
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


def login(base):
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": ADMIN_USERNAME, "password": PASSWORD},
    )
    assert_ok(status, data, "login")
    return data["token"]


def cleanup_post(post_id):
    with app.app_context():
        row = db.session.get(Post, post_id)
        if row:
            db.session.delete(row)
            db.session.commit()


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    ensure_admin()
    created_post_id = None
    synthetic_post_id = None
    try:
        token = login(base)
        payload = {"title": f"QA 发布链路 {int(time.time())}", "content": "<p>Smoke post body.</p>"}
        status, data = http_json(base + "/api/posts/precheck", method="POST", token=token, payload=payload)
        assert_ok(status, data, "precheck")
        if not data.get("ok"):
            raise AssertionError(f"precheck not ok: {data}")
        print("post_precheck_ok=1")

        status, data = http_json(base + "/api/posts", method="POST", token=token, payload=payload)
        assert_ok(status, data, "create post")
        created_post_id = ((data.get("post") or {}).get("id"))
        if not created_post_id:
            raise AssertionError("create post missing id")
        print("post_create_ok=1")

        with app.app_context():
            row = Post(
                title="QA Chain Published",
                content="<p>published</p>",
                author_id=User.query.filter_by(username=ADMIN_USERNAME).with_entities(User.id).scalar(),
                tx_hash="0x" + ("ab" * 32),
                ipfs_cid="qa-chain-cid",
                is_paid=True,
                is_on_chain=True,
                post_type=1,
            )
            db.session.add(row)
            db.session.commit()
            synthetic_post_id = row.id

        status, data = http_json(base + "/api/posts/check_tx?tx_hash=" + ("0x" + ("ab" * 32)))
        assert_ok(status, data, "check tx")
        if data.get("status") != "success":
            raise AssertionError(f"unexpected check_tx status: {data}")
        if data.get("stage") not in (None, "", "published"):
            raise AssertionError(f"unexpected published stage: {data}")
        print("post_check_tx_ok=1")
        print("post_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"post_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        if created_post_id:
            cleanup_post(created_post_id)
        if synthetic_post_id:
            cleanup_post(synthetic_post_id)


if __name__ == "__main__":
    raise SystemExit(main())
