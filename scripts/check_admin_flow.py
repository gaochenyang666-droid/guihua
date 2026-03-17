#!/usr/bin/env python3
"""管理员/互动 smoke：创建临时用户与帖子，经 HTTP 验证后自动清理。"""

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

from app import app, db, _new_user  # noqa: E402
from models import User, Post, Comment, Like, Bookmark, PendingPublication  # noqa: E402


ADMIN_USERNAME = "qa_admin_smoke"
USER_USERNAME = "qa_user_smoke"
PASSWORD = "123456"


def _is_remote_base(base: str) -> bool:
    return "127.0.0.1" not in base and "localhost" not in base


def _remote_credentials():
    """当对远程跑时使用环境变量；未设置则返回 None，调用方应报错或跳过。"""
    admin_user = os.environ.get("GUIHUA_ADMIN_USERNAME", "").strip()
    admin_pass = os.environ.get("GUIHUA_ADMIN_PASSWORD", "").strip()
    user_user = os.environ.get("GUIHUA_USER_USERNAME", "").strip() or admin_user
    user_pass = os.environ.get("GUIHUA_USER_PASSWORD", "").strip() or admin_pass
    return (admin_user or None, admin_pass or None, user_user or None, user_pass or None)


def ensure_users_and_post():
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

        user = User.query.filter_by(username=USER_USERNAME).first()
        if not user:
            user = _new_user(username=USER_USERNAME, nickname=USER_USERNAME, is_admin=False, avatar='👻')
            user.set_password(PASSWORD)
            db.session.add(user)
        else:
            user.nickname = USER_USERNAME
            user.is_admin = False
            user.set_password(PASSWORD)

        db.session.flush()
        post = Post(
            title=f"QA Smoke Post {int(time.time())}",
            content="<p>Smoke content for admin flow.</p>",
            author_id=admin.id,
            allow_comments=True,
            is_hidden=False,
            is_pinned=False,
        )
        db.session.add(post)
        db.session.commit()
        return post.id


def cleanup_post(post_id):
    with app.app_context():
        post = db.session.get(Post, post_id)
        if not post:
            return
        comment_ids = [c.id for c in Comment.query.filter_by(post_id=post.id).all()]
        if comment_ids:
            Comment.query.filter(Comment.id.in_(comment_ids)).delete(synchronize_session=False)
        Like.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        Bookmark.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        db.session.delete(post)
        db.session.commit()


def cleanup_pending(tx_hash):
    with app.app_context():
        row = PendingPublication.query.filter_by(tx_hash=tx_hash).first()
        if row:
            db.session.delete(row)
            db.session.commit()


