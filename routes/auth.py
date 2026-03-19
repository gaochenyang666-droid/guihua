import secrets
from datetime import datetime, timedelta, timezone

from flask import Blueprint, request, jsonify, g
from web3 import Web3

from extensions import db
from models import User, get_random_avatar
from utils.security import (
    _rate_limit, set_auth_cookie, clear_auth_cookie, issue_auth_token,
    _get_redis_client,
)
from services.runtime_state import (
    prune_pending_wallet_nonces,
    pending_wallet_nonce_redis_key,
    set_pending_wallet_nonce,
    get_pending_wallet_nonce,
    delete_pending_wallet_nonce,
)
from services.observability import log_flow_event as _log_flow_event
from services.app_support import parse_iso_datetime
from services.user_factory import new_user as _new_user

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

WALLET_NONCE_TTL_MINUTES = 5
JWT_EXPIRY_HOURS = 24

_pending_wallet_nonces = {}
_pending_wallet_nonce_redis_prefix = 'auth:pending_wallet_nonce:'


def _wallet_redis_key(address):
    return pending_wallet_nonce_redis_key(_pending_wallet_nonce_redis_prefix, address)


def _prune_pending_wallet_nonces():
    prune_pending_wallet_nonces(_pending_wallet_nonces, WALLET_NONCE_TTL_MINUTES)


def _set_pending_wallet_nonce(address, nonce, created_at=None):
    redis_conn = _get_redis_client()
    set_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _wallet_redis_key(address),
        WALLET_NONCE_TTL_MINUTES,
        address,
        nonce,
        created_at=created_at,
    )


def _get_pending_wallet_nonce(address):
    redis_conn = _get_redis_client()
    return get_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _wallet_redis_key(address),
        address,
        parse_iso_datetime,
    )


def _delete_pending_wallet_nonce(address):
    redis_conn = _get_redis_client()
    delete_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _wallet_redis_key(address),
        address,
    )


@auth_bp.route('/nonce', methods=['GET'])
def get_nonce():
    if _rate_limit('nonce', 30):
        return jsonify({'error': '请求过于频繁'}), 429
    _prune_pending_wallet_nonces()
    address = request.args.get('address')
    if not address: return jsonify({'error': '缺少钱包地址'}), 400

    try:
        address = Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
        return jsonify({'error': '钱包地址格式无效'}), 400

    user = User.query.filter_by(address=address).first()
    if user:
        user.refresh_nonce()
        db.session.commit()
        _log_flow_event('wallet_nonce_issued', address=address, mode='existing_user')
        return jsonify({'nonce': user.nonce})

    nonce = secrets.token_hex(16)
    _set_pending_wallet_nonce(address, nonce, datetime.now(timezone.utc))
    _log_flow_event('wallet_nonce_issued', address=address, mode='pending_user')
    return jsonify({'nonce': nonce})


@auth_bp.route('/verify', methods=['POST'])
def verify_signature():
    if _rate_limit('verify_wallet', 40):
        return jsonify({'error': '请求过于频繁'}), 429
    _prune_pending_wallet_nonces()
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体为空或 JSON 格式无效'}), 400
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')

    try:
        address = Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
        return jsonify({'error': '钱包地址格式无效'}), 400

    from eth_account.messages import encode_defunct
    from eth_account import Account

    user = User.query.filter_by(address=address).first()
    created_user = user is None
    nonce_value = None
    nonce_created_at = None
    if user:
        nonce_value = user.nonce
        nonce_created_at = user.nonce_created_at
    else:
        pending = _get_pending_wallet_nonce(address)
        if pending:
            nonce_value = pending.get('nonce')
            nonce_created_at = pending.get('created_at')
        if not nonce_value:
            _log_flow_event('wallet_verify_failed', address=address, reason='nonce_missing')
            return jsonify({'error': '签名挑战已失效，请重新获取'}), 401

    _nca = nonce_created_at if (nonce_created_at and nonce_created_at.tzinfo) else (nonce_created_at.replace(tzinfo=timezone.utc) if nonce_created_at else None)
    if not _nca or datetime.now(timezone.utc) - _nca > timedelta(minutes=WALLET_NONCE_TTL_MINUTES):
        _delete_pending_wallet_nonce(address)
        _log_flow_event('wallet_verify_failed', address=address, reason='nonce_expired')
        return jsonify({'error': '签名挑战已过期，请重新签名'}), 401

    msg_stripped = (message or '').strip()
    expected_old = f"Sign this message to login: {nonce_value}"
    expected_new_prefix = "Sign this message to login to "
    expected_new_suffix = f": {nonce_value}"
    valid = (
        msg_stripped == expected_old
        or (msg_stripped.startswith(expected_new_prefix) and msg_stripped.endswith(expected_new_suffix))
    )
    if not valid:
        _log_flow_event('wallet_verify_failed', address=address, reason='message_mismatch')
        return jsonify({'error': '签名消息格式不匹配'}), 400

    try:
        msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(msg, signature=signature)

        if recovered_address.lower() != address.lower():
             _log_flow_event('wallet_verify_failed', address=address, reason='signature_mismatch')
             return jsonify({'error': '签名无效'}), 401
    except Exception as e:
        print(f"Verify Error: {e}")
        _log_flow_event('wallet_verify_failed', address=address, reason='signature_exception')
        return jsonify({'error': '签名校验失败'}), 400

    if not user:
        try:
            user = _new_user(address=address, nickname=f"User_{address[:6]}", avatar=get_random_avatar())
            user.refresh_nonce()
            db.session.add(user)
            db.session.commit()
        except Exception:
            db.session.rollback()
            _log_flow_event('wallet_verify_failed', address=address, reason='user_create_failed')
            return jsonify({'error': '创建用户失败，请稍后重试'}), 500
        finally:
            _delete_pending_wallet_nonce(address)
    else:
        user.refresh_nonce()
        db.session.commit()

    token = issue_auth_token(user.id, JWT_EXPIRY_HOURS)
    _log_flow_event('wallet_verify_success', address=address, target_user_id=user.id, created_user=created_user)
    response = jsonify({'token': token, 'user': user.to_dict()})
    set_auth_cookie(response, token, max_age=JWT_EXPIRY_HOURS * 3600)
    return response


