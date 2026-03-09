# 安全与工具：JWT 装饰器、限流、HTML 清洗
import time
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


def _rate_limit(key_prefix, max_per_minute=5):
    ip = (request.remote_addr or 'unknown').strip()
    key = f"{key_prefix}:{ip}"
    now = time.time()
    if key not in _rate_limit_store:
        _rate_limit_store[key] = []
    times = _rate_limit_store[key]
    times[:] = [t for t in times if now - t < 60]
    if len(times) >= max_per_minute:
        return True
    times.append(now)
    return False


def _bearer_token():
    auth = request.headers.get('Authorization')
    if not auth or not auth.startswith('Bearer '):
        return None
    return auth[7:]


def _get_optional_jwt_payload():
    token = _bearer_token()
    if not token:
        return None
    try:
        return jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
    except Exception:
        return None


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _bearer_token()
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        try:
            data = jwt.decode(token, current_app.config['SECRET_KEY'], algorithms=['HS256'])
            user = User.query.get(data['user_id'])
            if not user:
                return jsonify({'error': 'User not found'}), 401
            if user.is_banned:
                return jsonify({'error': 'Account has been banned'}), 403
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except Exception:
            return jsonify({'error': 'Token is invalid'}), 401
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user.is_admin:
            return jsonify({'error': 'Admin privilege required'}), 403
        return f(*args, **kwargs)
    return decorated


def bleach_clean_post_content(html):
    if not html:
        return ''
    return bleach.clean(html, tags=POST_CONTENT_TAGS, attributes=POST_CONTENT_ATTRS, strip=True)
