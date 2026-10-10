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
from flask import Flask, request, jsonify, g, render_template, redirect
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, or_, text
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

from flask_migrate import Migrate
from extensions import db
db.init_app(app)
migrate = Migrate(app, db)

# 区块链与存储逻辑已拆至 services/blockchain.py、services/storage.py
from models import (User, Post, Vote, Comment, Like, CommentLike, Bookmark, Notification, UsedTransaction,
    PendingPublication,
    FlowEvent, UserVote, Tip, Report, Announcement, AdminAuditLog, CheckinLog, AppSetting, Series, SeriesPost,
    build_comment_tree, _comment_to_dict_node, get_random_avatar, ALLOWED_AVATARS,
    calc_level_info, checkin_exp_by_streak)
from utils.security import (_rate_limit, _bearer_token, _get_optional_jwt_payload,
    token_required, admin_required, set_auth_cookie,
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
    extract_mention_tokens as _svc_extract_mention_tokens,
    resolve_mentioned_users as _svc_resolve_mentioned_users,
    series_can_view as _svc_series_can_view,
    series_can_edit as _svc_series_can_edit,
)
from services.app_support import (
    humanize_verify_error as _svc_humanize_verify_error,
    is_post_permanent as _svc_is_post_permanent,
    tip_amount_to_usdt_str as _svc_tip_amount_to_usdt_str,
    compute_asset_version as _svc_compute_asset_version,
    load_text_file as _svc_load_text_file,
)
from services.site_settings import (
    get_setting_value as _svc_get_setting_value,
    get_group_link_urls as _svc_get_group_link_urls,
    validate_group_link_urls as _svc_validate_group_link_urls,
)
from services.publish_recovery import (
    upsert_pending_publication as _svc_upsert_pending_publication,
    clear_pending_publication as _svc_clear_pending_publication,
    get_latest_pending_publication as _svc_get_latest_pending_publication,
)
from services.runtime_state import allow_view_count_increment as _svc_allow_view_count_increment
from services.startup_tasks import (
    ensure_bootstrap_admin as _svc_ensure_bootstrap_admin,
    seed_default_article as _svc_seed_default_article,
    ensure_table as _svc_ensure_table,
    check_receive_address as _svc_check_receive_address,
    warn_if_redis_missing as _svc_warn_if_redis_missing,
    should_run_init_db as _svc_should_run_init_db,
    init_default_data as _svc_init_default_data,
    run_startup_sequence as _svc_run_startup_sequence,
)
from services.schema_compat import (
    ensure_users_wallet_address as _svc_ensure_users_wallet_address,
    ensure_users_withdrawable_balance as _svc_ensure_users_withdrawable_balance,
    ensure_users_checkin_columns as _svc_ensure_users_checkin_columns,
    ensure_posts_tx_nullable as _svc_ensure_posts_tx_nullable,
    ensure_posts_pin_columns as _svc_ensure_posts_pin_columns,
    ensure_posts_special_column as _svc_ensure_posts_special_column,
    ensure_posts_seo_columns as _svc_ensure_posts_seo_columns,
    backfill_posts_seo_fields as _svc_backfill_posts_seo_fields,
    ensure_notifications_columns as _svc_ensure_notifications_columns,
    ensure_reports_columns as _svc_ensure_reports_columns,
    ensure_announcements_columns as _svc_ensure_announcements_columns,
)
from services.observability import log_event as _svc_log_event
from services.pending_resume import resume_pending_publication_row as _resume_pending_publication_row
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
        seed = int(datetime.now(timezone.utc).strftime('%Y') + '1000000')
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

# ============== Register Blueprints ==============
from routes import register_blueprints
register_blueprints(app)

# ============== Routes (legacy – kept until all routes verified in blueprints) ==============

@app.route('/health')
def health():
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok'}), 200
    except Exception:
        return jsonify({'status': 'db_error'}), 503


# ============== Startup ==============

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
    return _svc_init_default_data(
        _ensure_bootstrap_admin,
        lambda: User.query.filter(User.is_admin == True).with_entities(User.id).scalar(),
        _seed_default_article,
    )

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


def _ensure_posts_seo_columns():
    """启动时确保 posts.slug/excerpt/seo/updated_at 列存在。"""
    return _svc_ensure_posts_seo_columns(db.session, db.engine.dialect.name)


def _backfill_posts_seo_fields():
    """启动时为历史帖子补齐 slug / excerpt。"""
    return _svc_backfill_posts_seo_fields(db.session, Post)


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
    started, interval = _svc_run_startup_sequence(
        create_all=db.create_all,
        ensure_steps=[
            _ensure_users_wallet_address,
            _ensure_users_withdrawable_balance,
            _ensure_users_checkin_columns,
            _ensure_checkin_logs_table,
            _ensure_app_settings_table,
            _ensure_posts_tx_nullable,
            _ensure_posts_pin_columns,
            _ensure_posts_special_column,
            _ensure_posts_seo_columns,
            _ensure_notifications_columns,
            _ensure_reports_columns,
            _ensure_announcements_columns,
            _ensure_series_tables,
            _ensure_pending_publications_table,
            _ensure_flow_events_table,
            _backfill_posts_seo_fields,
        ],
        should_run_init_db=_should_run_init_db,
        init_db_data=init_db_data,
        check_receive_address=_check_receive_address,
        redis_url=os.environ.get('REDIS_URL'),
        flask_debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true',
        warn_if_redis_missing_fn=_svc_warn_if_redis_missing,
        start_compensation_worker_fn=_svc_start_compensation_worker,
        app=app,
        pending_model=PendingPublication,
        resume_pending_publication_row=_resume_pending_publication_row,
        logger=app.logger,
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
