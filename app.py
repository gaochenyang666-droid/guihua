import os
import re
import json
import traceback
import hashlib
import secrets
import threading
import bleach
import base64
import random
import time
from datetime import datetime, timedelta, timezone
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, g, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from web3 import Web3
try:
    from web3.middleware.geth_poa import geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware  # web3 v6
import arweave
from arweave.arweave_lib import Wallet, Transaction

# Load environment variables
load_dotenv()

app = Flask(__name__)
_cors_origins_env = (os.environ.get('CORS_ORIGINS') or '').strip()
if _cors_origins_env:
    _cors_origins = [o.strip() for o in _cors_origins_env.split(',') if o.strip()]
    CORS(app, resources={r"/api/*": {"origins": _cors_origins}})
elif os.environ.get('FLASK_DEBUG', 'false').lower() == 'true':
    CORS(app, resources={r"/api/*": {"origins": [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:5173',
        'http://127.0.0.1:5173'
    ]}})
else:
    print("CORS disabled by default in production. Set CORS_ORIGINS to enable cross-origin API access.")

# ImgBB Configuration
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY')
if not IMGBB_API_KEY:
    print("Warning: IMGBB_API_KEY not set")

# Arweave Configuration
ARWEAVE_GATEWAY = 'https://arweave.net'

# Database Configuration（SQLite 建议用绝对路径，避免重启后工作目录变化导致数据“丢失”）
basedir = os.path.abspath(os.path.dirname(__file__))
_db_url = os.environ.get('DATABASE_URL', '').strip() or None
if _db_url and _db_url.startswith('sqlite:///') and not _db_url.startswith('sqlite:////'):
    # 相对路径如 sqlite:///guijing.db 转为基于项目目录的绝对路径，防止重启后 cwd 不同导致丢数据
    _rel = _db_url.replace('sqlite:///', '')
    if _rel and not os.path.isabs(_rel):
        _db_url = 'sqlite:///' + os.path.join(basedir, _rel)
if not _db_url:
    _db_url = 'sqlite:///' + os.path.join(basedir, 'guijing.db')
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# timeout 仅用于 SQLite（防锁库）；PostgreSQL 不支持该 DSN 选项，否则会报 invalid connection option "timeout"
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'timeout': 30} if _db_url.startswith('sqlite') else {}
}

# SECRET_KEY 仅从环境变量读取，禁止写入本地文件（云环境 Ephemeral 盘会导致重启后 JWT 全部失效）
app.config['SECRET_KEY'] = (os.environ.get('SECRET_KEY') or '').strip()
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY 未设置。请在环境变量中配置 SECRET_KEY 后启动应用。")

# BSC Mainnet Configuration（发帖费收 USDT）
BSC_RPC_LIST = [
    os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/'),
    'https://bsc-dataseed1.defibit.io/',
    'https://bsc-dataseed1.ninicoin.io/',
    'https://bsc.publicnode.com'
]

# JWT 过期时间（小时）；上线后可按需改为 24
JWT_EXPIRY_HOURS = 24
# 钱包签名挑战有效期（分钟）
WALLET_NONCE_TTL_MINUTES = 5
# 支付校验：要求交易已被至少 N 个区块确认，防链重组假充值。BSC 约 3 秒/块，2 约 6 秒
TX_CONFIRMATIONS_NEEDED = 2
# 发帖费：1 人民币等值 USDT（取价失败时用 POST_FEE_USDT 兜底，单位 USDT）
POST_FEE_CNY = float(os.environ.get('POST_FEE_CNY', '1').strip() or '1')
POST_FEE_USDT_FALLBACK = float(os.environ.get('POST_FEE_USDT', '0.14').strip() or '0.14')
# BSC 主网 USDT 合约（Binance-Peg BSC-USD），18 位小数
USDT_CONTRACT_BSC = (os.environ.get('USDT_CONTRACT_ADDRESS') or '0x55d398326f99059fF775485246999027B3197955').strip()
USDT_DECIMALS = 18
app.config['BSC'] = {
    'RPC_URL': BSC_RPC_LIST[0],
    'CHAIN_ID': 56,
    'RECEIVE_ADDRESS': os.environ.get('RECEIVE_ADDRESS'),
    'USDT_CONTRACT_ADDRESS': USDT_CONTRACT_BSC,
    'USDT_DECIMALS': USDT_DECIMALS,
    'POST_FEE_CNY': POST_FEE_CNY,
    'POST_FEE_USDT_FALLBACK': POST_FEE_USDT_FALLBACK,
}
app.config['BSC_RPC_LIST'] = BSC_RPC_LIST
app.config['TX_CONFIRMATIONS_NEEDED'] = TX_CONFIRMATIONS_NEEDED
app.config['IMGBB_API_KEY'] = IMGBB_API_KEY
app.config['ARWEAVE_GATEWAY'] = ARWEAVE_GATEWAY
app.config['SEED_ARTICLE_PATH'] = os.path.join(basedir, 'seeds', 'default_article_huaxiansheng.html')


def _build_csp_header():
    # 当前项目仍使用内联事件与第三方 CDN 脚本，因此先启用兼容型 CSP，
    # 先收紧可被明显滥用的能力，再逐步把 inline/eval 从前端结构里移除。
    directives = {
        "default-src": ["'self'"],
        "base-uri": ["'self'"],
        "object-src": ["'none'"],
        "frame-ancestors": ["'self'"],
        "form-action": ["'self'"],
        "script-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdnjs.cloudflare.com",
        ],
        "style-src": [
            "'self'",
            "'unsafe-inline'",
            "https://cdnjs.cloudflare.com",
        ],
        "img-src": [
            "'self'",
            "data:",
            "blob:",
            "https:",
        ],
        "font-src": [
            "'self'",
            "data:",
            "https://cdnjs.cloudflare.com",
        ],
        "connect-src": [
            "'self'",
            "https:",
            "wss:",
        ],
        "media-src": [
            "'self'",
            "blob:",
            "https:",
        ],
    }
    return '; '.join(key + ' ' + ' '.join(values) for key, values in directives.items())


@app.after_request
def _apply_security_headers(response):
    response.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    response.headers.setdefault('Content-Security-Policy', _build_csp_header())
    return response

# 未注册地址的临时签名挑战（地址 -> {nonce, created_at}）
_pending_wallet_nonces = {}
_pending_wallet_nonce_redis_prefix = 'auth:pending_wallet_nonce:'


def _prune_pending_wallet_nonces(now=None):
    _svc_prune_pending_wallet_nonces(_pending_wallet_nonces, WALLET_NONCE_TTL_MINUTES, now=now)


def _pending_wallet_nonce_redis_key(address):
    return _svc_pending_wallet_nonce_redis_key(_pending_wallet_nonce_redis_prefix, address)


def _set_pending_wallet_nonce(address, nonce, created_at=None):
    redis_conn = _get_redis_client()
    return _svc_set_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _pending_wallet_nonce_redis_key(address),
        WALLET_NONCE_TTL_MINUTES,
        address,
        nonce,
        created_at=created_at,
    )


def _get_pending_wallet_nonce(address):
    redis_conn = _get_redis_client()
    return _svc_get_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _pending_wallet_nonce_redis_key(address),
        address,
        _parse_iso_datetime,
    )


def _delete_pending_wallet_nonce(address):
    redis_conn = _get_redis_client()
    return _svc_delete_pending_wallet_nonce(
        _pending_wallet_nonces,
        redis_conn,
        _pending_wallet_nonce_redis_key(address),
        address,
    )

from extensions import db
db.init_app(app)

# 区块链与存储逻辑已拆至 services/blockchain.py、services/storage.py
from models import (User, Post, Vote, Comment, Like, CommentLike, Bookmark, Notification, UsedTransaction,
    PendingPublication,
    FlowEvent, UserVote, Tip, Report, Announcement, AdminAuditLog, CheckinLog, AppSetting, Series, SeriesPost,
    build_comment_tree, _comment_to_dict_node, get_random_avatar, ALLOWED_AVATARS,
    calc_level_info, checkin_exp_by_streak)
from utils.security import (_rate_limit, _bearer_token, _get_optional_jwt_payload,
    token_required, admin_required, _get_redis_client, set_auth_cookie,
    clear_auth_cookie, issue_auth_token, bleach_clean_post_content as _bleach_clean_post_content)
from services.storage import (upload_to_imgbb, upload_to_arweave_native, upload_to_arweave_with_retry)
from services.blockchain import (get_post_fee_usdt_raw, verify_transaction, inspect_transaction_status as _svc_inspect_transaction_status)
from services.posts_query import (
    apply_default_post_order as _posts_apply_default_post_order,
    build_posts_payload as _build_posts_payload,
    get_posts_fallback as _posts_get_posts_fallback,
)
from services.user_progress import (
    china_today as _svc_china_today,
    get_user_level as _svc_get_user_level,
    build_group_links_for_user as _svc_build_group_links_for_user,
    build_legacy_achievements as _svc_build_legacy_achievements,
    build_achievements_for_user as _svc_build_achievements_for_user,
    build_checkin_status as _svc_build_checkin_status,
)
from services.posts_logic import (
    build_post_precheck as _svc_build_post_precheck,
    normalize_tags as _svc_normalize_tags,
    extract_mention_tokens as _svc_extract_mention_tokens,
    resolve_mentioned_users as _svc_resolve_mentioned_users,
    series_can_view as _svc_series_can_view,
    series_can_edit as _svc_series_can_edit,
)
from services.app_support import (
    parse_iso_datetime as _svc_parse_iso_datetime,
    humanize_verify_error as _svc_humanize_verify_error,
    is_post_permanent as _svc_is_post_permanent,
    tip_amount_to_usdt_str as _svc_tip_amount_to_usdt_str,
    compute_asset_version as _svc_compute_asset_version,
    load_text_file as _svc_load_text_file,
)
from services.site_settings import (
    get_setting_value as _svc_get_setting_value,
    set_setting_value as _svc_set_setting_value,
    get_group_link_urls as _svc_get_group_link_urls,
    validate_group_link_urls as _svc_validate_group_link_urls,
)
from services.publish_recovery import (
    upsert_pending_publication as _svc_upsert_pending_publication,
    clear_pending_publication as _svc_clear_pending_publication,
    get_latest_pending_publication as _svc_get_latest_pending_publication,
)
from services.runtime_state import (
    prune_pending_wallet_nonces as _svc_prune_pending_wallet_nonces,
    pending_wallet_nonce_redis_key as _svc_pending_wallet_nonce_redis_key,
    set_pending_wallet_nonce as _svc_set_pending_wallet_nonce,
    get_pending_wallet_nonce as _svc_get_pending_wallet_nonce,
    delete_pending_wallet_nonce as _svc_delete_pending_wallet_nonce,
    allow_view_count_increment as _svc_allow_view_count_increment,
)
from services.startup_tasks import (
    ensure_bootstrap_admin as _svc_ensure_bootstrap_admin,
    seed_default_article as _svc_seed_default_article,
    ensure_table as _svc_ensure_table,
    check_receive_address as _svc_check_receive_address,
    warn_if_redis_missing as _svc_warn_if_redis_missing,
    should_run_init_db as _svc_should_run_init_db,
)
from services.schema_compat import (
    ensure_users_wallet_address as _svc_ensure_users_wallet_address,
    ensure_users_withdrawable_balance as _svc_ensure_users_withdrawable_balance,
    ensure_users_checkin_columns as _svc_ensure_users_checkin_columns,
    ensure_posts_tx_nullable as _svc_ensure_posts_tx_nullable,
    ensure_posts_pin_columns as _svc_ensure_posts_pin_columns,
    ensure_posts_special_column as _svc_ensure_posts_special_column,
    ensure_posts_tags_column as _svc_ensure_posts_tags_column,
    ensure_notifications_columns as _svc_ensure_notifications_columns,
    ensure_reports_columns as _svc_ensure_reports_columns,
    ensure_announcements_columns as _svc_ensure_announcements_columns,
)
from services.observability import log_event as _svc_log_event
from services.ops_monitor import build_ops_summary as _svc_build_ops_summary
from services.publish_compensation import (
    run_compensation_batch as _svc_run_compensation_batch,
    start_compensation_worker as _svc_start_compensation_worker,
    compensation_interval_seconds as _svc_compensation_interval_seconds,
    should_start_compensation_worker as _svc_should_start_compensation_worker,
)


def _new_user(**kwargs):
    """SQLite 上 BigInteger 主键不自增，创建用户时补一个递增 ID。"""
    if db.engine.dialect.name == 'sqlite' and not kwargs.get('id'):
        max_id = db.session.query(func.max(User.id)).scalar()
        seed = int(datetime.utcnow().strftime('%Y') + '1000000')
        next_id = int(max_id) + 1 if max_id else seed
        kwargs['id'] = next_id
    return User(**kwargs)


CHECKIN_STREAK_BONUS_DAYS = 3
CHECKIN_STREAK_BONUS_EXP = 3


BASE_ACHIEVEMENT_DEFINITIONS = [
    {
        'key': 'report_privilege',
        'title': '举报权限',
        'description': '等级达到 2 可使用快捷举报按钮',
        'min_level': 2,
        'wearable': False,
        'group_key': None
    },
    {
        'key': 'wearable_unlock',
        'title': '成就佩戴权限',
        'description': '等级达到 3 可佩戴成就（一次仅 1 个）',
        'min_level': 3,
        'wearable': False,
        'group_key': None
    },
    {
        'key': 'co_create_group',
        'title': '共创群资格',
        'description': '等级达到 5 可加入 Telegram 共创群',
        'min_level': 5,
        'wearable': True,
        'group_key': 'co_create'
    },
    {
        'key': 'core_group',
        'title': '核心群资格',
        'description': '等级达到 10 可加入 Telegram 核心群',
        'min_level': 10,
        'wearable': True,
        'group_key': 'core'
    }
]
LEGACY_ACHIEVEMENT_DEFINITIONS = [
    {'key': 'legacy_new_soul', 'title': '新魂', 'description': '初入诡话世界', 'wearable': True},
    {'key': 'legacy_chain_traveler', 'title': '链上旅人', 'description': '完成钱包绑定', 'wearable': True},
    {'key': 'legacy_wallet_bound', 'title': '钱包绑定', 'description': '完成钱包绑定', 'wearable': True},
    {'key': 'legacy_dual_identity', 'title': '双界行者', 'description': '同时拥有 Web2 与钱包身份', 'wearable': True},
    {'key': 'legacy_contract_psychic', 'title': '结契通灵者', 'description': '完成 Web2 与钱包绑定并发布帖子', 'wearable': True},
    {'key': 'legacy_first_post', 'title': '首帖达成', 'description': '发布第一篇帖子', 'wearable': True},
    {'key': 'legacy_post_10', 'title': '十帖异闻录', 'description': '累计发布 10 篇帖子', 'wearable': True},
    {'key': 'legacy_post_100', 'title': '百帖引魂者', 'description': '累计发布 100 篇帖子', 'wearable': True},
    {'key': 'legacy_post_1000', 'title': '千帖通灵者', 'description': '累计发布 1000 篇帖子', 'wearable': True},
    {'key': 'legacy_year_1', 'title': '一年见习者', 'description': '账号满 1 年', 'wearable': True},
    {'key': 'legacy_year_5', 'title': '五年夜巡者', 'description': '账号满 5 年', 'wearable': True},
    {'key': 'legacy_year_10', 'title': '十年守秘人', 'description': '账号满 10 年', 'wearable': True},
    {'key': 'legacy_admin_guardian', 'title': '守夜人', 'description': '管理员专属称号', 'wearable': True},
]
TELEGRAM_GROUP_SETTING_KEYS = {
    'co_create': 'telegram_group_co_create_url',
    'core': 'telegram_group_core_url'
}