@auth_bp.route('/web2/register', methods=['POST'])
def register():
    if _rate_limit('register', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    try:
        data = request.get_json(silent=True) or {}
        if not data:
            return jsonify({'error': '请使用 JSON 提交（Content-Type: application/json）'}), 400
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '')
        if not username or not password:
            return jsonify({'error': '请填写用户名和密码'}), 400
        if len(username) > 50:
            return jsonify({'error': '用户名过长（最多50字）'}), 400
        if len(password) < 6:
            return jsonify({'error': '密码至少 6 位'}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({'error': '该用户名已被注册，请换一个或直接登录'}), 400

        try:
            user = _new_user(username=username, nickname=username, avatar=get_random_avatar())
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Register Error: {e}")
            return jsonify({'error': '注册失败，请稍后重试'}), 500

        token = issue_auth_token(user.id, JWT_EXPIRY_HOURS)
        response = jsonify({'token': token, 'user': user.to_dict()})
        response.status_code = 201
        set_auth_cookie(response, token, max_age=JWT_EXPIRY_HOURS * 3600)
        return response
    except Exception as e:
        print(f"Register Error: {e}")
        return jsonify({'error': '注册失败，请稍后重试'}), 500


@auth_bp.route('/web2/login', methods=['POST'])
def login():
    if _rate_limit('login', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体为空或 JSON 格式无效'}), 400
    username = (data.get('username') or '').strip()
    password = data.get('password')
    if not username:
        return jsonify({'error': '请填写用户名'}), 400
    if password is None:
        return jsonify({'error': '请填写密码'}), 400
    password = str(password).strip() if not isinstance(password, str) else password.strip()
    if not password:
        return jsonify({'error': '请填写密码'}), 400

    try:
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': '用户名或密码错误'}), 401
        if not getattr(user, 'password_hash', None):
            return jsonify({'error': '该账号为钱包登录，请使用钱包登录'}), 401
        if not user.check_password(password):
            return jsonify({'error': '用户名或密码错误'}), 401
        token = issue_auth_token(user.id, JWT_EXPIRY_HOURS)
        response = jsonify({'token': token, 'user': user.to_dict()})
        set_auth_cookie(response, token, max_age=JWT_EXPIRY_HOURS * 3600)
        return response
    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({'error': '用户名或密码错误'}), 401


@auth_bp.route('/logout', methods=['POST'])
def logout():
    response = jsonify({'message': '已退出登录'})
    clear_auth_cookie(response)
    return response


@auth_bp.route('/web2/change-password', methods=['POST'])
def change_password_no_login():
    """找回/修改密码：凭账号和原密码即可设置新密码，无需登录。限流防撞库。"""
    if _rate_limit('change_password', 5):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '缺少请求数据'}), 400
    username = data.get('username')
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    if not username or not old_password or not new_password:
        return jsonify({'error': '请填写用户名、原密码和新密码'}), 400
    if len(new_password) < 6:
        return jsonify({'error': '新密码至少 6 位'}), 400
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if not user.check_password(old_password):
        return jsonify({'error': '原密码错误'}), 401
    if not user.password_hash:
        return jsonify({'error': '该账号为钱包登录，无密码可修改'}), 400
    user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': '密码已修改，请用新密码登录'})
