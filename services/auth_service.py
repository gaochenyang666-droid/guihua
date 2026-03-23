import secrets
from datetime import datetime, timedelta, timezone

from web3 import Web3

from services.runtime_state import (
    prune_pending_wallet_nonces as _prune_pending_wallet_nonces,
    pending_wallet_nonce_redis_key as _pending_wallet_nonce_redis_key,
    set_pending_wallet_nonce as _set_pending_wallet_nonce,
    get_pending_wallet_nonce as _get_pending_wallet_nonce,
    delete_pending_wallet_nonce as _delete_pending_wallet_nonce,
)


class AuthFlowError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code


def make_auth_response(result, jsonify, set_auth_cookie, clear_auth_cookie):
    payload = result.get('payload') or {}
    response = jsonify(payload)
    response.status_code = result.get('status', 200)
    if result.get('token'):
        set_auth_cookie(response, result['token'], max_age=result.get('max_age'))
    if result.get('clear_cookie'):
        clear_auth_cookie(response)
    return response


def build_wallet_nonce_store_helpers(store, redis_client_getter, parse_iso_datetime, prefix='auth:pending_wallet_nonce:'):
    def prune(ttl_minutes, now=None):
        return _prune_pending_wallet_nonces(store, ttl_minutes, now=now)

    def set_nonce(address, nonce, ttl_minutes, created_at=None):
        redis_conn = redis_client_getter()
        return _set_pending_wallet_nonce(
            store,
            redis_conn,
            _pending_wallet_nonce_redis_key(prefix, address),
            ttl_minutes,
            address,
            nonce,
            created_at=created_at,
        )

    def get_nonce(address):
        redis_conn = redis_client_getter()
        return _get_pending_wallet_nonce(
            store,
            redis_conn,
            _pending_wallet_nonce_redis_key(prefix, address),
            address,
            parse_iso_datetime,
        )

    def delete_nonce(address):
        redis_conn = redis_client_getter()
        return _delete_pending_wallet_nonce(
            store,
            redis_conn,
            _pending_wallet_nonce_redis_key(prefix, address),
            address,
        )

    return {
        'prune': prune,
        'set': set_nonce,
        'get': get_nonce,
        'delete': delete_nonce,
    }


def _normalize_wallet_address(address):
    try:
        return Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
        raise AuthFlowError('钱包地址格式无效', 400, 'invalid_address')


def _coerce_utc(dt_value):
    if not dt_value:
        return None
    if getattr(dt_value, 'tzinfo', None):
        return dt_value
    return dt_value.replace(tzinfo=timezone.utc)


def _wallet_verify_message_matches(message, nonce_value):
    msg_stripped = (message or '').strip()
    expected_old = f'Sign this message to login: {nonce_value}'
    expected_new_prefix = 'Sign this message to login to '
    expected_new_suffix = f': {nonce_value}'
    return (
        msg_stripped == expected_old
        or (msg_stripped.startswith(expected_new_prefix) and msg_stripped.endswith(expected_new_suffix))
    )


def _recover_wallet_address(message, signature):
    from eth_account.messages import encode_defunct
    from eth_account import Account

    try:
        msg = encode_defunct(text=message)
        return Account.recover_message(msg, signature=signature)
    except Exception as exc:
        raise AuthFlowError('签名校验失败', 400, 'signature_exception') from exc


def issue_wallet_nonce(address_raw, *, user_model, db_session, log_event, nonce_helpers, ttl_minutes, nonce_factory=None):
    nonce_helpers['prune'](ttl_minutes)
    address = _normalize_wallet_address(address_raw)
    user = user_model.query.filter_by(address=address).first()
    if user:
        user.refresh_nonce()
        db_session.commit()
        log_event('wallet_nonce_issued', address=address, mode='existing_user')
        return {
            'status': 200,
            'payload': {'nonce': user.nonce},
        }

    nonce_factory = nonce_factory or (lambda: secrets.token_hex(16))
    nonce = nonce_factory()
    nonce_helpers['set'](address, nonce, ttl_minutes, created_at=datetime.now(timezone.utc))
    log_event('wallet_nonce_issued', address=address, mode='pending_user')
    return {
        'status': 200,
        'payload': {'nonce': nonce},
    }


def verify_wallet_signature(data, *, user_model, db_session, log_event, nonce_helpers, ttl_minutes, new_user_factory, avatar_factory, issue_auth_token_fn, jwt_expiry_hours):
    nonce_helpers['prune'](ttl_minutes)
    data = data or {}
    if not data:
        raise AuthFlowError('请求体为空或 JSON 格式无效', 400, 'invalid_json')

    address = _normalize_wallet_address(data.get('address'))
    signature = data.get('signature')
    message = data.get('message')

    user = user_model.query.filter_by(address=address).first()
    created_user = user is None

    nonce_value = None
    nonce_created_at = None
    if user:
        nonce_value = user.nonce
        nonce_created_at = user.nonce_created_at
    else:
        pending = nonce_helpers['get'](address)
        if pending:
            nonce_value = pending.get('nonce')
            nonce_created_at = pending.get('created_at')
        if not nonce_value:
            log_event('wallet_verify_failed', address=address, reason='nonce_missing')
            raise AuthFlowError('签名挑战已失效，请重新获取', 401, 'nonce_missing')

    nonce_created_at = _coerce_utc(nonce_created_at)
    if not nonce_created_at or datetime.now(timezone.utc) - nonce_created_at > timedelta(minutes=ttl_minutes):
        nonce_helpers['delete'](address)
        log_event('wallet_verify_failed', address=address, reason='nonce_expired')
        raise AuthFlowError('签名挑战已过期，请重新签名', 401, 'nonce_expired')

    if not _wallet_verify_message_matches(message, nonce_value):
        log_event('wallet_verify_failed', address=address, reason='message_mismatch')
        raise AuthFlowError('签名消息格式不匹配', 400, 'message_mismatch')

    recovered_address = _recover_wallet_address(message, signature)
    if recovered_address.lower() != address.lower():
        log_event('wallet_verify_failed', address=address, reason='signature_mismatch')
        raise AuthFlowError('签名无效', 401, 'signature_mismatch')

    if not user:
        try:
            user = new_user_factory(address=address, nickname=f'User_{address[:6]}', avatar=avatar_factory())
            user.refresh_nonce()
            db_session.add(user)
            db_session.commit()
        except Exception as exc:
            db_session.rollback()
            log_event('wallet_verify_failed', address=address, reason='user_create_failed')
            raise AuthFlowError('创建用户失败，请稍后重试', 500, 'user_create_failed') from exc
        finally:
            nonce_helpers['delete'](address)
    else:
        user.refresh_nonce()
        db_session.commit()

    token = issue_auth_token_fn(user.id, jwt_expiry_hours)
    log_event('wallet_verify_success', address=address, target_user_id=user.id, created_user=created_user)
    return {
        'status': 200,
        'payload': {'token': token, 'user': user.to_dict()},
        'token': token,
        'max_age': jwt_expiry_hours * 3600,
    }