def _get_user_level(user):
    return _svc_get_user_level(user, calc_level_info)


def _get_setting_value(setting_key, default_value=''):
    return _svc_get_setting_value(AppSetting, setting_key, default_value)


def _set_setting_value(setting_key, setting_value):
    return _svc_set_setting_value(db.session, AppSetting, setting_key, setting_value)


def _build_group_links_for_user(user):
    co_url = _get_setting_value(TELEGRAM_GROUP_SETTING_KEYS['co_create'], '')
    core_url = _get_setting_value(TELEGRAM_GROUP_SETTING_KEYS['core'], '')
    return _svc_build_group_links_for_user(user, co_url, core_url, calc_level_info)


def _build_legacy_achievements(user, is_admin=False):
    try:
        post_count = Post.query.filter_by(author_id=user.id).count()
    except Exception:
        post_count = 0
    return _svc_build_legacy_achievements(user, LEGACY_ACHIEVEMENT_DEFINITIONS, post_count, is_admin=is_admin)


def _build_achievements_for_user(user):
    try:
        post_count = Post.query.filter_by(author_id=user.id).count()
    except Exception:
        post_count = 0
    return _svc_build_achievements_for_user(
        user,
        BASE_ACHIEVEMENT_DEFINITIONS,
        LEGACY_ACHIEVEMENT_DEFINITIONS,
        post_count,
        calc_level_info
    )


def _compute_asset_version():
    """Static asset version for cache-busting on CDN/browser."""
    return _svc_compute_asset_version(
        basedir,
        override=(os.environ.get('ASSET_VERSION') or '').strip()
    )


_ASSET_VERSION = _compute_asset_version()


@app.context_processor
def inject_asset_version():
    return {'asset_version': _ASSET_VERSION}

# ============== Routes ==============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/studio')
def studio():
    return render_template('studio.html')

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/profile')
def profile():
    return render_template('profile.html')


@app.route('/series/<int:series_id>')
def series_page(series_id):
    return render_template('series.html', series_id=series_id)

@app.route('/post/<int:post_id>')
def post_page(post_id):
    return render_template('post.html', post_id=post_id)

@app.route('/notices')
def notices_page():
    notice_type = (request.args.get('type') or 'announcement').strip().lower()
    if notice_type not in ('announcement', 'activity'):
        notice_type = 'announcement'
    return render_template('notice_center.html', notice_type=notice_type)

@app.route('/notifications')
def notifications_page():
    return render_template('notifications.html')

# --- Auth ---

@app.route('/api/auth/nonce', methods=['GET'])
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
        # 已有用户：使用数据库 nonce
        user.refresh_nonce()
        db.session.commit()
        _log_flow_event('wallet_nonce_issued', address=address, mode='existing_user')
        return jsonify({'nonce': user.nonce})

    # 未注册用户：仅下发临时挑战，不预先建号（防刷库）
    nonce = secrets.token_hex(16)
    _set_pending_wallet_nonce(address, nonce, datetime.utcnow())
    _log_flow_event('wallet_nonce_issued', address=address, mode='pending_user')
    return jsonify({'nonce': nonce})

@app.route('/api/auth/verify', methods=['POST'])
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
    
    # In production, verify signature here using web3
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

    # Check nonce expiration
    if not nonce_created_at or datetime.utcnow() - nonce_created_at > timedelta(minutes=WALLET_NONCE_TTL_MINUTES):
        _delete_pending_wallet_nonce(address)
        _log_flow_event('wallet_verify_failed', address=address, reason='nonce_expired')
        return jsonify({'error': '签名挑战已过期，请重新签名'}), 401

    # 严格全文本匹配，防止假站用同一 nonce 骗用户签名后到本站登录
    # 支持两种格式：旧版 "Sign this message to login: {nonce}"，新版 "Sign this message to login to {host}: {nonce}"
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
    
    # 首次验签成功才建号，并轮换 nonce 防重放
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

@app.route('/api/auth/web2/register', methods=['POST'])
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

@app.route('/api/auth/web2/login', methods=['POST'])
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


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    response = jsonify({'message': '已退出登录'})
    clear_auth_cookie(response)
    return response

@app.route('/api/auth/web2/change-password', methods=['POST'])
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

@app.route('/api/user/me', methods=['GET', 'PUT'])
@token_required
def user_me():
    if request.method == 'GET':
        return jsonify(g.current_user.to_dict())
    
    # PUT: Update profile
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
        
    nickname = data.get('nickname')
    bio = data.get('bio')
    avatar = data.get('avatar')
    refresh_avatar = data.get('refresh_avatar', False)
    if 'show_tip_thanks' in data:
        g.current_user.show_tip_thanks = bool(data.get('show_tip_thanks'))
    
    if nickname:
        if len(nickname) > 50: return jsonify({'error': '昵称过长'}), 400
        g.current_user.nickname = bleach.clean(nickname, strip=True)
        
    if bio is not None:
        if len(bio) > 500: return jsonify({'error': '简介过长'}), 400
        g.current_user.bio = bleach.clean(bio, strip=True)
        
    if avatar:
        if avatar not in ALLOWED_AVATARS:
            return jsonify({'error': '头像无效，仅支持系统内表情头像'}), 400
        g.current_user.avatar = avatar
    elif refresh_avatar:
        g.current_user.avatar = get_random_avatar()
        
    db.session.commit()
    return jsonify({'message': '资料已更新', 'user': g.current_user.to_dict()})


@app.route('/api/user/settings', methods=['GET', 'PUT'])
@token_required
def user_settings():
    if request.method == 'GET':
        return jsonify({
            'show_tip_thanks': bool(getattr(g.current_user, 'show_tip_thanks', False))
        })
    data = request.get_json(silent=True) or {}
    if 'show_tip_thanks' in data:
        g.current_user.show_tip_thanks = bool(data.get('show_tip_thanks'))
        db.session.commit()
    return jsonify({'message': '设置已更新', 'show_tip_thanks': bool(getattr(g.current_user, 'show_tip_thanks', False))})


@app.route('/api/checkin/status', methods=['GET'])
@token_required
def get_checkin_status():
    return jsonify(_build_checkin_status(g.current_user))


@app.route('/api/checkin', methods=['POST'])
@token_required
def daily_checkin():
    user = g.current_user
    if getattr(user, 'is_admin', False):
        return jsonify({
            'message': '管理员免签到，等级为无限',
            'already_checked': True,
            'gained_exp': 0,
            'bonus_exp': 0,
            'status': _build_checkin_status(user)
        })
    today = _china_today()
    yesterday = today - timedelta(days=1)
    if getattr(user, 'last_checkin_date', None) == today:
        return jsonify({
            'message': '今天已经签到过了',
            'already_checked': True,
            'status': _build_checkin_status(user)
        })

    last_date = getattr(user, 'last_checkin_date', None)
    if last_date == yesterday:
        streak = int(getattr(user, 'checkin_streak', 0) or 0) + 1
    else:
        streak = 1
    base_exp = checkin_exp_by_streak(streak)
    bonus_exp = CHECKIN_STREAK_BONUS_EXP if (streak % CHECKIN_STREAK_BONUS_DAYS == 0) else 0
    gained_exp = base_exp + bonus_exp
    user.checkin_streak = streak
    user.last_checkin_date = today
    user.experience_points = int(getattr(user, 'experience_points', 0) or 0) + gained_exp
    db.session.add(CheckinLog(
        user_id=user.id,
        checkin_date=today,
        gained_exp=gained_exp,
        streak_after=streak
    ))
    try:
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        fresh_user = User.query.get(user.id)
        return jsonify({
            'message': '今天已经签到过了',
            'already_checked': True,
            'status': _build_checkin_status(fresh_user or user)
        })
    except Exception as e:
        db.session.rollback()
        print(f"[daily_checkin] failed: {e}")
        return jsonify({'error': '签到失败，请稍后重试'}), 500

    return jsonify({
        'message': f'签到成功，获得 +{gained_exp} 经验' + (f'（连续{streak}天额外 +{bonus_exp}）' if bonus_exp else ''),
        'already_checked': False,
        'base_exp': base_exp,
        'bonus_exp': bonus_exp,
        'gained_exp': gained_exp,
        'status': _build_checkin_status(user)
    })


@app.route('/api/achievements', methods=['GET'])
@token_required
def get_my_achievements():
    return jsonify(_build_achievements_for_user(g.current_user))


@app.route('/api/achievements/equip', methods=['POST'])
@token_required
def equip_achievement():
    user = g.current_user
    state = _build_achievements_for_user(user)
    if not state.get('can_equip'):
        return jsonify({'error': '等级达到 3 才可佩戴成就'}), 403
    data = request.get_json(silent=True) or {}
    key = (data.get('key') or '').strip()
    if not key:
        user.equipped_achievement_key = None
        db.session.commit()
        return jsonify({'message': '已取消佩戴', 'status': _build_achievements_for_user(user)})

    target = None
    for item in state.get('achievements', []):
        if item.get('key') == key:
            target = item
            break
    if not target:
        return jsonify({'error': '成就不存在'}), 404
    if not target.get('wearable'):
        return jsonify({'error': '该成就不可佩戴'}), 400
    if not target.get('unlocked'):
        min_level = int(target.get('min_level', 1) or 1)
        if min_level > 1:
            return jsonify({'error': f'等级达到 {min_level} 才可佩戴该成就'}), 403
        return jsonify({'error': '该成就尚未解锁，暂不可佩戴'}), 403

    user.equipped_achievement_key = key
    db.session.commit()
    return jsonify({'message': f'已佩戴「{target.get("title")}」', 'status': _build_achievements_for_user(user)})


@app.route('/api/group-links', methods=['GET'])
@token_required
def get_group_links():
    return jsonify(_build_group_links_for_user(g.current_user))


@app.route('/api/admin/group-links', methods=['GET'])
@token_required
@admin_required
def get_admin_group_links():
    return jsonify(_svc_get_group_link_urls(AppSetting, TELEGRAM_GROUP_SETTING_KEYS))


@app.route('/api/admin/group-links', methods=['PUT'])
@token_required
@admin_required
def set_admin_group_links():
    data = request.get_json(silent=True) or {}
    co_url = (data.get('co_create_url') or '').strip()
    core_url = (data.get('core_url') or '').strip()
    ok, err = _svc_validate_group_link_urls(co_url, core_url)
    if not ok:
        return jsonify({'error': err}), 400
    _set_setting_value(TELEGRAM_GROUP_SETTING_KEYS['co_create'], co_url)
    _set_setting_value(TELEGRAM_GROUP_SETTING_KEYS['core'], core_url)
    db.session.commit()
    _log_admin_action('group_links_update', 'setting', 'telegram_group_links')
    return jsonify({'message': '群链接已更新'})

@app.route('/api/user/password', methods=['PUT'])
@token_required
def change_password():
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': '缺少密码字段'}), 400
        
    if not g.current_user.check_password(old_password):
        return jsonify({'error': '原密码错误'}), 401
        
    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': '密码已更新'})

@app.route('/api/user/bind_wallet', methods=['POST'])
@token_required
def bind_wallet():
    # Only Web2 users (without address) can bind
    if g.current_user.address:
        return jsonify({'error': '当前账号已绑定钱包'}), 400
        
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')
    
    if not address or not signature or not message:
        return jsonify({'error': '缺少必要参数'}), 400
        
    try:
        address = Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
        return jsonify({'error': '钱包地址格式无效'}), 400

    # Check if address already used by other account
    existing_user = User.query.filter_by(address=address).first()
    if existing_user and existing_user.id != g.current_user.id:
        _log_flow_event('wallet_bind_failed', address=address, reason='already_bound')
        return jsonify({'error': '该钱包已绑定到其他账号'}), 400

    # 绑定签名必须带当前登录用户 nonce，且 5 分钟内有效，防重放
    if not g.current_user.nonce_created_at or datetime.utcnow() - g.current_user.nonce_created_at > timedelta(minutes=WALLET_NONCE_TTL_MINUTES):
        _log_flow_event('wallet_bind_failed', address=address, reason='nonce_expired')
        return jsonify({'error': '绑定挑战已过期，请重新获取'}), 401
    msg_stripped = (message or '').strip()
    expected_legacy = f"Bind wallet {address} to user {g.current_user.username}. Nonce: {g.current_user.nonce}"
    expected_new = f"Bind wallet {address} to account {g.current_user.id} on {request.host}: {g.current_user.nonce}"
    if msg_stripped not in (expected_legacy, expected_new):
        _log_flow_event('wallet_bind_failed', address=address, reason='message_mismatch')
        return jsonify({'error': '绑定签名消息格式不匹配'}), 400
        
    # Verify signature
    from eth_account.messages import encode_defunct
    from eth_account import Account
    
    try:
        msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(msg, signature=signature)
        
        if Web3.to_checksum_address(recovered_address) != address:
             _log_flow_event('wallet_bind_failed', address=address, reason='signature_mismatch')
             return jsonify({'error': '签名无效'}), 401
    except Exception as e:
        print(f"Verify Error: {e}")
        _log_flow_event('wallet_bind_failed', address=address, reason='signature_exception')
        return jsonify({'error': '签名校验失败'}), 400
        
    g.current_user.address = address
    g.current_user.refresh_nonce()
    db.session.commit()
    _log_flow_event('wallet_bind_success', address=address, target_user_id=g.current_user.id)
    
    return jsonify({'message': '钱包绑定成功', 'user': g.current_user.to_dict()})

