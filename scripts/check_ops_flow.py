#!/usr/bin/env python3
"""运维/告警 smoke：管理员监控摘要 + 批量补偿任务。"""

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
    from scripts._acceptance_auth import get_admin_token as _get_accept_admin_token
except ImportError:
    try:
        from _acceptance_auth import get_admin_token as _get_accept_admin_token  # type: ignore
    except ImportError:
        _get_accept_admin_token = None  # type: ignore

try:
    from scripts._contract import require_keys as _require_keys
except ImportError:
    try:
        from _contract import require_keys as _require_keys  # type: ignore
    except ImportError:
        _require_keys = None  # type: ignore


ADMIN_USERNAME = "qa_ops_admin"
PASSWORD = "123456"


def _is_remote_base(base: str) -> bool:
    return "127.0.0.1" not in base and "localhost" not in base




def _load_local_ctx():
    from app import app, db, _new_user  # noqa: E402
    return app, db, _new_user

def _load_ops_ctx():
    from models import User, PendingPublication  # noqa: E402
    from services.observability import log_flow_event  # noqa: E402
    return (*_load_local_ctx(), User, PendingPublication, log_flow_event)

def _remote_admin_creds():
    u = os.environ.get("GUIHUA_ADMIN_USERNAME", "").strip()
    p = os.environ.get("GUIHUA_ADMIN_PASSWORD", "").strip()
    return (u or None, p or None)


def ensure_admin():
    app, db, _new_user, User, PendingPublication, log_flow_event = _load_ops_ctx()
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
        return admin.id


def cleanup_pending(tx_hash):
    app, db, _new_user, User, PendingPublication, log_flow_event = _load_ops_ctx()
    with app.app_context():
        row = PendingPublication.query.filter_by(tx_hash=tx_hash).first()
        if row:
            db.session.delete(row)
            db.session.commit()


def http_json(url, method="GET", token=None, payload=None):
    headers = {"User-Agent": "guihua-ops-smoke/1.0"}
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


def login(base, username=None, password=None):
    u = username or ADMIN_USERNAME
    p = password or PASSWORD
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": u, "password": p},
    )
    assert_ok(status, data, "login")
    return data["token"]


def main():
    maybe_disable_ssl_verify()
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    is_remote = _is_remote_base(base)
    admin_username, admin_password = ADMIN_USERNAME, PASSWORD

    pending_tx_hash = "ops_pending_retry_hash"
    try:
        if not is_remote:
            admin_id = ensure_admin()
            app, db, _new_user, User, PendingPublication, log_flow_event = _load_ops_ctx()
            with app.app_context():
                row = PendingPublication(
                    user_id=admin_id,
                    tx_hash=pending_tx_hash,
                    title=f"QA Ops Pending {int(time.time())}",
                    content="<p>ops</p>",
                    tags='["ops"]',
                    status='awaiting_retry',
                    last_error='待自动补偿',
                )
                db.session.add(row)
                db.session.commit()
                log_flow_event('ops_smoke_seeded', severity='warn', tx_hash=pending_tx_hash)

        if is_remote and _get_accept_admin_token:
            token = _get_accept_admin_token(base)
        else:
            if is_remote:
                creds = _remote_admin_creds()
                if not creds[0] or not creds[1]:
                    print("ops_flow_error=远程环境请设置 GUIHUA_ADMIN_TOKEN（推荐）或 GUIHUA_ADMIN_USERNAME 与 GUIHUA_ADMIN_PASSWORD", file=sys.stderr)
                    return 1
                admin_username, admin_password = creds
            token = login(base, admin_username, admin_password)
        status, data = http_json(base + "/api/admin/stats", token=token)
        assert_ok(status, data, "admin stats")
        # 兼容旧版：admin/stats 可能不包含 redis 字段（redis 状态可在 ops/summary 中验证）。
        if _require_keys:
            _require_keys("admin stats", data, ["users", "posts", "revenue"])
        else:
            if "users" not in data or "posts" not in data or "revenue" not in data:
                raise AssertionError(f"admin stats missing keys: {list(data.keys())}")
        if "redis" in data:
            redis_status = (data.get("redis") or {}).get("status")
            if redis_status not in ("ok", "fallback"):
                raise AssertionError(f"admin stats redis status invalid: {redis_status}")
        print("admin_stats_ok=1")

        status, data = http_json(base + "/api/admin/ops/summary", token=token)
        assert_ok(status, data, "ops summary")
        alerts = data.get("alerts") or []
        if not is_remote and not alerts:
            raise AssertionError(f"ops summary missing alerts: {data}")
        print("ops_summary_ok=1")

        status, data = http_json(base + "/api/admin/flow-events?severity=warn&limit=20", token=token)
        assert_ok(status, data, "flow events")
        items = data.get("items") or []
        if not is_remote and not items:
            raise AssertionError(f"flow events missing items: {data}")
        print("ops_events_ok=1")

        status, data = http_json(base + "/api/admin/pending-publications/retry-batch", method="POST", token=token)
        assert_ok(status, data, "ops retry batch")
        result = data.get("result") or {}
        processed = int(result.get("processed") or 0)
        if not is_remote and processed < 1:
            raise AssertionError(f"ops retry batch processed nothing: {data}")
        print("ops_retry_batch_ok=1")
        print("ops_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"ops_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        if not is_remote:
            cleanup_pending(pending_tx_hash)


if __name__ == "__main__":
    raise SystemExit(main())
