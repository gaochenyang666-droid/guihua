import os
import bleach
from datetime import datetime, timedelta, timezone
from flask import Blueprint, request, jsonify, g
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from web3 import Web3

from extensions import db
from models import (
    User, Post, Comment, Like, Bookmark, Tip, CheckinLog,
    Series, AppSetting,
    get_random_avatar, ALLOWED_AVATARS,
    calc_level_info, checkin_exp_by_streak,
)
from utils.security import (
    _rate_limit, _get_optional_jwt_payload, token_required, _get_redis_client,
)
from services.observability import log_event as _svc_log_event
from services.user_progress import (
    china_today as _svc_china_today,
    get_user_level as _svc_get_user_level,
    build_group_links_for_user as _svc_build_group_links_for_user,
    build_legacy_achievements as _svc_build_legacy_achievements,
    build_achievements_for_user as _svc_build_achievements_for_user,
    build_checkin_status as _svc_build_checkin_status,
)
from services.posts_logic import build_post_precheck as _svc_build_post_precheck
from services.site_settings import get_setting_value as _svc_get_setting_value
from services.runtime_state import (
    prune_pending_wallet_nonces as _svc_prune_pending_wallet_nonces,
    pending_wallet_nonce_redis_key as _svc_pending_wallet_nonce_redis_key,
    set_pending_wallet_nonce as _svc_set_pending_wallet_nonce,
    get_pending_wallet_nonce as _svc_get_pending_wallet_nonce,
    delete_pending_wallet_nonce as _svc_delete_pending_wallet_nonce,
)

bp = Blueprint('user', __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
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

WALLET_NONCE_TTL_MINUTES = 5

# ---------------------------------------------------------------------------
# Local thin wrappers
# ---------------------------------------------------------------------------

def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _china_today():
    return _svc_china_today()


def _get_setting_value(setting_key, default_value=''):
    return _svc_get_setting_value(AppSetting, setting_key, default_value)


def _get_user_level(user):
    return _svc_get_user_level(user, calc_level_info)


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


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/api/user/me', methods=['GET', 'PUT'])
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


@bp.route('/api/user/settings', methods=['GET', 'PUT'])
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


@bp.route('/api/checkin/status', methods=['GET'])
@token_required
def get_checkin_status():
    return jsonify(_build_checkin_status(g.current_user))


@bp.route('/api/checkin', methods=['POST'])
@token_required
def daily_checkin():
    if _rate_limit('checkin', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
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


@bp.route('/api/achievements', methods=['GET'])
@token_required
def get_my_achievements():
    return jsonify(_build_achievements_for_user(g.current_user))


@bp.route('/api/achievements/equip', methods=['POST'])
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


@bp.route('/api/group-links', methods=['GET'])
@token_required
def get_group_links():
    return jsonify(_build_group_links_for_user(g.current_user))


@bp.route('/api/user/password', methods=['PUT'])
@token_required
def change_password():
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    old_password = data.get('old_password')
    new_password = data.get('new_password')

    if not old_password or not new_password:
        return jsonify({'error': '缺少密码字段'}), 400
    if len(new_password) < 6:
        return jsonify({'error': '新密码至少 6 位'}), 400

    if not g.current_user.check_password(old_password):
        return jsonify({'error': '原密码错误'}), 401

    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': '密码已更新'})


@bp.route('/api/user/bind_wallet', methods=['POST'])
@token_required
def bind_wallet():
    if _rate_limit('bind_wallet', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
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

    existing_user = User.query.filter_by(address=address).first()
    if existing_user and existing_user.id != g.current_user.id:
        _log_flow_event('wallet_bind_failed', address=address, reason='already_bound')
        return jsonify({'error': '该钱包已绑定到其他账号'}), 400

    if not g.current_user.nonce_created_at or datetime.now(timezone.utc) - g.current_user.nonce_created_at > timedelta(minutes=WALLET_NONCE_TTL_MINUTES):
        _log_flow_event('wallet_bind_failed', address=address, reason='nonce_expired')
        return jsonify({'error': '绑定挑战已过期，请重新获取'}), 401
    msg_stripped = (message or '').strip()
    expected_legacy = f"Bind wallet {address} to user {g.current_user.username}. Nonce: {g.current_user.nonce}"
    expected_new = f"Bind wallet {address} to account {g.current_user.id} on {request.host}: {g.current_user.nonce}"
    if msg_stripped not in (expected_legacy, expected_new):
        _log_flow_event('wallet_bind_failed', address=address, reason='message_mismatch')
        return jsonify({'error': '绑定签名消息格式不匹配'}), 400

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


@bp.route('/api/user/bind_wallet/nonce', methods=['GET'])
@token_required
def get_bind_wallet_nonce():
    """为当前登录用户生成一次性绑定 nonce。"""
    g.current_user.refresh_nonce()
    db.session.commit()
    return jsonify({'nonce': g.current_user.nonce})


@bp.route('/api/posts/precheck', methods=['POST'])
@token_required
def precheck_post():
    data = request.get_json(silent=True) or {}
    return jsonify(_build_post_precheck(g.current_user, data))


@bp.route('/api/onboarding/tasks', methods=['GET'])
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


@bp.route('/api/users/<username>', methods=['GET'])
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
            comments_count=comment_counts.get(p.id, 0),
            is_liked=p.id in user_likes,
            is_bookmarked=p.id in user_bookmarks,
        )
        posts_data.append(p_dict)

    series_rows = Series.query.filter_by(author_id=user.id).order_by(Series.updated_at.desc()).limit(50).all()
    return jsonify({
        'user': user_data,
        'posts': posts_data,
        'series': [s.to_dict() for s in series_rows]
    })