@app.route('/api/user/bind_wallet/nonce', methods=['GET'])
@token_required
def get_bind_wallet_nonce():
    """为当前登录用户生成一次性绑定 nonce。"""
    g.current_user.refresh_nonce()
    db.session.commit()
    return jsonify({'nonce': g.current_user.nonce})

@app.route('/api/config/fees', methods=['GET'])
def get_fees():
    receive_address = app.config['BSC']['RECEIVE_ADDRESS']
    if not receive_address:
        return jsonify({'error': '平台收款地址未配置'}), 503
    fee_raw = get_post_fee_usdt_raw()
    decimals = app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_raw / (10 ** decimals), 4)
    return jsonify({
        'fee': str(fee_raw),
        'fee_currency': 'USDT',
        'fee_usdt': fee_usdt,
        'fee_cny': app.config['BSC']['POST_FEE_CNY'],
        'chain_id': app.config['BSC']['CHAIN_ID'],
        'receive_address': receive_address,
        'usdt_contract': app.config['BSC']['USDT_CONTRACT_ADDRESS'],
    })


@app.route('/api/config/public', methods=['GET'])
def get_public_config():
    """前端用：扫码登录等需 WalletConnect Project ID（从 https://cloud.walletconnect.com 申请）"""
    return jsonify({
        'walletconnect_project_id': os.environ.get('WALLETCONNECT_PROJECT_ID') or ''
    })


