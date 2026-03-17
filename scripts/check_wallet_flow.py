#!/usr/bin/env python3
"""钱包登录/绑定 smoke：本地生成临时钱包签名，覆盖 nonce、验签、Web2 绑钱包。"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from eth_account import Account
from eth_account.messages import encode_defunct

try:
    from _ssl_skip import maybe_disable_ssl_verify
except ImportError:
    def maybe_disable_ssl_verify():
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import app, db, _new_user  # noqa: E402
from models import User  # noqa: E402


PASSWORD = "123456"


def host_label(base_url: str) -> str:
    parsed = urllib.parse.urlparse(base_url)
    return parsed.netloc or parsed.path


def http_json(url, method="GET", token=None, payload=None):
    headers = {"User-Agent": "guihua-wallet-smoke/1.0"}
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


def ensure_web2_user(username):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if not user:
            user = _new_user(username=username, nickname=username, avatar='👻', is_admin=False)
            user.set_password(PASSWORD)
            db.session.add(user)
        else:
            user.nickname = username
            user.set_password(PASSWORD)
            user.address = None
            user.wallet_address = None
        db.session.commit()
        return user.id


def cleanup_user(username):
    with app.app_context():
        user = User.query.filter_by(username=username).first()
        if user:
            db.session.delete(user)
            db.session.commit()


def login_web2(base, username):
    status, data = http_json(
        base + "/api/auth/web2/login",
        method="POST",
        payload={"username": username, "password": PASSWORD},
    )
    assert_ok(status, data, f"login:{username}")
    token = data.get("token") or ""
    if not token:
        raise AssertionError("login token missing")
    return token


def sign_text(private_key_hex: str, message: str) -> str:
    signed = Account.sign_message(encode_defunct(text=message), private_key=private_key_hex)
    return signed.signature.hex()


def _is_remote_base(base: str) -> bool:
    return "127.0.0.1" not in base and "localhost" not in base


def main():
    maybe_disable_ssl_verify()
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    if _is_remote_base(base):
        print("wallet_flow_skipped=1")
        print("wallet_flow_ok=1")
        return 0
    wallet_username = f"qa_wallet_bind_{int(time.time())}"
    try:
        ensure_web2_user(wallet_username)
        token = login_web2(base, wallet_username)

        # Web2 绑定钱包
        bind_account = Account.create()
        bind_address = bind_account.address
        host = host_label(base)
        status, data = http_json(base + "/api/user/bind_wallet/nonce", token=token)
        assert_ok(status, data, "bind nonce")
        bind_nonce = data.get("nonce") or ""
        if not bind_nonce:
            raise AssertionError("bind nonce missing")
        with app.app_context():
            user_id = User.query.filter_by(username=wallet_username).with_entities(User.id).scalar()
        bind_message = f"Bind wallet {bind_address} to account {user_id} on {host}: {bind_nonce}"
        bind_signature = sign_text(bind_account.key.hex(), bind_message)
        status, data = http_json(
            base + "/api/user/bind_wallet",
            method="POST",
            token=token,
            payload={
                "address": bind_address,
                "message": bind_message,
                "signature": bind_signature,
            },
        )
        assert_ok(status, data, "bind wallet")
        print("bind_wallet_ok=1")

        # 原生钱包登录
        login_account = Account.create()
        login_address = login_account.address
        status, data = http_json(base + f"/api/auth/nonce?address={urllib.parse.quote(login_address)}")
        assert_ok(status, data, "wallet nonce")
        login_nonce = data.get("nonce") or ""
        if not login_nonce:
            raise AssertionError("wallet nonce missing")
        login_message = f"Sign this message to login to {host}: {login_nonce}"
        login_signature = sign_text(login_account.key.hex(), login_message)
        status, data = http_json(
            base + "/api/auth/verify",
            method="POST",
            payload={
                "address": login_address,
                "message": login_message,
                "signature": login_signature,
            },
        )
        assert_ok(status, data, "wallet verify")
        if not data.get("token"):
            raise AssertionError("wallet verify token missing")
        print("wallet_login_ok=1")
        print("wallet_flow_ok=1")
        return 0
    except Exception as exc:
        print(f"wallet_flow_error={exc}", file=sys.stderr)
        return 1
    finally:
        cleanup_user(wallet_username)


if __name__ == "__main__":
    raise SystemExit(main())