def http_json(url, method="GET", token=None, payload=None):
    headers = {"User-Agent": "guihua-admin-smoke/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
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
    token = data.get("token") or ""
    if not token:
        raise AssertionError(f"login:{username}: missing token")
    return token


def main():
    maybe_disable_ssl_verify()
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    is_remote = _is_remote_base(base)
    admin_username = ADMIN_USERNAME
    admin_password = PASSWORD
    user_username = USER_USERNAME
    user_password = PASSWORD
    if is_remote:
        creds = _remote_credentials()
        if not creds[0] or not creds[1]:
            print("admin_flow_error=远程环境请设置 GUIHUA_ADMIN_USERNAME 与 GUIHUA_ADMIN_PASSWORD", file=sys.stderr)
            return 1
        admin_username, admin_password = creds[0], creds[1]
        user_username = creds[2] or admin_username
        user_password = creds[3] or admin_password

    post_id = None
    pending_tx_hash = "0x" + ("ef" * 32)
    try:
        if not is_remote:
            post_id = ensure_users_and_post()
            admin_token = login(base, admin_username, admin_password)
            user_token = login(base, user_username, user_password)
        else:
            admin_token = login(base, admin_username, admin_password)
            status, data = http_json(
                base + "/api/posts",
                method="POST",
                token=admin_token,
                payload={"title": f"QA Smoke Post {int(time.time())}", "content": "<p>Smoke content for admin flow.</p>"},
            )
            assert_ok(status, data, "create post (remote)")
            post_id = (data.get("post") or {}).get("id")
            if not post_id:
                raise AssertionError(f"create post missing id: {data}")
            user_token = login(base, user_username, user_password) if user_username != admin_username else admin_token

        status, data = http_json(f"{base}/api/posts/{post_id}/like", method="POST", token=user_token)
        assert_ok(status, data, "user like")
        print("user_like_ok=1")

        status, data = http_json(f"{base}/api/posts/{post_id}/bookmark", method="POST", token=user_token)
        assert_ok(status, data, "user bookmark")
        print("user_bookmark_ok=1")

        status, data = http_json(
            f"{base}/api/posts/{post_id}/comments",
            method="POST",
            token=user_token,
            payload={"content": "qa smoke comment"},
        )
        assert_ok(status, data, "user comment")
        print("user_comment_ok=1")

        status, data = http_json(f"{base}/api/admin/posts/{post_id}/pin", method="POST", token=admin_token, payload={"pinned": True, "exclusive": False})
        assert_ok(status, data, "admin pin")
        print("admin_pin_ok=1")

        status, data = http_json(f"{base}/api/admin/posts/{post_id}/toggle-comments", method="POST", token=admin_token)
        assert_ok(status, data, "admin toggle comments off")
        status, data = http_json(f"{base}/api/admin/posts/{post_id}/toggle-comments", method="POST", token=admin_token)
        assert_ok(status, data, "admin toggle comments on")
        print("admin_comments_ok=1")

        status, data = http_json(f"{base}/api/admin/posts/{post_id}/hide", method="POST", token=admin_token)
        assert_ok(status, data, "admin hide")
        status, data = http_json(f"{base}/api/admin/posts/{post_id}/hide", method="POST", token=admin_token)
        assert_ok(status, data, "admin unhide")
        print("admin_hide_ok=1")

        status, data = http_json(f"{base}/api/posts/{post_id}", method="DELETE", token=admin_token)
        assert_ok(status, data, "admin delete")
        post_id = None
        print("admin_delete_ok=1")

        if not is_remote:
            with app.app_context():
                admin_id = User.query.filter_by(username=ADMIN_USERNAME).with_entities(User.id).scalar()
                row = PendingPublication(
                    user_id=admin_id,
                    tx_hash=pending_tx_hash,
                    title="QA Admin Pending",
                    content="<p>pending</p>",
                    tags='["qa"]',
                    status='awaiting_retry',
                    last_error='待管理员处理',
                )
                db.session.add(row)
                db.session.commit()

            status, data = http_json(f"{base}/api/admin/pending-publications", token=admin_token)
            assert_ok(status, data, "admin pending list")
            items = data.get("items") or []
            if not any((row.get("tx_hash") == pending_tx_hash) for row in items):
                raise AssertionError(f"pending publication not found in admin list: {data}")
            print("admin_pending_list_ok=1")

            status, data = http_json(f"{base}/api/admin/pending-publications?status=awaiting_retry&q=QA%20Admin%20Pending", token=admin_token)
            assert_ok(status, data, "admin pending filtered list")
            filtered = data.get("items") or []
            if not any((row.get("tx_hash") == pending_tx_hash) for row in filtered):
                raise AssertionError(f"pending publication not found in filtered list: {data}")
            print("admin_pending_filter_ok=1")

            pending_id = next((row.get("id") for row in items if row.get("tx_hash") == pending_tx_hash), None)
            if not pending_id:
                raise AssertionError(f"pending publication id missing: {data}")
            status, data = http_json(f"{base}/api/admin/pending-publications/{pending_id}", method="DELETE", token=admin_token)
            assert_ok(status, data, "admin pending delete")
            print("admin_pending_delete_ok=1")
        else:
            print("admin_pending_skipped=1")

        print("admin_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"admin_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        if not is_remote and post_id is not None:
            try:
                cleanup_post(post_id)
            except Exception:
                pass
        if not is_remote:
            try:
                cleanup_pending(pending_tx_hash)
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
