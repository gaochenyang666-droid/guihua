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

from app import app, db, _new_user, _log_flow_event  # noqa: E402
from models import User, PendingPublication  # noqa: E402


ADMIN_USERNAME = "qa_ops_admin"
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
        return admin.id


def cleanup_pending(tx_hash):
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


def login(base):
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": ADMIN_USERNAME, "password": PASSWORD},
    )
    assert_ok(status, data, "login")
    return data["token"]


def main():
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    pending_tx_hash = "ops_pending_retry_hash"
    try:
        admin_id = ensure_admin()
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
            _log_flow_event('ops_smoke_seeded', severity='warn', tx_hash=pending_tx_hash)

        token = login(base)
        status, data = http_json(base + "/api/admin/ops/summary", token=token)
        assert_ok(status, data, "ops summary")
        alerts = data.get("alerts") or []
        if not alerts:
            raise AssertionError(f"ops summary missing alerts: {data}")
        print("ops_summary_ok=1")

        status, data = http_json(base + "/api/admin/pending-publications/retry-batch", method="POST", token=token)
        assert_ok(status, data, "ops retry batch")
        result = data.get("result") or {}
        if int(result.get("processed") or 0) < 1:
            raise AssertionError(f"ops retry batch processed nothing: {data}")
        print("ops_retry_batch_ok=1")
        print("ops_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"ops_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        cleanup_pending(pending_tx_hash)


if __name__ == "__main__":
    raise SystemExit(main())
