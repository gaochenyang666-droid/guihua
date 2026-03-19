import re
import json
import traceback
import bleach
from datetime import datetime, timezone
from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy import func, or_
from sqlalchemy.orm import joinedload, subqueryload

from extensions import db
from models import (
    Post, Vote, UserVote, Comment, CommentLike, Like, Bookmark,
    Notification, UsedTransaction, PendingPublication, User,
    Series, SeriesPost, Report, Tip, AdminAuditLog,
    build_comment_tree,
)
from utils.security import (
    _rate_limit, token_required, _get_optional_jwt_payload, _bearer_token,
    bleach_clean_post_content as _bleach_clean_post_content,
    _get_redis_client,
)
from services.posts_query import (
    build_posts_payload as _build_posts_payload,
    apply_default_post_order as _apply_default_post_order,
)
from services.posts_logic import (
    build_post_precheck as _build_post_precheck,
    normalize_tags as _normalize_tags,
    extract_mention_tokens as _extract_mention_tokens,
    resolve_mentioned_users as _svc_resolve_mentioned_users,
    series_can_view as _svc_series_can_view,
    series_can_edit as _svc_series_can_edit,
)
from services.blockchain import (
    get_post_fee_usdt_raw,
    verify_transaction,
    inspect_transaction_status as _svc_inspect_transaction_status,
)
from services.storage import (
    upload_to_imgbb,
    upload_to_arweave_native,
    upload_to_arweave_with_retry,
)
from services.publish_recovery import (
    upsert_pending_publication as _svc_upsert_pending_publication,
    clear_pending_publication as _svc_clear_pending_publication,
    get_latest_pending_publication as _svc_get_latest_pending_publication,
)
from services.app_support import (
    parse_iso_datetime as _parse_iso_datetime,
    humanize_verify_error as _humanize_verify_error,
    is_post_permanent as _is_post_permanent,
    tip_amount_to_usdt_str as _svc_tip_amount_to_usdt_str,
)
from services.observability import log_event as _svc_log_event
from services.pending_resume import resume_pending_publication_row as _resume_pending_publication_row
from services.runtime_state import allow_view_count_increment as _svc_allow_view_count_increment

