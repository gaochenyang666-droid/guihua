from flask import Blueprint, request, jsonify

from extensions import db
from models import User, get_random_avatar
from utils.security import (
    _rate_limit, set_auth_cookie, clear_auth_cookie, issue_auth_token,
    _get_redis_client,
)
from services.observability import log_flow_event as _log_flow_event
from services.app_support import parse_iso_datetime
from services.user_factory import new_user as _new_user
from services.auth_service import (
    AuthFlowError,
    build_wallet_nonce_store_helpers,
    make_auth_response,
    issue_wallet_nonce as _svc_issue_wallet_nonce,
    verify_wallet_signature as _svc_verify_wallet_signature,
    register_web2_user as _svc_register_web2_user,
    login_web2_user as _svc_login_web2_user,
    logout_user as _svc_logout_user,
    change_web2_password as _svc_change_web2_password,
)

auth_bp = Blueprint('auth', __name__, url_prefix='/api/auth')

WALLET_NONCE_TTL_MINUTES = 5
JWT_EXPIRY_HOURS = 24

_pending_wallet_nonces = {}
_wallet_nonce_helpers = build_wallet_nonce_store_helpers(
    _pending_wallet_nonces,
    _get_redis_client,
    parse_iso_datetime,
)


def _handle_auth_flow(run_flow, *, use_cookie_response=False):
    try:
        result = run_flow()
        if use_cookie_response:
            return make_auth_response(result, jsonify, set_auth_cookie, clear_auth_cookie)
        return jsonify(result['payload']), result['status']
    except AuthFlowError as exc:
        return jsonify({'error': exc.message}), exc.status


@auth_bp.route('/nonce', methods=['GET'])
def get_nonce():
    if _rate_limit('nonce', 30):
        return jsonify({'error': '请求过于频繁'}), 429
    return _handle_auth_flow(lambda: _svc_issue_wallet_nonce(
            request.args.get('address'),
            user_model=User,
            db_session=db.session,
            log_event=_log_flow_event,
            nonce_helpers=_wallet_nonce_helpers,
            ttl_minutes=WALLET_NONCE_TTL_MINUTES,
        ))


@auth_bp.route('/verify', methods=['POST'])
def verify_signature():
    if _rate_limit('verify_wallet', 40):
        return jsonify({'error': '请求过于频繁'}), 429
    return _handle_auth_flow(lambda: _svc_verify_wallet_signature(
            request.get_json(silent=True) or {},
            user_model=User,
            db_session=db.session,
            log_event=_log_flow_event,
            nonce_helpers=_wallet_nonce_helpers,
            ttl_minutes=WALLET_NONCE_TTL_MINUTES,
            new_user_factory=_new_user,
            avatar_factory=get_random_avatar,
            issue_auth_token_fn=issue_auth_token,
            jwt_expiry_hours=JWT_EXPIRY_HOURS,
        ), use_cookie_response=True)


@auth_bp.route('/web2/register', methods=['POST'])
def register():
    if _rate_limit('register', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    return _handle_auth_flow(lambda: _svc_register_web2_user(
            request.get_json(silent=True) or {},
            user_model=User,
            db_session=db.session,
            log_event=_log_flow_event,
            new_user_factory=_new_user,
            avatar_factory=get_random_avatar,
            issue_auth_token_fn=issue_auth_token,
            jwt_expiry_hours=JWT_EXPIRY_HOURS,
        ), use_cookie_response=True)


@auth_bp.route('/web2/login', methods=['POST'])
def login():
    if _rate_limit('login', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    return _handle_auth_flow(lambda: _svc_login_web2_user(
            request.get_json(silent=True) or {},
            user_model=User,
            log_event=_log_flow_event,
            issue_auth_token_fn=issue_auth_token,
            jwt_expiry_hours=JWT_EXPIRY_HOURS,
        ), use_cookie_response=True)


@auth_bp.route('/logout', methods=['POST'])
def logout():
    result = _svc_logout_user()
    return make_auth_response(result, jsonify, set_auth_cookie, clear_auth_cookie)


@auth_bp.route('/web2/change-password', methods=['POST'])
def change_password_no_login():
    if _rate_limit('change_password', 5):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    return _handle_auth_flow(lambda: _svc_change_web2_password(
            request.get_json(silent=True) or {},
            user_model=User,
            db_session=db.session,
            log_event=_log_flow_event,
        ))