def _log_admin_action(action, target_type=None, target_id=None, details=None):
    try:
        if not getattr(g, 'current_user', None) or not getattr(g.current_user, 'is_admin', False):
            return
        row = AdminAuditLog(
            admin_id=g.current_user.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=(details or '')[:1000] if details else None
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


def _parse_iso_datetime(value):
    return _svc_parse_iso_datetime(value)


def _humanize_verify_error(message):
    return _svc_humanize_verify_error(message)


def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _china_today():
    return _svc_china_today()


def _build_checkin_status(user):
    return _svc_build_checkin_status(
        user,
        calc_level_info,
        checkin_exp_by_streak,
        CHECKIN_STREAK_BONUS_DAYS,
        CHECKIN_STREAK_BONUS_EXP,
        today=_china_today()
    )


def _build_post_precheck(user, data):
    return _svc_build_post_precheck(user, data)


def _normalize_tags(raw):
    return _svc_normalize_tags(raw)


def _is_post_permanent(post_obj):
    return _svc_is_post_permanent(post_obj)


def _extract_mention_tokens(text_value):
    return _svc_extract_mention_tokens(text_value)


def _resolve_mentioned_users(tokens, exclude_user_id=None):
    return _svc_resolve_mentioned_users(
        tokens,
        username_lookup=lambda token: User.query.filter(func.lower(User.username) == token.lower()).first(),
        nickname_lookup=lambda token: User.query.filter(func.lower(User.nickname) == token.lower()).first(),
        exclude_user_id=exclude_user_id
    )


@app.route('/api/posts/precheck', methods=['POST'])
@token_required
def precheck_post():
    data = request.get_json(silent=True) or {}
    return jsonify(_build_post_precheck(g.current_user, data))


@app.route('/api/onboarding/tasks', methods=['GET'])
@token_required
def onboarding_tasks():
    user = g.current_user
    posts_count = Post.query.filter_by(author_id=user.id).count()
    has_post = posts_count > 0
    has_wallet = bool(user.address)
    is_web2_bound = bool(user.username) and has_wallet
    has_checked_today = bool(getattr(user, 'last_checkin_date', None) == _china_today()) or bool(getattr(user, 'is_admin', False))
    tasks = [
        {'key': 'login', 'title': '完成登录', 'done': True},
        {'key': 'bind_wallet', 'title': '绑定钱包', 'done': has_wallet},
        {'key': 'daily_checkin', 'title': '完成今日签到', 'done': has_checked_today},
        {'key': 'publish_first', 'title': '发布第一篇帖子', 'done': has_post},
        {'key': 'verify_archive', 'title': '查看永存证据', 'done': has_post},
        {'key': 'web2_bind_wallet', 'title': 'Web2 账号绑定钱包', 'done': is_web2_bound},
    ]
    done_count = sum(1 for t in tasks if t['done'])
    return jsonify({'tasks': tasks, 'done_count': done_count, 'total': len(tasks)})


@app.route('/api/announcements/active', methods=['GET'])
def get_active_announcement():
    now = datetime.utcnow()
    ann = Announcement.query.filter(
        Announcement.entry_type == 'announcement',
        Announcement.is_active == True,
        ((Announcement.starts_at == None) | (Announcement.starts_at <= now)),
        ((Announcement.expires_at == None) | (Announcement.expires_at > now))
    ).order_by(Announcement.created_at.desc()).first()
    return jsonify({'announcement': ann.to_dict() if ann else None})


@app.route('/api/announcements', methods=['GET'])
def list_public_announcements():
    now = datetime.utcnow()
    entry_type = (request.args.get('type') or '').strip().lower()
    active_only = request.args.get('is_active')
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    query = Announcement.query
    if entry_type in ('announcement', 'activity'):
        query = query.filter(Announcement.entry_type == entry_type)
    if active_only in ('1', 'true', 'yes'):
        query = query.filter(
            Announcement.is_active == True,
            ((Announcement.starts_at == None) | (Announcement.starts_at <= now)),
            ((Announcement.expires_at == None) | (Announcement.expires_at > now))
        )
    query = query.order_by(Announcement.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'announcements': [a.to_dict() for a in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

# --- Posts ---

@app.route('/api/search', methods=['GET'])
def search_posts():
    q = request.args.get('q', '').strip()
    if len(q) > 200:
        return jsonify({'error': '搜索关键词过长', 'posts': []}), 400
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    from_date_raw = (request.args.get('from_date') or '').strip()
    to_date_raw = (request.args.get('to_date') or '').strip()
    permanent_only = (request.args.get('permanent_only') or request.args.get('on_chain') or '').strip().lower() in ('1', 'true', 'yes')
    tags = _normalize_tags(request.args.get('tags') or '')
    if not q and not from_date_raw and not to_date_raw and not permanent_only and not tags:
        return jsonify({'posts': [], 'total': 0, 'pages': 0, 'current_page': page})

    query = Post.query.filter_by(is_hidden=False)
    if q:
        escaped_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.filter(
            (Post.title.ilike(f'%{escaped_q}%', escape='\\')) |
            (Post.content.ilike(f'%{escaped_q}%', escape='\\'))
        )

    if from_date_raw:
        dt = _parse_iso_datetime(from_date_raw) or _parse_iso_datetime(f"{from_date_raw}T00:00:00")
        if dt:
            query = query.filter(Post.created_at >= dt)
    if to_date_raw:
        dt = _parse_iso_datetime(to_date_raw) or _parse_iso_datetime(f"{to_date_raw}T23:59:59")
        if dt:
            query = query.filter(Post.created_at <= dt)
    if permanent_only:
        query = query.filter(or_(Post.tx_hash != None, Post.ipfs_cid != None, Post.is_on_chain == True, Post.post_type == 1))
    if tags:
        tag_filters = []
        for tag in tags:
            escaped = tag.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            # tags 存为 JSON 字符串时，优先按引号包裹词项匹配，避免宽泛子串误命中。
            tag_filters.append(Post.tags.ilike(f'%"{escaped}"%', escape='\\'))
        if tag_filters:
            query = query.filter(or_(*tag_filters))

    query = query.order_by(
        Post.is_special_announcement.desc(),
        Post.is_pinned.desc(),
        Post.pinned_at.desc(),
        Post.created_at.desc()
    )
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    posts = pagination.items
    return jsonify({
        'posts': [p.to_dict() for p in posts],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/posts/check_tx', methods=['GET'])
def check_tx_status():
    tx_hash = request.args.get('tx_hash')
    if not tx_hash:
        return jsonify({'error': '缺少交易哈希'}), 400
        
    # Check if it exists in Post (Published successfully)
    post = Post.query.filter_by(tx_hash=tx_hash).first()
    if post:
        return jsonify({
            'status': 'success',
            'stage': 'published',
            'message': '帖子已成功发布',
            'post_id': post.id,
            'post_title': post.title
        })

    pending_row = PendingPublication.query.filter_by(tx_hash=tx_hash).first()
    if pending_row:
        if pending_row.status == 'awaiting_retry':
            return jsonify({
                'status': 'pending',
                'stage': 'awaiting_retry',
                'message': pending_row.last_error or '支付已确认，但永存写入失败，可直接继续发布重试',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': TX_CONFIRMATIONS_NEEDED,
                'pending_publication': pending_row.to_dict(),
            })
        if pending_row.status == 'storage_ready':
            return jsonify({
                'status': 'pending',
                'stage': 'storage_ready',
                'message': '永存档案已写入，正在创建帖子记录',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': TX_CONFIRMATIONS_NEEDED,
                'pending_publication': pending_row.to_dict(),
            })
        if pending_row.status in ('payment_verified', 'initiated'):
            return jsonify({
                'status': 'pending',
                'stage': pending_row.status,
                'message': '支付已记录，正在继续处理发布',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': TX_CONFIRMATIONS_NEEDED,
                'pending_publication': pending_row.to_dict(),
            })

    inspect = _svc_inspect_transaction_status(tx_hash, tx_confirmations=TX_CONFIRMATIONS_NEEDED)
    if inspect.get('stage') == 'confirmed':
        return jsonify({
            'status': 'pending',
            'stage': 'confirmed_processing',
            'message': '链上支付已确认，正在写入永存档案并创建帖子',
            'confirmations': inspect.get('confirmations', 0),
            'confirmations_needed': inspect.get('confirmations_needed', TX_CONFIRMATIONS_NEEDED),
        })
    if inspect.get('ok'):
        return jsonify({
            'status': 'pending',
            'stage': inspect.get('stage') or 'pending',
            'message': inspect.get('message') or '处理中',
            'confirmations': inspect.get('confirmations', 0),
            'confirmations_needed': inspect.get('confirmations_needed', TX_CONFIRMATIONS_NEEDED),
        })
    return jsonify({
        'status': 'error',
        'stage': inspect.get('stage') or 'error',
        'message': inspect.get('message') or '交易状态异常',
        'confirmations': inspect.get('confirmations', 0),
        'confirmations_needed': inspect.get('confirmations_needed', TX_CONFIRMATIONS_NEEDED),
    })


@app.route('/api/posts/pending/latest', methods=['GET'])
@token_required
def get_latest_pending_post():
    row = _svc_get_latest_pending_publication(PendingPublication, g.current_user.id)
    if not row:
        return jsonify({'pending': None})
    return jsonify({'pending': row.to_dict()})


@app.route('/api/posts/pending/clear', methods=['POST'])
@token_required
def clear_pending_post():
    data = request.get_json(silent=True) or {}
    tx_hash = (data.get('tx_hash') or '').strip()
    row = None
    if tx_hash:
        row = PendingPublication.query.filter_by(tx_hash=tx_hash, user_id=g.current_user.id).first()
    else:
        row = _svc_get_latest_pending_publication(PendingPublication, g.current_user.id)
    if row:
        db.session.delete(row)
        db.session.commit()
        _log_flow_event('pending_publication_cleared', tx_hash=row.tx_hash, user_id=g.current_user.id)
    return jsonify({'message': '待恢复记录已清除'})


def _resume_pending_publication_row(row, actor_user=None):
    if not row:
        return False, '未找到待恢复记录', None, None
    owner = db.session.get(User, row.user_id)
    if not owner:
        return False, '该待恢复记录对应的用户不存在', None, row
    existing_post = Post.query.filter_by(tx_hash=row.tx_hash).first()
    if existing_post:
        _svc_clear_pending_publication(PendingPublication, db.session, tx_hash=row.tx_hash)
        db.session.commit()
        return True, '帖子已存在，已同步清理待恢复记录', existing_post, None

    inspect = _svc_inspect_transaction_status(row.tx_hash, tx_confirmations=TX_CONFIRMATIONS_NEEDED)
    row.confirmations = int(inspect.get('confirmations', 0) or 0)
    if not inspect.get('ok') and inspect.get('stage') != 'confirmed':
        row.status = 'awaiting_retry'
        row.last_error = inspect.get('message') or '交易状态异常'
        db.session.commit()
        return False, row.last_error, None, row
    if inspect.get('stage') not in ('confirmed',) and inspect.get('stage') not in ('awaiting_confirmation', 'broadcasted'):
        row.status = 'awaiting_retry'
        row.last_error = inspect.get('message') or '交易状态异常'
        db.session.commit()
        return False, row.last_error, None, row
    if inspect.get('stage') in ('awaiting_confirmation', 'broadcasted'):
        row.status = 'payment_verified'
        row.last_error = inspect.get('message') or '链上确认中'
        db.session.commit()
        return False, row.last_error, None, row

    try:
        normalized_tags = []
        try:
            normalized_tags = json.loads(row.tags) if row.tags else []
        except Exception:
            normalized_tags = []
        if not isinstance(normalized_tags, list):
            normalized_tags = []

        clean_title = bleach.clean(row.title or '', strip=True)
        clean_content = _bleach_clean_post_content(row.content or '')
        if not clean_title or not clean_content.strip():
            row.status = 'awaiting_retry'
            row.last_error = '待恢复记录缺少完整标题或正文'
            db.session.commit()
            return False, row.last_error, None, row

        target_series = db.session.get(Series, row.series_id) if row.series_id else None
        if target_series and not _series_can_edit(target_series, owner):
            target_series = None

        if not row.ipfs_cid:
            payload = {
                'title': clean_title,
                'content': clean_content,
                'tags': normalized_tags,
                'author': owner.address,
                'timestamp': datetime.utcnow().isoformat(),
                'tx_hash': row.tx_hash,
                'region': row.region or '其他',
                'platform': 'GuiHua Web3 (Arweave)'
            }
            storage_id, storage_type, last_error = upload_to_arweave_with_retry(payload, retries=3)
            if not storage_id:
                row.status = 'awaiting_retry'
                row.last_error = '支付已确认，但永存档案写入失败。可直接继续发布重试，无需再次支付。'
                db.session.commit()
                return False, row.last_error, None, row
            row.ipfs_cid = storage_id
            row.status = 'storage_ready'
            row.last_error = None
            db.session.flush()

        post = Post(
            title=clean_title,
            content=clean_content,
            cover_image=None,
            images='[]',
            tags=json.dumps(normalized_tags, ensure_ascii=False),
            author_id=owner.id,
            tx_hash=row.tx_hash,
            ipfs_cid=row.ipfs_cid,
            is_paid=True,
            is_on_chain=True,
            region=row.region or '其他',
            is_special_announcement=bool(row.is_special_announcement) if owner.is_admin else False,
            post_type=1
        )
        db.session.add(post)
        db.session.flush()

        if target_series:
            max_order = db.session.query(func.max(SeriesPost.order_index)).filter(SeriesPost.series_id == target_series.id).scalar() or 0
            db.session.add(SeriesPost(series_id=target_series.id, post_id=post.id, order_index=int(max_order) + 1))

        if not UsedTransaction.query.filter_by(tx_hash=row.tx_hash).first():
            db.session.add(UsedTransaction(tx_hash=row.tx_hash, user_id=owner.id))

        mention_source = re.sub(r'<[^>]+>', ' ', clean_content or '')
        mention_tokens = _extract_mention_tokens(mention_source)
        mention_users = _resolve_mentioned_users(mention_tokens, exclude_user_id=owner.id)
        for u in mention_users:
            db.session.add(Notification(
                user_id=u.id,
                sender_id=owner.id,
                post_id=post.id,
                comment_id=None,
                type='mention',
                content='在帖子中提到了你',
                link=f"/?post={post.id}"
            ))

        db.session.delete(row)
        db.session.commit()
        _log_flow_event(
            'pending_publication_recovered',
            tx_hash=post.tx_hash,
            post_id=post.id,
            operator_user_id=getattr(actor_user, 'id', None),
            target_user_id=owner.id,
        )
        return True, '待恢复发布已补偿完成', post, None
    except Exception as e:
        db.session.rollback()
        row = PendingPublication.query.filter_by(tx_hash=row.tx_hash).first()
        if row:
            row.status = 'awaiting_retry'
            row.last_error = '支付已确认，但发布流程未完成。可直接继续发布重试。'
            db.session.commit()
        _log_flow_event('pending_publication_recovery_failed', tx_hash=getattr(row, 'tx_hash', None), reason=str(e)[:180])
        return False, '待恢复发布补偿失败，请稍后重试', None, row


@app.route('/api/posts/pending/retry', methods=['POST'])
@token_required
def retry_pending_post():
    data = request.get_json(silent=True) or {}
    tx_hash = (data.get('tx_hash') or '').strip()
    if not tx_hash:
        return jsonify({'error': '缺少交易哈希'}), 400
    row = PendingPublication.query.filter_by(tx_hash=tx_hash, user_id=g.current_user.id).first()
    if not row:
        payload = {
            'title': data.get('title') or '',
            'content': data.get('content') or '',
            'tags': _normalize_tags(data.get('tags') or data.get('tag_names')),
            'region': data.get('region') or '其他',
            'series_id': data.get('series_id'),
            'is_special_announcement': bool(data.get('is_special_announcement')) if g.current_user.is_admin else False,
        }
        row = _svc_upsert_pending_publication(
            PendingPublication, db.session, g.current_user.id, tx_hash,
            payload=payload, status='initiated'
        )
        db.session.commit()
    ok, message, post, pending_row = _resume_pending_publication_row(row, actor_user=g.current_user)
    if ok:
        return jsonify({'message': message, 'post': post.to_dict(g.current_user.id)}), 200
    if pending_row:
        return jsonify({'error': message, 'pending': pending_row.to_dict()}), 503
    return jsonify({'error': message}), 400


@app.route('/api/admin/pending-publications', methods=['GET'])
@token_required
@admin_required
def list_pending_publications():
    status = (request.args.get('status') or '').strip().lower()
    q = (request.args.get('q') or '').strip()
    limit = max(1, min(int(request.args.get('limit', 200) or 200), 300))
    query = PendingPublication.query
    if status:
        query = query.filter(PendingPublication.status == status)
    if q:
        escaped = q.replace('%', '').replace('_', '')
        query = query.filter(or_(
            PendingPublication.tx_hash.ilike(f'%{escaped}%'),
            PendingPublication.title.ilike(f'%{escaped}%'),
            PendingPublication.last_error.ilike(f'%{escaped}%')
        ))
    rows = query.order_by(PendingPublication.updated_at.desc(), PendingPublication.id.desc()).limit(limit).all()
    items = []
    for row in rows:
        existing_post_id = Post.query.filter_by(tx_hash=row.tx_hash).with_entities(Post.id).scalar()
        items.append({
            **row.to_dict(),
            'nickname': row.user.nickname if row.user else None,
            'username': row.user.username if row.user else None,
            'profile_url': f"/profile?user={row.user.username}" if row.user and row.user.username else None,
            'post_url': f"/post/{existing_post_id}" if existing_post_id else None,
        })
    return jsonify({'items': items})


@app.route('/api/admin/pending-publications/<int:pending_id>/retry', methods=['POST'])
@token_required
@admin_required
def retry_pending_publication_admin(pending_id):
    row = PendingPublication.query.get_or_404(pending_id)
    ok, message, post, pending_row = _resume_pending_publication_row(row, actor_user=g.current_user)
    if ok:
        return jsonify({'message': message, 'post': post.to_dict(g.current_user.id)}), 200
    if pending_row:
        return jsonify({'error': message, 'pending': pending_row.to_dict()}), 503
    return jsonify({'error': message}), 400


@app.route('/api/admin/pending-publications/<int:pending_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_pending_publication_admin(pending_id):
    row = PendingPublication.query.get_or_404(pending_id)
    tx_hash = row.tx_hash
    db.session.delete(row)
    db.session.commit()
    _log_flow_event('pending_publication_admin_deleted', pending_id=pending_id, tx_hash=tx_hash, admin_id=g.current_user.id)
    return jsonify({'message': '待恢复记录已删除'})


@app.route('/api/admin/pending-publications/retry-batch', methods=['POST'])
@token_required
@admin_required
def retry_pending_publication_batch_admin():
    result = _svc_run_compensation_batch(
        app,
        PendingPublication,
        _resume_pending_publication_row,
        app.logger,
        limit=10,
        min_age_seconds=0,
    )
    _log_flow_event('pending_publication_batch_retry', admin_id=g.current_user.id, **result)
    return jsonify({
        'message': '已执行一轮待发布补偿任务',
        'result': result
    })


@app.route('/api/admin/ops/summary', methods=['GET'])
@token_required
@admin_required
def admin_ops_summary():
    summary = _svc_build_ops_summary(FlowEvent, PendingPublication, AdminAuditLog)
    summary['worker'] = {
        'enabled': _svc_should_start_compensation_worker() and _svc_compensation_interval_seconds() > 0,
        'interval_seconds': _svc_compensation_interval_seconds(),
    }
    return jsonify(summary)


@app.route('/api/admin/flow-events', methods=['GET'])
@token_required
@admin_required
def admin_flow_events():
    severity = (request.args.get('severity') or '').strip().lower()
    event_keyword = (request.args.get('event') or '').strip()
    limit = max(1, min(int(request.args.get('limit', 100) or 100), 300))
    query = FlowEvent.query
    if severity in ('info', 'warn', 'error'):
        query = query.filter(FlowEvent.severity == severity)
    if event_keyword:
        query = query.filter(FlowEvent.event.ilike(f'%{event_keyword.replace("%", "").replace("_", "")}%'))
    rows = query.order_by(FlowEvent.created_at.desc(), FlowEvent.id.desc()).limit(limit).all()
    return jsonify({'items': [row.to_dict() for row in rows]})

@app.route('/api/admin/stats', methods=['GET'])
@token_required
def admin_stats():
    if not g.current_user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403
        
    # Stats
    total_users = User.query.count()
    web3_users = User.query.filter(User.address != None).count()
    web2_users = total_users - web3_users
    
    total_posts = Post.query.count()
    web3_posts = Post.query.filter(Post.post_type == 1).count() # Or filter by tx_hash
    web2_posts = total_posts - web3_posts
    
    fee_usdt_raw = get_post_fee_usdt_raw()
    decimals = app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_usdt_raw / (10 ** decimals), 4)
    total_revenue_raw = web3_posts * fee_usdt_raw
    total_revenue_usdt = total_revenue_raw / (10 ** decimals)
    
    return jsonify({
        'users': {
            'total': total_users,
            'web3': web3_users,
            'web2': web2_users,
            'retention_rate': 'N/A'
        },
        'posts': {
            'total': total_posts,
            'web3': web3_posts,
            'web2': web2_posts
        },
        'revenue': {
            'total_usdt': round(total_revenue_usdt, 2),
            'fee_per_post_usdt': fee_usdt
        }
    })

@app.route('/api/users/<username>', methods=['GET'])
def get_user_profile(username):
    token = (username or '').strip()
    if not token:
        return jsonify({'error': '用户不存在'}), 404

    user = None
    if token.isdigit():
        try:
            user = User.query.get(int(token))
        except Exception:
            user = None
    if not user:
        user = User.query.filter(func.lower(User.username) == token.lower()).first()
    if not user and token.startswith('0x'):
        user = User.query.filter(func.lower(User.address) == token.lower()).first()
    if not user:
        user = User.query.filter(func.lower(User.nickname) == token.lower()).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
        
    payload = _get_optional_jwt_payload()
    current_user_id = payload.get('user_id') if payload else None

    posts = Post.query.filter_by(author_id=user.id, is_hidden=False).order_by(Post.created_at.desc()).all()
    post_ids = [p.id for p in posts]
    user_likes = set()
    user_bookmarks = set()
    like_counts = {}
    comment_counts = {}
    if post_ids:
        if current_user_id:
            user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
            user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
        like_rows = db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id).all()
        like_counts = {r[0]: r[1] for r in like_rows}
        comment_rows = db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all()
        comment_counts = {r[0]: r[1] for r in comment_rows}

    user_data = user.to_dict()
    user_data['posts_count'] = len(posts)
    try:
        tips_count = Tip.query.filter_by(to_user_id=user.id).count()
    except Exception:
        tips_count = 0
    user_data['tips_received_count'] = tips_count
    posts_data = []
    for p in posts:
        p_dict = p.to_dict(
            current_user_id,
            likes_count=like_counts.get(p.id, 0),
            comments_count=comment_counts.get(p.id, 0)
        )
        p_dict['is_liked'] = p.id in user_likes
        p_dict['is_bookmarked'] = p.id in user_bookmarks
        posts_data.append(p_dict)

    series_rows = Series.query.filter_by(author_id=user.id).order_by(Series.updated_at.desc()).limit(50).all()
    return jsonify({
        'user': user_data,
        'posts': posts_data,
        'series': [s.to_dict() for s in series_rows]
    })


def _series_can_view(series_obj, viewer=None):
    return _svc_series_can_view(series_obj, viewer)


def _series_can_edit(series_obj, viewer):
    return _svc_series_can_edit(series_obj, viewer)


def _reindex_series_posts(series_id):
    rows = SeriesPost.query.filter_by(series_id=series_id).order_by(SeriesPost.order_index.asc(), SeriesPost.id.asc()).all()
    changed = False
    for idx, row in enumerate(rows, start=1):
        if row.order_index != idx:
            row.order_index = idx
            changed = True
    if changed:
        db.session.flush()


@app.route('/api/series', methods=['GET'])
def list_series():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    creator_id = request.args.get('creator_id', type=int)
    payload = _get_optional_jwt_payload()
    viewer = User.query.get(payload.get('user_id')) if payload and payload.get('user_id') else None
    mine = (request.args.get('mine') or '').strip().lower() in ('1', 'true', 'yes')
    query = Series.query
    if creator_id:
        query = query.filter(Series.author_id == creator_id)
    if mine and viewer:
        query = query.filter(Series.author_id == viewer.id)
    if not (viewer and getattr(viewer, 'is_admin', False)):
        if mine and viewer:
            pass
        else:
            query = query.filter(Series.is_public == True)
    query = query.order_by(Series.updated_at.desc(), Series.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = []
    for s in pagination.items:
        d = s.to_dict()
        d['posts_count'] = SeriesPost.query.filter_by(series_id=s.id).count()
        items.append(d)
    return jsonify({'items': items, 'total': pagination.total, 'pages': pagination.pages, 'current_page': page})


@app.route('/api/series', methods=['POST'])
@token_required
def create_series():
    data = request.get_json(silent=True) or {}
    title = bleach.clean((data.get('title') or '').strip(), tags=[], strip=True)
    if not title:
        return jsonify({'error': '系列标题不能为空'}), 400
    if len(title) > 120:
        return jsonify({'error': '系列标题不能超过120字'}), 400
    desc = bleach.clean((data.get('description') or '').strip(), tags=[], strip=True)
    cover_image = (data.get('cover_image') or '').strip() or None
    row = Series(
        title=title,
        description=desc[:1000] if desc else None,
        cover_image=cover_image,
        author_id=g.current_user.id,
        is_public=bool(data.get('is_public', True))
    )
    db.session.add(row)
    db.session.commit()
    _log_flow_event('series_created', series_id=row.id, title=row.title, is_public=bool(row.is_public))
    return jsonify({'message': '系列已创建', 'series': row.to_dict()}), 201


@app.route('/api/series/<int:series_id>', methods=['GET'])
def get_series_detail(series_id):
    row = Series.query.get_or_404(series_id)
    payload = _get_optional_jwt_payload()
    viewer = User.query.get(payload.get('user_id')) if payload and payload.get('user_id') else None
    if not _series_can_view(row, viewer):
        return jsonify({'error': '该系列不可见'}), 403
    links = SeriesPost.query.filter_by(series_id=series_id).order_by(SeriesPost.order_index.asc(), SeriesPost.id.asc()).all()
    posts = []
    for link in links:
        p = link.post
        if not p:
            continue
        if p.is_hidden and not (viewer and (viewer.is_admin or viewer.id == p.author_id)):
            continue
        posts.append({
            'order_index': link.order_index,
            'post': p.to_dict(payload.get('user_id') if payload else None)
        })
    return jsonify({'series': row.to_dict(), 'items': posts})


@app.route('/api/series/<int:series_id>', methods=['PATCH'])
@token_required
def update_series(series_id):
    row = Series.query.get_or_404(series_id)
    if not _series_can_edit(row, g.current_user):
        return jsonify({'error': '无权限编辑该系列'}), 403
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        title = bleach.clean((data.get('title') or '').strip(), tags=[], strip=True)
        if not title:
            return jsonify({'error': '系列标题不能为空'}), 400
        row.title = title[:120]
    if 'description' in data:
        row.description = bleach.clean((data.get('description') or '').strip(), tags=[], strip=True)[:1000]
    if 'cover_image' in data:
        row.cover_image = (data.get('cover_image') or '').strip() or None
    if 'is_public' in data:
        row.is_public = bool(data.get('is_public'))
    db.session.commit()
    _log_flow_event('series_updated', series_id=row.id, title=row.title, is_public=bool(row.is_public))
    return jsonify({'message': '系列已更新', 'series': row.to_dict()})


@app.route('/api/series/<int:series_id>', methods=['DELETE'])
@token_required
def delete_series(series_id):
    row = Series.query.get_or_404(series_id)
    if not _series_can_edit(row, g.current_user):
        return jsonify({'error': '无权限删除该系列'}), 403
    SeriesPost.query.filter_by(series_id=series_id).delete(synchronize_session=False)
    db.session.delete(row)
    db.session.commit()
    _log_flow_event('series_deleted', series_id=series_id, title=row.title)
    return jsonify({'message': '系列已删除'})


@app.route('/api/series/<int:series_id>/posts', methods=['POST'])
@token_required
def add_post_to_series(series_id):
    series = Series.query.get_or_404(series_id)
    if not _series_can_edit(series, g.current_user):
        return jsonify({'error': '无权限操作该系列'}), 403
    data = request.get_json(silent=True) or {}
    post_id = data.get('post_id')
    if not post_id:
        return jsonify({'error': '缺少 post_id'}), 400
    post = Post.query.get_or_404(int(post_id))
    if not g.current_user.is_admin and post.author_id != g.current_user.id:
        return jsonify({'error': '仅可加入自己的帖子'}), 403
    existed = SeriesPost.query.filter_by(series_id=series_id, post_id=post.id).first()
    if existed:
        return jsonify({'error': '该帖子已在系列中'}), 400
    order_index = data.get('order_index')
    if order_index is None:
        max_order = db.session.query(func.max(SeriesPost.order_index)).filter(SeriesPost.series_id == series_id).scalar() or 0
        order_index = int(max_order) + 1
    else:
        try:
            order_index = max(1, int(order_index))
        except Exception:
            return jsonify({'error': 'order_index 非法'}), 400
        SeriesPost.query.filter(
            SeriesPost.series_id == series_id,
            SeriesPost.order_index >= order_index
        ).update({'order_index': SeriesPost.order_index + 1}, synchronize_session=False)
    row = SeriesPost(series_id=series_id, post_id=post.id, order_index=order_index)
    db.session.add(row)
    db.session.commit()
    _log_flow_event('series_post_added', series_id=series_id, post_id=post.id, order_index=order_index)
    return jsonify({'message': '已加入系列', 'item': row.to_dict()})


@app.route('/api/series/<int:series_id>/posts/<int:post_id>', methods=['DELETE'])
@token_required
def remove_post_from_series(series_id, post_id):
    series = Series.query.get_or_404(series_id)
    if not _series_can_edit(series, g.current_user):
        return jsonify({'error': '无权限操作该系列'}), 403
    row = SeriesPost.query.filter_by(series_id=series_id, post_id=post_id).first()
    if not row:
        return jsonify({'error': '该帖子不在系列中'}), 404
    db.session.delete(row)
    db.session.flush()
    _reindex_series_posts(series_id)
    db.session.commit()
    _log_flow_event('series_post_removed', series_id=series_id, post_id=post_id)
    return jsonify({'message': '已移出系列'})


@app.route('/api/series/<int:series_id>/order', methods=['PATCH'])
@token_required
def reorder_series_posts(series_id):
    series = Series.query.get_or_404(series_id)
    if not _series_can_edit(series, g.current_user):
        return jsonify({'error': '无权限操作该系列'}), 403
    data = request.get_json(silent=True) or {}
    items = data.get('items') or data.get('post_ids') or []
    if not isinstance(items, list) or not items:
        return jsonify({'error': 'items 不能为空'}), 400
    if items and isinstance(items[0], dict):
        mapping = []
        for it in items:
            pid = int(it.get('post_id', 0) or 0)
            order = int(it.get('order_index', 0) or 0)
            if pid > 0 and order > 0:
                mapping.append((pid, order))
        for pid, order in mapping:
            row = SeriesPost.query.filter_by(series_id=series_id, post_id=pid).first()
            if row:
                row.order_index = order
    else:
        for idx, pid in enumerate(items, start=1):
            row = SeriesPost.query.filter_by(series_id=series_id, post_id=int(pid)).first()
            if row:
                row.order_index = idx
    db.session.flush()
    _reindex_series_posts(series_id)
    db.session.commit()
    _log_flow_event('series_reordered', series_id=series_id, total_items=len(items))
    rows = SeriesPost.query.filter_by(series_id=series_id).order_by(SeriesPost.order_index.asc()).all()
    return jsonify({'message': '排序已更新', 'items': [r.to_dict() for r in rows]})

@app.route('/api/notifications', methods=['GET'])
@token_required
def get_notifications():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    pagination = Notification.query.filter_by(user_id=g.current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
        
    notifs = pagination.items
    
    return jsonify({
        'notifications': [n.to_dict() for n in notifs],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/notifications/<int:id>/read', methods=['PUT'])
@token_required
def read_notification(id):
    notif = Notification.query.get_or_404(id)
    if notif.user_id != g.current_user.id:
        return jsonify({'error': '这不是你的通知'}), 403
        
    notif.is_read = True
    db.session.commit()
    return jsonify({'message': '已标记为已读'})

@app.route('/api/notifications/read_all', methods=['PUT'])
@token_required
def read_all_notifications():
    Notification.query.filter_by(user_id=g.current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': '已全部标记为已读'})

def _get_posts_fallback(page, per_page, current_user_id):
    return _posts_get_posts_fallback(page, per_page, current_user_id)


def _apply_default_post_order(query):
    return _posts_apply_default_post_order(query)


@app.route('/api/posts/pinned', methods=['GET'])
def get_pinned_post():
    """返回当前全站置顶帖（若无则返回 null）。"""
    post = Post.query.filter_by(is_hidden=False, is_pinned=True).order_by(
        Post.pinned_at.desc(), Post.created_at.desc()
    ).first()
    return jsonify({'post': post.to_dict() if post else None})

@app.route('/api/posts', methods=['GET'])
def get_posts():
    """帖子列表：委托 services.posts_query 处理排序、聚合与 fallback。"""
    payload = _get_optional_jwt_payload()
    current_user_id = payload.get('user_id') if payload else None

    sort_by = request.args.get('sort', 'new')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)
    region = request.args.get('region')
    payload_data, status_code = _build_posts_payload(
        sort_by=sort_by,
        page=page,
        per_page=per_page,
        region=region,
        current_user_id=current_user_id
    )
    return jsonify(payload_data), status_code

@app.route('/api/posts', methods=['POST'])
@token_required
def create_post():
    if _rate_limit('create_post', 20):
        return jsonify({'error': '请求过于频繁'}), 429
    # 1. Permission Check
    if not g.current_user.is_admin and not g.current_user.address:
        _log_flow_event('post_publish_blocked', reason='wallet_required')
        return jsonify({'error': '请先绑定钱包'}), 400
    
    # Check if multipart/form-data (for image upload)
    if 'image' in request.files:
        title = request.form.get('title')
        content = request.form.get('content')
        image_file = request.files.get('image')
        tx_hash = request.form.get('tx_hash')
        region = request.form.get('region', '其他')
        vote_options_str = request.form.get('vote_options')
        if vote_options_str:
            try:
                vote_options = json.loads(vote_options_str)
            except (TypeError, ValueError):
                return jsonify({'error': 'vote_options 必须是 JSON 数组'}), 400
            if not isinstance(vote_options, list):
                return jsonify({'error': 'vote_options 必须是数组'}), 400
        else:
            vote_options = []
        data = {
            'title': title,
            'content': content,
            'tx_hash': tx_hash,
            'ipfs_cid': request.form.get('ipfs_cid'),
            'images': [],
            'region': region,
            'vote_options': vote_options,
            'tags': request.form.get('tags')
        }
    else:
        # JSON fallback（避免 get_json() 为 None 时 .get 报错）
        data = request.get_json(silent=True) or {}
    
    tx_hash = data.get('tx_hash')
    ipfs_cid = data.get('ipfs_cid')
    region = data.get('region', '其他')
    vote_options = data.get('vote_options', [])
    normalized_tags = _normalize_tags(data.get('tags') or data.get('tag_names'))
    series_id_raw = data.get('series_id')
    target_series = None
    if series_id_raw not in (None, '', 0, '0'):
        try:
            series_id_int = int(series_id_raw)
        except (TypeError, ValueError):
            _log_flow_event('post_series_invalid', series_id=series_id_raw)
            return jsonify({'error': 'series_id 非法'}), 400
        target_series = Series.query.get(series_id_int)
        if not target_series:
            _log_flow_event('post_series_missing', series_id=series_id_int)
            return jsonify({'error': '系列不存在'}), 404
        if not _series_can_edit(target_series, g.current_user):
            _log_flow_event('post_series_forbidden', series_id=series_id_int)
            return jsonify({'error': '无权限将帖子加入该系列'}), 403
    if vote_options is None:
        vote_options = []
    if not isinstance(vote_options, list):
        return jsonify({'error': 'vote_options 必须是数组'}), 400

    precheck = _build_post_precheck(g.current_user, data)
    if not precheck['ok']:
        _log_flow_event('post_precheck_failed', issues=precheck.get('issues'))
        return jsonify({'error': '发布前检查未通过', 'issues': precheck['issues']}), 400
    
    # 2. Region Validation
    valid_regions = ['中国', '台湾', '香港', '澳门', '新加坡', '马来西亚', '日本', '韩国', '其他']
    if region not in valid_regions:
        _log_flow_event('post_region_invalid', region=region)
        return jsonify({'error': f'地区不合法，可选范围：{", ".join(valid_regions)}'}), 400
    _log_flow_event('post_publish_started', tx_hash=tx_hash, region=region, is_admin=bool(g.current_user.is_admin), series_id=getattr(target_series, 'id', None))

    pending_payload = {
        'title': data.get('title'),
        'content': data.get('content'),
        'tags': normalized_tags,
        'region': region,
        'series_id': getattr(target_series, 'id', None),
        'is_special_announcement': bool(data.get('is_special_announcement')) if g.current_user.is_admin else False,
    }

    # 3. Logic Branching（is_paid 仅由后端校验结果决定，绝不信任客户端传入）
    is_paid = False
    is_on_chain = False
    
    if g.current_user.is_admin:
        # 管理员直接发帖：不上链、不支付，仅普通论坛帖；确保 tx_hash/ipfs_cid 为 None 避免 DB NOT NULL 报错
        tx_hash = None
        ipfs_cid = None
    else:
        # Regular User: 必须带 tx_hash，且经 verify_transaction 校验 to/from/value 与唯一性（min_amount = 1 USD 等值 BNB）
        if not tx_hash:
            _log_flow_event('post_payment_missing', reason='tx_hash_required')
            return jsonify({'error': '缺少交易哈希'}), 400
        _svc_upsert_pending_publication(
            PendingPublication, db.session, g.current_user.id, tx_hash,
            payload=pending_payload, status='initiated'
        )
        db.session.commit()
        is_valid, error_msg = verify_transaction(tx_hash, g.current_user.address, min_amount=get_post_fee_usdt_raw(), payment_type='usdt')
        if not is_valid:
            _log_flow_event('post_payment_verify_failed', tx_hash=tx_hash, reason=error_msg)
            _svc_upsert_pending_publication(
                PendingPublication, db.session, g.current_user.id, tx_hash,
                payload=pending_payload, status='awaiting_retry', last_error=_humanize_verify_error(error_msg)
            )
            db.session.commit()
            return jsonify({'error': _humanize_verify_error(error_msg)}), 400
            
        is_paid = True
        is_on_chain = True
        _log_flow_event('post_payment_verified', tx_hash=tx_hash, user_address=g.current_user.address)
        _svc_upsert_pending_publication(
            PendingPublication, db.session, g.current_user.id, tx_hash,
            payload=pending_payload, status='payment_verified'
        )
        db.session.commit()
        
        # 永存档案：支付后必须立即写入 Arweave，否则不发帖；放行 img 的 src/alt/style/class 以保留正文内图片
        clean_content = _bleach_clean_post_content(data.get('content', ''))
        payload = {
            'title': data.get('title'),
            'content': clean_content,
            'tags': normalized_tags,
            'author': g.current_user.address,
            'timestamp': datetime.utcnow().isoformat(),
            'tx_hash': tx_hash,
            'region': region,
            'platform': 'GuiHua Web3 (Arweave)'
        }
        storage_id, storage_type, last_error = upload_to_arweave_with_retry(payload, retries=3)
        if not storage_id:
            print(f"[create_post] 永存档案写入失败: {last_error}")
            _log_flow_event('post_storage_failed', tx_hash=tx_hash, reason=last_error)
            _svc_upsert_pending_publication(
                PendingPublication, db.session, g.current_user.id, tx_hash,
                payload=pending_payload, status='awaiting_retry',
                last_error='支付已确认，但永存档案写入失败。可直接继续发布重试，无需再次支付。'
            )
            db.session.commit()
            err_msg = '永存档案写入失败。您的支付已确认，无需再次支付，请稍后点击「重试发布」再试。'
            if last_error:
                err_msg += f' 原因: {last_error}'
            return jsonify({'error': err_msg, 'code': 'ARWEAVE_FAIL'}), 503
        ipfs_cid = storage_id
        _log_flow_event('post_storage_ready', tx_hash=tx_hash, ipfs_cid=ipfs_cid)
        _svc_upsert_pending_publication(
            PendingPublication, db.session, g.current_user.id, tx_hash,
            payload=pending_payload, status='storage_ready', ipfs_cid=ipfs_cid
        )
        db.session.commit()

    # 防重复：保存前再次确认该交易哈希未被任何帖子使用（与 verify_transaction + unique 约束三重保险，防并发）
    if tx_hash:
        existing_post = Post.query.filter_by(tx_hash=tx_hash).first()
        if existing_post:
            _log_flow_event('post_duplicate_tx', tx_hash=tx_hash, existing_post_id=existing_post.id)
            return jsonify({'error': '该交易已用于其他帖子'}), 400

    # 4. Create Post（正文 HTML 允许 img 等，需放行 img 属性防 XSS）
    clean_content = _bleach_clean_post_content(data.get('content', ''))
    clean_title = bleach.clean(data.get('title', ''), strip=True)
    if not clean_title or not clean_title.strip():
        _log_flow_event('post_publish_blocked', reason='empty_title')
        return jsonify({'error': '标题不能为空'}), 400
    if not clean_content or not clean_content.strip():
        _log_flow_event('post_publish_blocked', reason='empty_content')
        return jsonify({'error': '正文不能为空'}), 400

    # 封面功能已下线：新帖统一不写入封面
    cover_image = None
    is_special_announcement = bool(data.get('is_special_announcement')) if g.current_user.is_admin else False
    post = Post(
        title=clean_title,
        content=clean_content,
        cover_image=cover_image,
        images=json.dumps(data.get('images', [])),
        tags=json.dumps(normalized_tags, ensure_ascii=False),
        author_id=g.current_user.id,
        tx_hash=tx_hash,
        ipfs_cid=ipfs_cid,
        is_paid=is_paid,
        is_on_chain=is_on_chain,
        region=region,
        is_special_announcement=is_special_announcement,
        post_type=1 if is_on_chain else 0
    )
    
    try:
        db.session.add(post)
        db.session.flush() # Get ID for votes
        
        # 5. Handle Votes
        if vote_options and isinstance(vote_options, list):
            for opt in vote_options:
                if opt and isinstance(opt, str) and len(opt.strip()) > 0:
                    clean_opt = bleach.clean(opt.strip(), strip=True)
                    vote = Vote(post_id=post.id, option_text=clean_opt)
                    db.session.add(vote)

        if target_series:
            max_order = db.session.query(func.max(SeriesPost.order_index)).filter(SeriesPost.series_id == target_series.id).scalar() or 0
            db.session.add(SeriesPost(series_id=target_series.id, post_id=post.id, order_index=int(max_order) + 1))
        
        # 6. Record Transaction (Prevent Replay)
        if tx_hash and not g.current_user.is_admin:
            used_tx = UsedTransaction(tx_hash=tx_hash, user_id=g.current_user.id)
            db.session.add(used_tx)

        # Mentions in post content (optional enhancement)
        mention_source = re.sub(r'<[^>]+>', ' ', clean_content or '')
        mention_tokens = _extract_mention_tokens(mention_source)
        mention_users = _resolve_mentioned_users(mention_tokens, exclude_user_id=g.current_user.id)
        for u in mention_users:
            db.session.add(Notification(
                user_id=u.id,
                sender_id=g.current_user.id,
                post_id=post.id,
                comment_id=None,
                type='mention',
                content='在帖子中提到了你',
                link=f"/?post={post.id}"
            ))
            
        db.session.commit()
        if tx_hash and not g.current_user.is_admin:
            _svc_clear_pending_publication(PendingPublication, db.session, tx_hash=tx_hash)
            db.session.commit()
        _log_flow_event(
            'post_publish_success',
            post_id=post.id,
            tx_hash=tx_hash,
            ipfs_cid=ipfs_cid,
            is_on_chain=is_on_chain,
            series_id=getattr(target_series, 'id', None),
            mentions=len(mention_users),
            votes=len(vote_options or []),
        )
    except Exception as e:
        db.session.rollback()
        err_str = str(e).lower()
        _log_flow_event('post_publish_failed', tx_hash=tx_hash, reason=str(e)[:180])
        if tx_hash and not g.current_user.is_admin:
            try:
                _svc_upsert_pending_publication(
                    PendingPublication, db.session, g.current_user.id, tx_hash,
                    payload=pending_payload, status='awaiting_retry',
                    last_error='支付已确认，但发布流程未完成。可直接继续发布重试。', ipfs_cid=ipfs_cid
                )
                db.session.commit()
            except Exception:
                db.session.rollback()
        if 'unique' in err_str and 'tx_hash' in err_str:
            return jsonify({'error': '该交易已被使用'}), 400
        # 管理员发帖常见：数据库 tx_hash/ipfs_cid 为 NOT NULL 时插 None 会报错
        if 'null' in err_str or 'not null' in err_str:
            print(f"Create Post DB Error (nullable?): {e}")
            traceback.print_exc()
            return jsonify({
                'error': '发帖失败：数据库字段不允许为空。请确认 posts 表的 tx_hash、ipfs_cid 列已设为允许 NULL（管理员发帖无需上链）。'
            }), 500
        print(f"Create Post DB Error: {e}")
        traceback.print_exc()
        app.logger.exception('Create post failed: user_id=%s tx_hash=%s', getattr(g.current_user, 'id', None), tx_hash)
        return jsonify({'error': '服务器暂时不可用，请稍后重试'}), 500
    
    return jsonify({'message': '帖子已发布', 'post': post.to_dict()}), 201

# 浏览量防刷：同一 IP 对同一帖子 60 秒内只计一次
_view_count_key = {}
_view_count_ttl = 60
_view_count_fallback_warned = False


def _prune_view_count_keys(now):
    global _view_count_key
    # 兼容旧调用点；实际逻辑已收口到 services.runtime_state。
    _ = now
    return None


def _allow_view_count_increment(post_id, ip):
    redis_conn = _get_redis_client()
    global _view_count_fallback_warned
    allowed, warned, warn_message = _svc_allow_view_count_increment(
        _view_count_key,
        redis_conn,
        _view_count_ttl,
        post_id,
        ip,
        fallback_warned=_view_count_fallback_warned,
    )
    _view_count_fallback_warned = warned
    if warn_message:
        try:
            print(warn_message)
        except Exception:
            pass
    return allowed

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        payload = _get_optional_jwt_payload()
        current_user_id = payload.get('user_id') if payload else None
        viewer = User.query.get(current_user_id) if current_user_id else None
        if post.is_hidden and not (viewer and (viewer.is_admin or viewer.id == post.author_id)):
            return jsonify({'error': '帖子不存在'}), 404
        # 浏览量 +1（同 IP 60 秒内仅计一次）
        try:
            ip = (request.remote_addr or 'unknown').strip()
            if _allow_view_count_increment(post_id, ip):
                post.view_count = getattr(post, 'view_count', 0) or 0
                post.view_count += 1
                db.session.commit()
        except Exception:
            db.session.rollback()
            
        post_data = post.to_dict(current_user_id)

        from sqlalchemy.orm import joinedload
        all_comments = Comment.query.filter_by(post_id=post_id).options(
            joinedload(Comment.author)
        ).order_by(Comment.created_at.asc()).all()
        comment_like_counts = {}
        liked_comment_ids = set()
        comment_ids = [c.id for c in all_comments]
        if comment_ids:
            like_rows = db.session.query(
                CommentLike.comment_id, func.count(CommentLike.id)
            ).filter(
                CommentLike.comment_id.in_(comment_ids)
            ).group_by(CommentLike.comment_id).all()
            comment_like_counts = {r[0]: int(r[1] or 0) for r in like_rows}
            if current_user_id:
                liked_comment_ids = {
                    row.comment_id for row in CommentLike.query.filter(
                        CommentLike.user_id == current_user_id,
                        CommentLike.comment_id.in_(comment_ids)
                    ).all()
                }
        post_data['comments'] = build_comment_tree(
            all_comments,
            like_counts=comment_like_counts,
            liked_comment_ids=liked_comment_ids
        )
        post_data['comments_count'] = len(all_comments)

        series_items = []
        link_rows = SeriesPost.query.filter_by(post_id=post_id).order_by(SeriesPost.order_index.asc()).all()
        for link in link_rows:
            s = link.series
            if not s:
                continue
            if not _series_can_view(s, viewer):
                continue
            prev_row = SeriesPost.query.filter(
                SeriesPost.series_id == s.id,
                SeriesPost.order_index < link.order_index
            ).order_by(SeriesPost.order_index.desc()).first()
            next_row = SeriesPost.query.filter(
                SeriesPost.series_id == s.id,
                SeriesPost.order_index > link.order_index
            ).order_by(SeriesPost.order_index.asc()).first()
            series_items.append({
                'series_id': s.id,
                'title': s.title,
                'order_index': link.order_index,
                'prev_post_id': prev_row.post_id if prev_row else None,
                'next_post_id': next_row.post_id if next_row else None
            })
        post_data['series'] = series_items
            
        return jsonify(post_data)
    except Exception as e:
        print(f"Post Detail Error: {e}")
        return jsonify({'error': '加载帖子失败，请稍后重试'}), 500

@app.route('/api/posts/<int:post_id>/sync-arweave', methods=['POST'])
@token_required
def sync_post_to_arweave(post_id):
    """将已有帖子内容同步到 Arweave，生成永存档案（仅作者或管理员；帖子需有 tx_hash 且尚未有 ipfs_cid）。"""
    post = Post.query.get_or_404(post_id)
    if post.author_id != g.current_user.id and not getattr(g.current_user, 'is_admin', False):
        return jsonify({'error': '仅作者或管理员可操作'}), 403
    if not post.tx_hash:
        return jsonify({'error': '该帖子无支付凭证，无法同步到 Arweave'}), 400
    if post.ipfs_cid:
        return jsonify({'error': '该帖子已有永存档案', 'ipfs_cid': post.ipfs_cid}), 400
    author_address = (post.author.wallet_address or post.author.address or '').strip() if post.author else ''
    payload = {
        'title': post.title,
        'content': post.content or '',
        'author': author_address,
        'timestamp': post.created_at.isoformat() if post.created_at else datetime.utcnow().isoformat(),
        'tx_hash': post.tx_hash,
        'region': getattr(post, 'region', '其他') or '其他',
        'platform': 'GuiHua Web3 (Arweave)'
    }
    ar_tx_id, _ = upload_to_arweave_native(payload)
    if not ar_tx_id:
        return jsonify({'error': 'Arweave 上传失败，请稍后重试'}), 503
    post.ipfs_cid = ar_tx_id
    db.session.commit()
    return jsonify({'message': '已同步到 Arweave', 'ipfs_cid': ar_tx_id, 'arweave_url': f'https://arweave.net/{ar_tx_id}'})

@app.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    content = data.get('content', '')
    
    original_post = Post.query.get_or_404(post_id)
    target_id = original_post.original_post_id if original_post.original_post_id else post_id
    
    clean_comment = bleach.clean(content, tags=[], strip=True)

    new_post = Post(
        title=bleach.clean(f"转发: {original_post.title}", strip=True),
        content="",
        repost_comment=clean_comment,
        author_id=g.current_user.id,
        is_repost=True,
        original_post_id=target_id,
        is_paid=True
    )
    
    db.session.add(new_post)
    db.session.commit()
    return jsonify(new_post.to_dict()), 201

@app.route('/api/posts/<int:post_id>/vote', methods=['POST'])
@token_required
def vote_post(post_id):
    post = Post.query.get_or_404(post_id)
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    option_id = data.get('option_id')
    
    if not option_id:
        return jsonify({'error': '缺少投票选项'}), 400
        
    vote_option = Vote.query.get(option_id)
    if not vote_option or vote_option.post_id != post_id:
        return jsonify({'error': '投票选项无效'}), 400
    
    # 单选：同一用户在同一帖子只能投一次（不允许投多个选项）
    existing_vote = db.session.query(UserVote.id).join(
        Vote, UserVote.vote_id == Vote.id
    ).filter(
        UserVote.user_id == g.current_user.id,
        Vote.post_id == post_id
    ).first()
    if existing_vote:
        return jsonify({'error': '你已经参与过这篇帖子的投票'}), 400
    
    # Record vote
    try:
        user_vote = UserVote(user_id=g.current_user.id, vote_id=option_id)
        db.session.add(user_vote)
        vote_option.vote_count += 1
        db.session.commit()
    except Exception as e: # IntegrityError catch
        db.session.rollback()
        return jsonify({'error': '你已经投过票了'}), 400
    
    return jsonify({
        'message': '投票成功',
        'votes': [v.to_dict() for v in post.votes]
    })

# --- Interactions ---

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def add_comment(post_id):
    if _rate_limit('comment', 40):
        return jsonify({'error': '评论过于频繁，请稍后再试'}), 429
    post = Post.query.get_or_404(post_id)
    if not post.allow_comments and not g.current_user.is_admin:
        _log_flow_event('comment_blocked', post_id=post_id, reason='comments_closed')
        return jsonify({'error': '这篇帖子已关闭评论'}), 403

    data = request.get_json(silent=True) or {}
    if not data:
        _log_flow_event('comment_blocked', post_id=post_id, reason='empty_payload')
        return jsonify({'error': '请求体不能为空'}), 400
    content = data.get('content')
    raw_parent_id = data.get('parent_id')
    parent_id = None
    
    if not content:
        _log_flow_event('comment_blocked', post_id=post_id, reason='empty_content')
        return jsonify({'error': '评论内容不能为空'}), 400
    
    clean_content = bleach.clean(content, tags=[], strip=True)
    
    # parent_id 仅允许正整数；0/空统一视为无父评论，避免脏数据写入 parent_id=0。
    parent_comment = None
    if raw_parent_id not in (None, '', 0, '0'):
        try:
            parent_id = int(raw_parent_id)
        except Exception:
            _log_flow_event('comment_parent_invalid', post_id=post_id, parent_id=raw_parent_id)
            return jsonify({'error': '父评论参数无效'}), 400
        if parent_id <= 0:
            _log_flow_event('comment_parent_invalid', post_id=post_id, parent_id=raw_parent_id)
            return jsonify({'error': '父评论参数无效'}), 400
        parent_comment = Comment.query.get(parent_id)
        if not parent_comment or parent_comment.post_id != post_id:
            _log_flow_event('comment_parent_missing', post_id=post_id, parent_id=parent_id)
            return jsonify({'error': '父评论不存在或不属于当前帖子'}), 400
    
    comment = Comment(content=clean_content, author_id=g.current_user.id, post_id=post.id, parent_id=parent_id)
    db.session.add(comment)
    db.session.commit()
    _log_flow_event('comment_created', post_id=post.id, comment_id=comment.id, parent_id=parent_id)
    
    # Notification Logic
    try:
        notified_user_ids = set()
        if parent_id is not None:
            # Reply to comment
            if parent_comment and parent_comment.author_id != g.current_user.id:
                notif = Notification(
                    user_id=parent_comment.author_id,
                    sender_id=g.current_user.id,
                    post_id=post.id,
                    comment_id=comment.id,
                    type='reply',
                    content='回复了你的评论',
                    link=f"/?post={post.id}"
                )
                db.session.add(notif)
                notified_user_ids.add(parent_comment.author_id)
        elif post.author_id != g.current_user.id:
            # Comment on post
            notif = Notification(
                user_id=post.author_id,
                sender_id=g.current_user.id,
                post_id=post.id,
                comment_id=comment.id,
                type='comment',
                content='评论了你的帖子',
                link=f"/?post={post.id}"
            )
            db.session.add(notif)
            notified_user_ids.add(post.author_id)

        # Mentions in comment content
        mention_tokens = _extract_mention_tokens(clean_content)
        mention_users = _resolve_mentioned_users(mention_tokens, exclude_user_id=g.current_user.id)
        for u in mention_users:
            if u.id in notified_user_ids:
                continue
            db.session.add(Notification(
                user_id=u.id,
                sender_id=g.current_user.id,
                post_id=post.id,
                comment_id=comment.id,
                type='mention',
                content='在评论中提到了你',
                link=f"/?post={post.id}"
            ))
            notified_user_ids.add(u.id)
        db.session.commit()
    except Exception as e:
        print(f"Notification Error: {e}")

    return jsonify({'message': '评论已发布', 'comment': comment.to_dict()}), 201


@app.route('/api/comments/<int:comment_id>/like', methods=['POST'])
@token_required
def toggle_comment_like(comment_id):
    comment = Comment.query.get_or_404(comment_id)
    post = Post.query.get(comment.post_id) if comment.post_id else None
    if not post:
        return jsonify({'error': '帖子不存在'}), 404
    if post.is_hidden and not (g.current_user.is_admin or post.author_id == g.current_user.id):
        return jsonify({'error': '没有权限操作该评论'}), 403

    like = CommentLike.query.filter_by(user_id=g.current_user.id, comment_id=comment_id).first()
    if like:
        db.session.delete(like)
        liked = False
        msg = '已取消评论点赞'
    else:
        db.session.add(CommentLike(user_id=g.current_user.id, comment_id=comment_id))
        liked = True
        msg = '已点赞评论'
    db.session.commit()
    likes_count = CommentLike.query.filter_by(comment_id=comment_id).count()
    return jsonify({'message': msg, 'liked': liked, 'likes_count': likes_count, 'comment_id': comment_id})


@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    try:
        like = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
        if like:
            db.session.delete(like)
            msg = '已取消恐惧'
        else:
            db.session.add(Like(user_id=g.current_user.id, post_id=post.id))
            msg = '已恐惧'
            # Notification
            if post.author_id != g.current_user.id:
                notif = Notification(
                    user_id=post.author_id,
                    sender_id=g.current_user.id,
                    post_id=post.id,
                    type='like',
                    content='点赞了你的帖子',
                    link=f"/?post={post.id}"
                )
                db.session.add(notif)
        db.session.commit()
        return jsonify({'message': msg})
    except Exception as e:
        db.session.rollback()
        # If it's an integrity error, it means we tried to like a liked post (race condition)
        # We can treat it as 'already liked'
        app.logger.exception('Like post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'message': '操作失败，请稍后重试'}), 400

@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    try:
        bm = Bookmark.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
        if bm:
            db.session.delete(bm)
            msg = '已取消收藏'
        else:
            db.session.add(Bookmark(user_id=g.current_user.id, post_id=post.id))
            msg = '已收藏'
        db.session.commit()
        return jsonify({'message': msg})
    except Exception as e:
        db.session.rollback()
        app.logger.exception('Bookmark post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'message': '操作失败，请稍后重试'}), 400

@app.route('/api/upload', methods=['POST'])
@token_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['file']
    if not file or (getattr(file, 'filename', None) or '').strip() == '':
        return jsonify({'error': '未选择文件'}), 400
    url, err = upload_to_imgbb(file)
    if url:
        return jsonify({'url': url})
    return jsonify({'error': err or '上传失败'}), 500

# --- Admin & Debug ---

# 打赏最低 1 USDT（最小单位）
TIP_MIN_USDT_RAW = 10 ** USDT_DECIMALS


def _tip_amount_to_usdt_str(raw_amount):
    return _svc_tip_amount_to_usdt_str(raw_amount, app.config['BSC']['USDT_DECIMALS'])


@app.route('/api/users/<int:user_id>/tips-received', methods=['GET'])
def list_tips_received(user_id):
    user = User.query.get_or_404(user_id)
    payload = _get_optional_jwt_payload()
    viewer_id = payload.get('user_id') if payload else None
    viewer = User.query.get(viewer_id) if viewer_id else None
    is_owner = bool(viewer and viewer.id == user.id)
    is_admin = bool(viewer and viewer.is_admin)
    if not (is_owner or is_admin or bool(getattr(user, 'show_tip_thanks', False))):
        return jsonify({'error': '作者未开启感谢名单展示'}), 403

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    include_amount = (request.args.get('show_amount') or '').strip().lower() in ('1', 'true', 'yes')
    if not (is_owner or is_admin):
        include_amount = False

    q = Tip.query.filter_by(to_user_id=user.id).order_by(Tip.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    rows = []
    for t in pagination.items:
        sender = t.sender.to_dict() if t.sender else None
        item = {
            'id': t.id,
            'post_id': t.post_id,
            'token_symbol': t.token_symbol or 'USDT',
            'tx_hash': t.tx_hash,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'from_user': sender,
        }
        if include_amount:
            item['amount_usdt'] = _tip_amount_to_usdt_str(t.amount)
        rows.append(item)
    return jsonify({
        'items': rows,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'show_amount': include_amount,
        'show_tip_thanks': bool(getattr(user, 'show_tip_thanks', False))
    })


@app.route('/api/posts/<int:post_id>/tips', methods=['GET'])
def list_post_tips(post_id):
    post = Post.query.get_or_404(post_id)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    q = Tip.query.filter_by(post_id=post.id).order_by(Tip.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    rows = []
    for t in pagination.items:
        rows.append({
            'id': t.id,
            'from_user': t.sender.to_dict() if t.sender else None,
            'created_at': t.created_at.isoformat() if t.created_at else None
        })
    return jsonify({
        'items': rows,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'post_id': post.id
    })


@app.route('/api/tips/verify', methods=['POST'])
@token_required
def verify_tip():
    """打赏直接转入作者钱包：验证 USDT 转至作者地址后仅记账（展示打赏记录），不经过平台、不抽成、不写入可提现余额。"""
    if _rate_limit('tip_verify', 30):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    tx_hash = data.get('tx_hash')
    post_id = data.get('post_id')
    if not tx_hash or not post_id:
        return jsonify({'error': '缺少必要参数'}), 400
    post = Post.query.get_or_404(post_id)
    if not post.author:
        return jsonify({'error': '未找到帖子作者'}), 400
    author_address = (post.author.wallet_address or post.author.address or '').strip()
    if not author_address or not Web3.is_address(author_address):
        return jsonify({'error': '作者未绑定钱包，暂无法打赏'}), 400
    is_valid, result = verify_transaction(
        tx_hash, 
        g.current_user.address, 
        expected_recipient=author_address,
        min_amount=TIP_MIN_USDT_RAW,
        payment_type='usdt'
    )
    if not is_valid:
        return jsonify({'error': _humanize_verify_error(result)}), 400
    amount_full = int(result)
    if Tip.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': '该打赏交易已记录，无需重复提交'}), 400
    decimals = app.config['BSC']['USDT_DECIMALS']
    tip = Tip(
        tx_hash=tx_hash,
        from_user_id=g.current_user.id,
        to_user_id=post.author.id,
        post_id=post.id,
        amount=str(amount_full)
    )
    used_tx = UsedTransaction(tx_hash=tx_hash, user_id=g.current_user.id)
    try:
        db.session.add(tip)
        db.session.add(used_tx)
        if post.author.id != g.current_user.id:
            notif = Notification(
                user_id=post.author.id,
                sender_id=g.current_user.id,
                post_id=post.id,
                type='tip',
                content='给你打赏了帖子',
                link=f"/?post={post.id}"
            )
            db.session.add(notif)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.exception('Verify tip failed: post_id=%s user_id=%s tx_hash=%s', post_id, getattr(g.current_user, 'id', None), tx_hash)
        return jsonify({'error': '服务器错误，请稍后重试'}), 500
    amount_usdt = amount_full / (10 ** decimals)
    return jsonify({
        'message': '打赏成功，已直接转入作者钱包',
        'tip': {
            'amount': str(amount_full),
            'tx_hash': tx_hash,
            'amount_usdt': round(amount_usdt, 2),
            'author_receives_usdt': round(amount_usdt, 2),
        }
    })

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Allow admin or author to delete
    if not g.current_user.is_admin and post.author_id != g.current_user.id:
        return jsonify({'error': '没有权限删除该帖子'}), 403
    
    try:
        # 先删除 user_votes，避免 votes 被删时触发外键约束失败。
        vote_ids = [row[0] for row in db.session.query(Vote.id).filter(Vote.post_id == post.id).all()]
        if vote_ids:
            UserVote.query.filter(UserVote.vote_id.in_(vote_ids)).delete(synchronize_session=False)

        # 清理与该帖相关的引用，确保无外键阻塞并保留审计记录。
        Notification.query.filter(Notification.post_id == post.id).update({'post_id': None}, synchronize_session=False)
        Report.query.filter(Report.post_id == post.id).update({'post_id': None}, synchronize_session=False)
        Tip.query.filter(Tip.post_id == post.id).update({'post_id': None}, synchronize_session=False)
        SeriesPost.query.filter(SeriesPost.post_id == post.id).delete(synchronize_session=False)

        # 删除强关联互动数据
        comment_ids = [row[0] for row in db.session.query(Comment.id).filter(Comment.post_id == post.id).all()]
        if comment_ids:
            CommentLike.query.filter(CommentLike.comment_id.in_(comment_ids)).delete(synchronize_session=False)
        Comment.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        Like.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        Bookmark.query.filter_by(post_id=post.id).delete(synchronize_session=False)
        Vote.query.filter_by(post_id=post.id).delete(synchronize_session=False)

        db.session.delete(post)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        app.logger.exception('Delete post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'error': '删除失败，请稍后重试'}), 500
    if g.current_user.is_admin:
        _log_admin_action('post_delete', 'post', post_id)
    return jsonify({'message': '帖子已删除'})

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
@token_required
def update_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Only author can edit
    if post.author_id != g.current_user.id:
        return jsonify({'error': '没有权限编辑该帖子'}), 403
        
    # Cannot edit if on-chain (immutable)
    if post.is_on_chain:
        return jsonify({'error': '链上内容不可编辑'}), 400
        
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    title = data.get('title')
    content = data.get('content')
    
    if title:
        post.title = bleach.clean(title, strip=True)
    if content:
        post.content = _bleach_clean_post_content(content)
    if 'tags' in data or 'tag_names' in data:
        post.tags = json.dumps(_normalize_tags(data.get('tags') or data.get('tag_names')), ensure_ascii=False)
        
    db.session.commit()
    return jsonify({'message': '帖子已更新', 'post': post.to_dict()})

@app.route('/api/admin/posts/<int:post_id>/hide', methods=['POST'])
@token_required
@admin_required
def toggle_hide_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_hidden = not post.is_hidden
    db.session.commit()
    _log_admin_action('post_toggle_hide', 'post', post_id, f"is_hidden={post.is_hidden}")
    return jsonify({'message': '帖子可见状态已更新', 'is_hidden': post.is_hidden})


@app.route('/api/admin/posts/<int:post_id>/pin', methods=['POST'])
@token_required
@admin_required
def toggle_pin_post(post_id):
    """管理员置顶/取消置顶；默认全站仅保留一个置顶帖。"""
    post = Post.query.get_or_404(post_id)
    payload = request.get_json(silent=True) or {}
    should_pin = payload.get('pinned')
    if should_pin is None:
        should_pin = not bool(post.is_pinned)
    should_pin = bool(should_pin)
    exclusive = payload.get('exclusive', True)

    if should_pin and exclusive:
        Post.query.filter(Post.id != post.id, Post.is_pinned == True).update({
            'is_pinned': False,
            'pinned_at': None,
            'pinned_by': None
        }, synchronize_session=False)

    post.is_pinned = should_pin
    post.pinned_at = datetime.utcnow() if should_pin else None
    post.pinned_by = g.current_user.id if should_pin else None
    db.session.commit()
    _log_admin_action('post_pin_toggle', 'post', post_id, f"is_pinned={post.is_pinned}")
    return jsonify({
        'message': '已置顶' if should_pin else '已取消置顶',
        'is_pinned': post.is_pinned,
        'pinned_at': post.pinned_at.isoformat() if post.pinned_at else None
    })

@app.route('/api/admin/posts/<int:post_id>/toggle-comments', methods=['POST'])
@token_required
@admin_required
def toggle_post_comments(post_id):
    """管理员切换帖子「允许评论」状态。与 POST .../comments（发表评论）区分开。"""
    post = Post.query.get_or_404(post_id)
    post.allow_comments = not post.allow_comments
    db.session.commit()
    _log_admin_action('post_toggle_comments', 'post', post_id, f"allow_comments={post.allow_comments}")
    return jsonify({'message': '评论权限已更新', 'allow_comments': post.allow_comments})

@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@token_required
@admin_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        return jsonify({'error': '不能封禁管理员'}), 400
        
    user.is_banned = not user.is_banned
    db.session.commit()
    _log_admin_action('user_ban_toggle', 'user', user_id, f"is_banned={user.is_banned}")
    return jsonify({'message': '用户封禁状态已更新', 'is_banned': user.is_banned})

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


@app.route('/api/admin/announcements', methods=['GET'])
@token_required
@admin_required
def list_announcements():
    rows = Announcement.query.order_by(Announcement.created_at.desc()).limit(100).all()
    return jsonify({'announcements': [a.to_dict() for a in rows]})


@app.route('/api/admin/announcements', methods=['POST'])
@token_required
@admin_required
def create_announcement():
    data = request.get_json(silent=True) or {}
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    level = (data.get('level') or 'info').strip().lower()
    entry_type = (data.get('entry_type') or 'announcement').strip().lower()
    starts_at = _parse_iso_datetime(data.get('starts_at'))
    expires_at = _parse_iso_datetime(data.get('expires_at'))
    activate_now = bool(data.get('activate', True))
    if not title or not content:
        return jsonify({'error': '标题和内容不能为空'}), 400
    if len(title) > 120 or len(content) > 1000:
        return jsonify({'error': '标题或内容过长'}), 400
    if level not in ('info', 'warning', 'critical'):
        return jsonify({'error': 'level 仅支持 info/warning/critical'}), 400
    if entry_type not in ('announcement', 'activity'):
        return jsonify({'error': 'entry_type 仅支持 announcement/activity'}), 400

    if activate_now:
        Announcement.query.filter(Announcement.entry_type == entry_type).update({'is_active': False}, synchronize_session=False)
    ann = Announcement(
        title=title,
        content=content,
        entry_type=entry_type,
        level=level,
        is_active=activate_now,
        starts_at=starts_at,
        expires_at=expires_at,
        created_by=g.current_user.id
    )
    db.session.add(ann)
    db.session.commit()
    _log_admin_action('announcement_create', 'announcement', ann.id, f"title={title}")
    return jsonify({'message': '公告已创建', 'announcement': ann.to_dict()}), 201


@app.route('/api/admin/announcements/<int:announcement_id>', methods=['PUT'])
@token_required
@admin_required
def update_announcement(announcement_id):
    ann = Announcement.query.get_or_404(announcement_id)
    data = request.get_json(silent=True) or {}
    if 'title' in data:
        ann.title = (data.get('title') or '').strip()[:120]
    if 'content' in data:
        ann.content = (data.get('content') or '').strip()[:1000]
    if 'entry_type' in data:
        entry_type = (data.get('entry_type') or 'announcement').strip().lower()
        if entry_type not in ('announcement', 'activity'):
            return jsonify({'error': 'entry_type 仅支持 announcement/activity'}), 400
        ann.entry_type = entry_type
    if 'level' in data:
        level = (data.get('level') or 'info').strip().lower()
        if level not in ('info', 'warning', 'critical'):
            return jsonify({'error': 'level 仅支持 info/warning/critical'}), 400
        ann.level = level
    if 'starts_at' in data:
        ann.starts_at = _parse_iso_datetime(data.get('starts_at'))
    if 'expires_at' in data:
        ann.expires_at = _parse_iso_datetime(data.get('expires_at'))
    if 'is_active' in data:
        make_active = bool(data.get('is_active'))
        if make_active:
            Announcement.query.filter(
                Announcement.id != ann.id,
                Announcement.entry_type == ann.entry_type
            ).update({'is_active': False}, synchronize_session=False)
        ann.is_active = make_active
    db.session.commit()
    _log_admin_action('announcement_update', 'announcement', ann.id)
    return jsonify({'message': '公告已更新', 'announcement': ann.to_dict()})


@app.route('/api/admin/announcements/<int:announcement_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_announcement(announcement_id):
    ann = Announcement.query.get_or_404(announcement_id)
    db.session.delete(ann)
    db.session.commit()
    _log_admin_action('announcement_delete', 'announcement', announcement_id)
    return jsonify({'message': '公告已删除'})


@app.route('/api/admin/audit-logs', methods=['GET'])
@token_required
@admin_required
def list_admin_audit_logs():
    limit = min(request.args.get('limit', 100, type=int), 300)
    rows = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(limit).all()
    return jsonify({'logs': [r.to_dict() for r in rows]})

@app.route('/api/reports', methods=['POST'])
@token_required
def create_report():
    """用户举报帖子或用户。"""
    if _rate_limit('report', 20):
        return jsonify({'error': '举报过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    post_id = data.get('post_id')
    reported_user_id = data.get('reported_user_id')
    reason = (data.get('reason') or '').strip()
    if not reason or len(reason) > 500:
        _log_flow_event('report_blocked', reason='invalid_reason')
        return jsonify({'error': '请填写举报原因（最多500字）'}), 400
    if not post_id and not reported_user_id:
        _log_flow_event('report_blocked', reason='missing_target')
        return jsonify({'error': '请指定举报的帖子或用户'}), 400
    target_type = 'user'
    target_id = 0
    if post_id:
        post = Post.query.get(post_id)
        if not post:
            _log_flow_event('report_blocked', reason='post_missing', post_id=post_id)
            return jsonify({'error': '帖子不存在'}), 404
        reported_user_id = post.author_id
        target_type = 'post'
        target_id = int(post_id)
    elif reported_user_id:
        target_type = 'user'
        try:
            target_id = int(reported_user_id)
        except (TypeError, ValueError):
            _log_flow_event('report_blocked', reason='invalid_user_id', reported_user_id=reported_user_id)
            return jsonify({'error': '被举报用户 ID 非法'}), 400
    r = Report(
        reporter_id=g.current_user.id,
        target_type=target_type,
        target_id=target_id,
        reported_user_id=reported_user_id,
        post_id=post_id,
        reason=reason,
        status='pending'
    )
    db.session.add(r)
    db.session.commit()
    _log_flow_event('report_created', report_id=r.id, target_type=target_type, target_id=target_id, post_id=post_id)
    return jsonify({'message': '举报已提交，管理员会尽快处理', 'id': r.id}), 201


@app.route('/api/reports/priority', methods=['POST'])
@token_required
def report_priority():
    if _rate_limit('report_priority', 20):
        return jsonify({'error': '举报过于频繁，请稍后再试'}), 429
    level = _get_user_level(g.current_user)
    is_admin = bool(getattr(g.current_user, 'is_admin', False))
    if is_admin:
        level = 9999
    if level < 2:
        _log_flow_event('priority_report_blocked', reason='level_too_low', level=level)
        return jsonify({'error': '等级达到 2 才能解锁该举报权限'}), 403
    data = request.get_json(silent=True) or {}
    extra_reason = (data.get('reason') or '').strip()
    if len(extra_reason) > 460:
        _log_flow_event('priority_report_blocked', reason='reason_too_long')
        return jsonify({'error': '补充说明最多 460 字'}), 400
    reason = '等级权益举报'
    if extra_reason:
        reason = f'{reason} | {extra_reason}'
    row = Report(
        reporter_id=g.current_user.id,
        target_type='user',
        target_id=0,
        reported_user_id=None,
        post_id=None,
        reason=reason,
        status='pending'
    )
    db.session.add(row)
    db.session.commit()
    _log_flow_event('priority_report_created', report_id=row.id, level=level)
    return jsonify({'message': '已提交快速举报', 'id': row.id}), 201

@app.route('/api/admin/reports', methods=['GET'])
@token_required
@admin_required
def list_reports():
    """管理员查看举报列表。"""
    status = request.args.get('status')
    q = Report.query.order_by(Report.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    reports = q.limit(200).all()
    return jsonify([r.to_dict() for r in reports])

@app.route('/api/admin/reports/<int:report_id>', methods=['PUT'])
@token_required
@admin_required
def update_report(report_id):
    """管理员处理举报：status=resolved|dismissed, admin_notes=..."""
    r = Report.query.get_or_404(report_id)
    data = request.get_json(silent=True) or {}
    old_status = (r.status or '').strip()
    if data.get('status') in ('resolved', 'dismissed'):
        r.status = data['status']
    if ('admin_notes' in data) or ('admin_note' in data):
        notes = (data.get('admin_notes', data.get('admin_note')) or '')[:500]
        r.admin_notes = notes
        # 兼容历史字段：统一同步写入，后续可在迁移后移除 admin_note。
        r.admin_note = notes
    should_notify_result = (
        r.reporter_id
        and r.status in ('resolved', 'dismissed')
        and r.status != old_status
        and r.result_notified_at is None
    )
    if should_notify_result:
        msg = '您提交的举报已处理，感谢反馈。' if r.status == 'resolved' else '您提交的举报经核实暂不处理。'
        notif = Notification(
            user_id=r.reporter_id,
            sender_id=g.current_user.id,
            post_id=r.post_id,
            type='report_result',
            content=msg,
            link=f"/?post={r.post_id}" if r.post_id else None
        )
        db.session.add(notif)
        r.result_notified_at = datetime.utcnow()
    db.session.commit()
    _log_admin_action('report_update', 'report', report_id, f"status={r.status}")
    _log_flow_event('report_updated', report_id=report_id, old_status=old_status, new_status=r.status, notified=bool(should_notify_result))
    return jsonify({'message': '已更新', 'report': r.to_dict()})

# /api/debug/seed 已移除，生产环境不可暴露造数接口；造数请用 Flask shell 或独立脚本

def _load_seed_article_content():
    path = app.config.get('SEED_ARTICLE_PATH')
    content = _svc_load_text_file(path)
    if not content and path:
        print("Init DB: failed to load seed article content")
    return content


def _ensure_bootstrap_admin():
    """Ensure there is at least one admin. Create one only when env vars are provided."""
    return _svc_ensure_bootstrap_admin(User, db.session, _new_user)


def _seed_default_article(admin_id):
    """Seed one default article for first-time setup."""
    return _svc_seed_default_article(Post, db.session, admin_id, _load_seed_article_content)


def init_db_data():
    """Auto-initialize basic data on startup"""
    try:
        admin = _ensure_bootstrap_admin()
        admin_id = getattr(admin, 'id', None) if admin else None
        if not admin_id:
            admin_id = User.query.filter(User.is_admin == True).with_entities(User.id).scalar()
        _seed_default_article(admin_id)
    except Exception as e:
        print(f"Init Data Error: {e}")

# 生产环境已移除：/api/debug/reset_db、/api/debug/seed（防止误开导致清库/刷数据）
# 数据库变更请使用 Flask-Migrate (alembic)，勿用 drop_all

def _ensure_users_wallet_address():
    """启动时确保 users 表存在 wallet_address 列（Render 等可能为旧 schema）。仅在实际变更时打日志。"""
    return _svc_ensure_users_wallet_address(db.session, db.engine.dialect.name)


def _ensure_users_withdrawable_balance():
    """启动时确保 users 表存在 withdrawable_balance 列。仅在实际变更时打日志。"""
    return _svc_ensure_users_withdrawable_balance(db.session, db.engine.dialect.name)


def _ensure_users_checkin_columns():
    """启动时确保 users 表存在签到经验与成就佩戴相关列。"""
    return _svc_ensure_users_checkin_columns(db.session, db.engine.dialect.name)


def _ensure_checkin_logs_table():
    """启动时确保签到日志表存在（create_all 对历史库补表）。"""
    return _svc_ensure_table(CheckinLog.__table__, db.engine, 'checkin_logs table')


def _ensure_app_settings_table():
    """启动时确保站点配置表存在。"""
    return _svc_ensure_table(AppSetting.__table__, db.engine, 'app_settings table')


def _ensure_pending_publications_table():
    """启动时确保待恢复发布表存在。"""
    return _svc_ensure_table(PendingPublication.__table__, db.engine, 'pending_publications table')


def _ensure_flow_events_table():
    """启动时确保流转事件表存在。"""
    return _svc_ensure_table(FlowEvent.__table__, db.engine, 'flow_events table')

def _ensure_posts_tx_nullable():
    """启动时确保 posts.tx_hash、ipfs_cid 允许 NULL。仅在实际变更时打日志。"""
    return _svc_ensure_posts_tx_nullable(db.session, db.engine.dialect.name)


def _ensure_posts_pin_columns():
    """启动时确保 posts 表存在置顶相关列。"""
    return _svc_ensure_posts_pin_columns(db.session, db.engine.dialect.name)


def _ensure_posts_special_column():
    """启动时确保 posts 表存在特殊公告列。"""
    return _svc_ensure_posts_special_column(db.session, db.engine.dialect.name)


def _ensure_posts_tags_column():
    """启动时确保 posts.tags 列存在。"""
    return _svc_ensure_posts_tags_column(db.session, db.engine.dialect.name)


def _ensure_notifications_columns():
    """启动时确保 notifications.content/link 列存在。"""
    return _svc_ensure_notifications_columns(db.session, db.engine.dialect.name)


def _ensure_reports_columns():
    """启动时兼容 reports 历史表结构（补齐新旧字段并避免 NOT NULL 报错）。"""
    return _svc_ensure_reports_columns(db.session, db.engine.dialect.name)


def _ensure_announcements_columns():
    """启动时兼容 announcements 历史表结构（entry_type / starts_at）。"""
    return _svc_ensure_announcements_columns(db.session, db.engine.dialect.name)


def _ensure_series_tables():
    """启动时确保系列表存在。"""
    _svc_ensure_table(Series.__table__, db.engine, 'series table')
    _svc_ensure_table(SeriesPost.__table__, db.engine, 'series_post table')

def _check_receive_address():
    """启动时检查：未配置 RECEIVE_ADDRESS 时打印明确错误提示（发帖费与站长赞赏需要）。"""
    return _svc_check_receive_address(app.config.get('BSC', {}).get('RECEIVE_ADDRESS'))

# 仅当设置 ALLOW_INIT_DB=true 时执行种子数据（避免每次重启都插测试文章；需造数时在 Render 临时加该环境变量）
def _should_run_init_db():
    return _svc_should_run_init_db()


def _run_startup_tasks():
    db.create_all()
    _ensure_users_wallet_address()
    _ensure_users_withdrawable_balance()
    _ensure_users_checkin_columns()
    _ensure_checkin_logs_table()
    _ensure_app_settings_table()
    _ensure_posts_tx_nullable()
    _ensure_posts_pin_columns()
    _ensure_posts_special_column()
    _ensure_posts_tags_column()
    _ensure_notifications_columns()
    _ensure_reports_columns()
    _ensure_announcements_columns()
    _ensure_series_tables()
    _ensure_pending_publications_table()
    _ensure_flow_events_table()
    if _should_run_init_db():
        init_db_data()
    _check_receive_address()
    _svc_warn_if_redis_missing(
        os.environ.get('REDIS_URL'),
        flask_debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true'
    )
    started, interval = _svc_start_compensation_worker(
        app,
        PendingPublication,
        _resume_pending_publication_row,
        app.logger,
        limit=8,
        min_age_seconds=90,
    )
    if started:
        app.logger.info('[publish-compensation] worker started interval=%ss', interval)

if __name__ == '__main__':
    with app.app_context():
        _run_startup_tasks()
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=int(os.environ.get('PORT', 5001)))
else:
    with app.app_context():
        _run_startup_tasks()