posts_bp = Blueprint('posts', __name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TX_CONFIRMATIONS_NEEDED = 2

# ---------------------------------------------------------------------------
# Module-level view-count anti-spam state
# ---------------------------------------------------------------------------

_view_count_key: dict = {}
_view_count_ttl = 60
_view_count_fallback_warned = False

# ---------------------------------------------------------------------------
# Local helpers (same pattern as app.py thin wrappers)
# ---------------------------------------------------------------------------


def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _resolve_mentioned_users(tokens, exclude_user_id=None):
    return _svc_resolve_mentioned_users(
        tokens,
        username_lookup=lambda t: User.query.filter(func.lower(User.username) == t.lower()).first(),
        nickname_lookup=lambda t: User.query.filter(func.lower(User.nickname) == t.lower()).first(),
        exclude_user_id=exclude_user_id,
    )


def _series_can_view(series_obj, viewer=None):
    return _svc_series_can_view(series_obj, viewer)


def _series_can_edit(series_obj, viewer):
    return _svc_series_can_edit(series_obj, viewer)


def _allow_view_count_increment(post_id, ip):
    global _view_count_fallback_warned
    redis_conn = _get_redis_client()
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


def _log_admin_action(action, target_type=None, target_id=None, details=None):
    try:
        if not getattr(g, 'current_user', None) or not getattr(g.current_user, 'is_admin', False):
            return
        row = AdminAuditLog(
            admin_id=g.current_user.id,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            details=(details or '')[:1000] if details else None,
        )
        db.session.add(row)
        db.session.commit()
    except Exception:
        db.session.rollback()


# ===================================================================
# Routes
# ===================================================================


@posts_bp.route('/api/posts/pinned', methods=['GET'])
def get_pinned_post():
    """返回当前全站置顶帖（若无则返回 null）。"""
    post = Post.query.filter_by(is_hidden=False, is_pinned=True).order_by(
        Post.pinned_at.desc(), Post.created_at.desc()
    ).first()
    return jsonify({'post': post.to_dict() if post else None})


@posts_bp.route('/api/posts', methods=['GET'])
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


@posts_bp.route('/api/search', methods=['GET'])
def search_posts():
    if _rate_limit('search', 60):
        return jsonify({'error': '搜索过于频繁，请稍后再试'}), 429
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
            tag_filters.append(Post.tags.ilike(f'%"{escaped}"%', escape='\\'))
        if tag_filters:
            query = query.filter(or_(*tag_filters))

    query = query.order_by(
        Post.is_special_announcement.desc(),
        Post.is_pinned.desc(),
        Post.pinned_at.desc(),
        Post.created_at.desc()
    )
    from sqlalchemy.orm import joinedload as _jl
    query = query.options(_jl(Post.author))
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    posts = pagination.items
    s_post_ids = [p.id for p in posts]
    s_like_counts = {}
    s_comment_counts = {}
    if s_post_ids:
        s_like_counts = {r[0]: int(r[1] or 0) for r in db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(s_post_ids)).group_by(Like.post_id).all()}
        s_comment_counts = {r[0]: int(r[1] or 0) for r in db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(s_post_ids)).group_by(Comment.post_id).all()}
    return jsonify({
        'posts': [p.to_dict(likes_count=s_like_counts.get(p.id, 0), comments_count=s_comment_counts.get(p.id, 0), is_liked=False, is_bookmarked=False) for p in posts],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@posts_bp.route('/api/posts/check_tx', methods=['GET'])
def check_tx_status():
    if _rate_limit('check_tx', 30):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    tx_hash = request.args.get('tx_hash')
    if not tx_hash:
        return jsonify({'error': '缺少交易哈希'}), 400
        
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


@posts_bp.route('/api/posts/pending/latest', methods=['GET'])
@token_required
def get_latest_pending_post():
    row = _svc_get_latest_pending_publication(PendingPublication, g.current_user.id)
    if not row:
        return jsonify({'pending': None})
    return jsonify({'pending': row.to_dict()})


@posts_bp.route('/api/posts/pending/clear', methods=['POST'])
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


@posts_bp.route('/api/posts/pending/retry', methods=['POST'])
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


@posts_bp.route('/api/posts', methods=['POST'])
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
        tx_hash = None
        ipfs_cid = None
    else:
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
        
        clean_content = _bleach_clean_post_content(data.get('content', ''))
        payload = {
            'title': data.get('title'),
            'content': clean_content,
            'tags': normalized_tags,
            'author': g.current_user.address,
            'timestamp': datetime.now(timezone.utc).isoformat(),
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

    if tx_hash:
        existing_post = Post.query.filter_by(tx_hash=tx_hash).first()
        if existing_post:
            _log_flow_event('post_duplicate_tx', tx_hash=tx_hash, existing_post_id=existing_post.id)
            return jsonify({'error': '该交易已用于其他帖子'}), 400

    # 4. Create Post
    clean_content = _bleach_clean_post_content(data.get('content', ''))
    clean_title = bleach.clean(data.get('title', ''), strip=True)
    if not clean_title or not clean_title.strip():
        _log_flow_event('post_publish_blocked', reason='empty_title')
        return jsonify({'error': '标题不能为空'}), 400
    if not clean_content or not clean_content.strip():
        _log_flow_event('post_publish_blocked', reason='empty_content')
        return jsonify({'error': '正文不能为空'}), 400

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
        db.session.flush()
        
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
        if 'null' in err_str or 'not null' in err_str:
            print(f"Create Post DB Error (nullable?): {e}")
            traceback.print_exc()
            return jsonify({
                'error': '发帖失败：数据库字段不允许为空。请确认 posts 表的 tx_hash、ipfs_cid 列已设为允许 NULL（管理员发帖无需上链）。'
            }), 500
        print(f"Create Post DB Error: {e}")
        traceback.print_exc()
        current_app.logger.exception('Create post failed: user_id=%s tx_hash=%s', getattr(g.current_user, 'id', None), tx_hash)
        return jsonify({'error': '服务器暂时不可用，请稍后重试'}), 500
    
    return jsonify({'message': '帖子已发布', 'post': post.to_dict()}), 201


@posts_bp.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    try:
        post = Post.query.options(
            joinedload(Post.author),
            subqueryload(Post.votes),
        ).get_or_404(post_id)
        payload = _get_optional_jwt_payload()
        current_user_id = payload.get('user_id') if payload else None
        viewer = User.query.get(current_user_id) if current_user_id else None
        if post.is_hidden and not (viewer and (viewer.is_admin or viewer.id == post.author_id)):
            return jsonify({'error': '帖子不存在'}), 404
        try:
            ip = (request.remote_addr or 'unknown').strip()
            if _allow_view_count_increment(post_id, ip):
                post.view_count = getattr(post, 'view_count', 0) or 0
                post.view_count += 1
                db.session.commit()
        except Exception:
            db.session.rollback()

        likes_count = Like.query.filter_by(post_id=post_id).count()
        all_comments = Comment.query.filter_by(post_id=post_id).options(
            joinedload(Comment.author)
        ).order_by(Comment.created_at.asc()).all()
        post_data = post.to_dict(current_user_id, likes_count=likes_count, comments_count=len(all_comments))

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
        link_rows = SeriesPost.query.filter_by(post_id=post_id).options(
            joinedload(SeriesPost.series)
        ).order_by(SeriesPost.order_index.asc()).all()
        if link_rows:
            series_ids = [lk.series_id for lk in link_rows]
            all_series_posts = SeriesPost.query.filter(
                SeriesPost.series_id.in_(series_ids)
            ).order_by(SeriesPost.series_id, SeriesPost.order_index).all()
            sp_by_series: dict[int, list] = {}
            for sp in all_series_posts:
                sp_by_series.setdefault(sp.series_id, []).append(sp)
            for link in link_rows:
                s = link.series
                if not s or not _series_can_view(s, viewer):
                    continue
                siblings = sp_by_series.get(s.id, [])
                prev_post_id = None
                next_post_id = None
                for i, sp in enumerate(siblings):
                    if sp.post_id == post_id:
                        if i > 0:
                            prev_post_id = siblings[i - 1].post_id
                        if i < len(siblings) - 1:
                            next_post_id = siblings[i + 1].post_id
                        break
                series_items.append({
                    'series_id': s.id,
                    'title': s.title,
                    'order_index': link.order_index,
                    'prev_post_id': prev_post_id,
                    'next_post_id': next_post_id,
                })
        post_data['series'] = series_items

        return jsonify(post_data)
    except Exception as e:
        print(f"Post Detail Error: {e}")
        return jsonify({'error': '加载帖子失败，请稍后重试'}), 500


@posts_bp.route('/api/posts/<int:post_id>/sync-arweave', methods=['POST'])
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
        'timestamp': post.created_at.isoformat() if post.created_at else datetime.now(timezone.utc).isoformat(),
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


@posts_bp.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    if _rate_limit('repost', 20):
        return jsonify({'error': '操作过于频繁'}), 429
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


@posts_bp.route('/api/posts/<int:post_id>/vote', methods=['POST'])
@token_required
def vote_post(post_id):
    if _rate_limit('vote', 30):
        return jsonify({'error': '操作过于频繁'}), 429
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
    
    existing_vote = db.session.query(UserVote.id).join(
        Vote, UserVote.vote_id == Vote.id
    ).filter(
        UserVote.user_id == g.current_user.id,
        Vote.post_id == post_id
    ).first()
    if existing_vote:
        return jsonify({'error': '你已经参与过这篇帖子的投票'}), 400
    
    try:
        user_vote = UserVote(user_id=g.current_user.id, vote_id=option_id)
        db.session.add(user_vote)
        vote_option.vote_count += 1
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': '你已经投过票了'}), 400
    
    return jsonify({
        'message': '投票成功',
        'votes': [v.to_dict() for v in post.votes]
    })


@posts_bp.route('/api/posts/<int:post_id>/comments', methods=['POST'])
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
    
    try:
        notified_user_ids = set()
        if parent_id is not None:
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


@posts_bp.route('/api/comments/<int:comment_id>/like', methods=['POST'])
@token_required
def toggle_comment_like(comment_id):
    if _rate_limit('comment_like', 60):
        return jsonify({'error': '操作过于频繁'}), 429
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


@posts_bp.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(post_id):
    if _rate_limit('like', 60):
        return jsonify({'error': '操作过于频繁'}), 429
    post = Post.query.get_or_404(post_id)
    try:
        like = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
        if like:
            db.session.delete(like)
            msg = '已取消恐惧'
        else:
            db.session.add(Like(user_id=g.current_user.id, post_id=post.id))
            msg = '已恐惧'
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
        current_app.logger.exception('Like post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'message': '操作失败，请稍后重试'}), 400


@posts_bp.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def bookmark_post(post_id):
    if _rate_limit('bookmark', 60):
        return jsonify({'error': '操作过于频繁'}), 429
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
        current_app.logger.exception('Bookmark post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'message': '操作失败，请稍后重试'}), 400


@posts_bp.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    if not g.current_user.is_admin and post.author_id != g.current_user.id:
        return jsonify({'error': '没有权限删除该帖子'}), 403
    
    try:
        vote_ids = [row[0] for row in db.session.query(Vote.id).filter(Vote.post_id == post.id).all()]
        if vote_ids:
            UserVote.query.filter(UserVote.vote_id.in_(vote_ids)).delete(synchronize_session=False)

        Notification.query.filter(Notification.post_id == post.id).update({'post_id': None}, synchronize_session=False)
        Report.query.filter(Report.post_id == post.id).update({'post_id': None}, synchronize_session=False)
        Tip.query.filter(Tip.post_id == post.id).update({'post_id': None}, synchronize_session=False)

        db.session.delete(post)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        current_app.logger.exception('Delete post failed: post_id=%s user_id=%s', post_id, getattr(g.current_user, 'id', None))
        return jsonify({'error': '删除失败，请稍后重试'}), 500
    if g.current_user.is_admin:
        _log_admin_action('post_delete', 'post', post_id)
    return jsonify({'message': '帖子已删除'})


@posts_bp.route('/api/posts/<int:post_id>', methods=['PUT'])
@token_required
def update_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    if post.author_id != g.current_user.id:
        return jsonify({'error': '没有权限编辑该帖子'}), 403
        
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
