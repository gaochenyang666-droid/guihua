# 安全与工具：JWT 装饰器、限流、HTML 清洗
import os
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
import jwt
import bleach
from flask import request, g, jsonify, current_app

from models import User


# 帖子正文 HTML 白名单（与 Quill 输出对齐，保留图文混排）
POST_CONTENT_TAGS = [
    'b', 'strong', 'i', 'em', 'u',
    'img', 'p', 'br', 'div', 'span',
    'a', 'ol', 'ul', 'li', 'blockquote', 'pre', 'code',
    'h1', 'h2', 'h3'
]
POST_CONTENT_ATTRS = {
    'img': ['src', 'alt', 'style', 'class', 'width', 'height'],
    'a': ['href', 'target', 'rel', 'class', 'style'],
    '*': ['class', 'style']
}

_rate_limit_store = {}
_redis_client = None
AUTH_COOKIE_NAME = 'guihua_auth'


def _get_redis_client():
    global _redis_client
    if _redis_client is not None:
        return _redis_client
    redis_url = (os.environ.get('REDIS_URL') or '').strip()
    if not redis_url:
        _redis_client = False
        return None
    try:
        import redis
        _redis_client = redis.from_url(redis_url, decode_responses=True)
        _redis_client.ping()
        return _redis_client
    except Exception:
        _redis_client = False
        return None


def get_redis_status():
    redis_conn = _get_redis_client()
    if redis_conn:
        return {
            'status': 'ok',
            'message': 'Redis 已连接，限流与状态存储为共享模式',
            'configured': True,
            'readiness': 'ready',
            'required_in_production': True,
            'degraded': False,
            'recommendation': '当前状态正常，可作为生产正式依赖使用。',
        }
    return {
        'status': 'fallback',
        'message': 'Redis 未配置或不可用，当前退化为进程内 fallback',
        'configured': False,
        'readiness': 'readiness_gap',
        'required_in_production': True,
        'degraded': True,
        'recommendation': '请在线上配置 REDIS_URL，避免限流、nonce 与防刷退化为进程内模式。',
    }


def _rate_limit(key_prefix, max_per_minute=5):
    ip = (request.remote_addr or 'unknown').strip()
    key = f"{key_prefix}:{ip}"
    now = time.time()
    redis_conn = _get_redis_client()
    if redis_conn:
        try:
            ttl = 60
            val = redis_conn.incr(key)
            if val == 1:
                redis_conn.expire(key, ttl)
            return val > max_per_minute
        except Exception:
            pass
    if key not in _rate_limit_store:
        _rate_limit_store[key] = []
    times = _rate_limit_store[key]
    times[:] = [t for t in times if now - t < 60]
    if len(times) >= max_per_minute:
        return True
    times.append(now)
    return False


def _auth_cookie_token():
    token = request.cookies.get(AUTH_COOKIE_NAME)
    return token or None


def _request_token():
    auth = request.headers.get('Authorization')
    if auth and auth.startswith('Bearer '):
        return auth[7:]
    return _auth_cookie_token()


def _bearer_token():
    return _request_token()


def _decode_jwt_token(token):
    return jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])


def issue_auth_token(user_id, expiry_hours=None):
    hours = expiry_hours if expiry_hours is not None else current_app.config.get('JWT_EXPIRY_HOURS', 24)
    return jwt.encode({
        'user_id': user_id,
        'exp': datetime.now(timezone.utc) + timedelta(hours=hours)
    }, current_app.config['SECRET_KEY'], algorithm='HS256')


def _should_secure_auth_cookie():
    if request.is_secure:
        return True
    forwarded_proto = (request.headers.get('X-Forwarded-Proto') or '').strip().lower()
    return forwarded_proto == 'https'


def set_auth_cookie(response, token, max_age=None):
    if max_age is None:
        max_age = int(current_app.config.get('JWT_EXPIRY_HOURS', 24) * 3600)
    response.set_cookie(
        AUTH_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        secure=_should_secure_auth_cookie(),
        samesite='Lax',
        path='/'
    )
    return response


def clear_auth_cookie(response):
    response.set_cookie(
        AUTH_COOKIE_NAME,
        '',
        expires=0,
        max_age=0,
        httponly=True,
        secure=_should_secure_auth_cookie(),
        samesite='Lax',
        path='/'
    )
    return response


def _get_optional_jwt_payload():
    token = _request_token()
    if not token:
        return None
    try:
        return _decode_jwt_token(token)
    except Exception:
        return None


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _request_token()
        if not token:
            return jsonify({'error': '登录已失效，请重新登录'}), 401
        try:
            data = _decode_jwt_token(token)
            user = User.query.get(data['user_id'])
            if not user:
                return jsonify({'error': '用户不存在或登录已失效'}), 401
            if user.is_banned:
                return jsonify({'error': '账号已被封禁'}), 403
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'error': '登录已过期，请重新登录'}), 401
        except Exception:
            return jsonify({'error': '登录状态无效，请重新登录'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user.is_admin:
            return jsonify({'error': '需要管理员权限'}), 403
        return f(*args, **kwargs)
    return decorated


def bleach_clean_post_content(html):
    if not html:
        return ''
    return bleach.clean(html, tags=POST_CONTENT_TAGS, attributes=POST_CONTENT_ATTRS, strip=True)