def register_web2_user(data, *, user_model, db_session, log_event, new_user_factory, avatar_factory, issue_auth_token_fn, jwt_expiry_hours):
    data = data or {}
    if not data:
        raise AuthFlowError('请使用 JSON 提交（Content-Type: application/json）', 400, 'invalid_json')
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '')
    if not username or not password:
        raise AuthFlowError('请填写用户名和密码', 400, 'missing_credentials')
    if len(username) > 50:
        raise AuthFlowError('用户名过长（最多50字）', 400, 'username_too_long')
    if len(password) < 6:
        raise AuthFlowError('密码至少 6 位', 400, 'password_too_short')
    if user_model.query.filter_by(username=username).first():
        raise AuthFlowError('该用户名已被注册，请换一个或直接登录', 400, 'username_taken')

    try:
        user = new_user_factory(username=username, nickname=username, avatar=avatar_factory())
        user.set_password(password)
        db_session.add(user)
        db_session.commit()
    except Exception as exc:
        db_session.rollback()
        log_event('web2_register_failed', username=username, reason='db_error')
        raise AuthFlowError('注册失败，请稍后重试', 500, 'register_failed') from exc

    token = issue_auth_token_fn(user.id, jwt_expiry_hours)
    log_event('web2_register_success', target_user_id=user.id, username=username)
    return {
        'status': 201,
        'payload': {'token': token, 'user': user.to_dict()},
        'token': token,
        'max_age': jwt_expiry_hours * 3600,
    }


def login_web2_user(data, *, user_model, log_event, issue_auth_token_fn, jwt_expiry_hours):
    data = data or {}
    if not data:
        raise AuthFlowError('请求体为空或 JSON 格式无效', 400, 'invalid_json')
    username = (data.get('username') or '').strip()
    password = data.get('password')
    if not username:
        raise AuthFlowError('请填写用户名', 400, 'missing_username')
    if password is None:
        raise AuthFlowError('请填写密码', 400, 'missing_password')
    password = str(password).strip() if not isinstance(password, str) else password.strip()
    if not password:
        raise AuthFlowError('请填写密码', 400, 'missing_password')

    user = user_model.query.filter_by(username=username).first()
    if not user:
        log_event('web2_login_failed', username=username, reason='user_missing')
        raise AuthFlowError('用户名或密码错误', 401, 'invalid_credentials')
    if not getattr(user, 'password_hash', None):
        raise AuthFlowError('该账号为钱包登录，请使用钱包登录', 401, 'wallet_only_account')
    if not user.check_password(password):
        log_event('web2_login_failed', username=username, reason='password_mismatch', target_user_id=user.id)
        raise AuthFlowError('用户名或密码错误', 401, 'invalid_credentials')
    if getattr(user, 'is_banned', False):
        raise AuthFlowError('账号已被封禁', 403, 'user_banned')

    token = issue_auth_token_fn(user.id, jwt_expiry_hours)
    log_event('web2_login_success', username=username, target_user_id=user.id)
    return {
        'status': 200,
        'payload': {'token': token, 'user': user.to_dict()},
        'token': token,
        'max_age': jwt_expiry_hours * 3600,
    }


def logout_user():
    return {
        'status': 200,
        'payload': {'message': '已退出登录'},
        'clear_cookie': True,
    }


def change_web2_password(data, *, user_model, db_session, log_event):
    data = data or {}
    if not data:
        raise AuthFlowError('缺少请求数据', 400, 'missing_payload')
    username = data.get('username')
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    if not username or not old_password or not new_password:
        raise AuthFlowError('请填写用户名、原密码和新密码', 400, 'missing_fields')
    if len(new_password) < 6:
        raise AuthFlowError('新密码至少 6 位', 400, 'password_too_short')
    user = user_model.query.filter_by(username=username).first()
    if not user:
        raise AuthFlowError('用户不存在', 404, 'user_missing')
    if not user.check_password(old_password):
        log_event('web2_change_password_failed', username=username, target_user_id=user.id, reason='password_mismatch')
        raise AuthFlowError('原密码错误', 401, 'password_mismatch')
    if not user.password_hash:
        raise AuthFlowError('该账号为钱包登录，无密码可修改', 400, 'wallet_only_account')
    user.set_password(new_password)
    db_session.commit()
    log_event('web2_change_password_success', username=username, target_user_id=user.id)
    return {
        'status': 200,
        'payload': {'message': '密码已修改，请用新密码登录'},
    }
