import bleach
from flask import Blueprint, request, jsonify, g
from sqlalchemy import func

from extensions import db
from models import (
    User, Post, Comment, Like, Bookmark,
    Series, SeriesPost,
)
from utils.security import token_required, _get_optional_jwt_payload
from services.observability import log_event as _svc_log_event
from services.posts_logic import (
    series_can_view as _series_can_view,
    series_can_edit as _series_can_edit,
)

bp = Blueprint('series', __name__, url_prefix='/api/series')


# ---------------------------------------------------------------------------
# Local helpers
# ---------------------------------------------------------------------------

def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _reindex_series_posts(series_id):
    rows = SeriesPost.query.filter_by(series_id=series_id).order_by(SeriesPost.order_index.asc(), SeriesPost.id.asc()).all()
    changed = False
    for idx, row in enumerate(rows, start=1):
        if row.order_index != idx:
            row.order_index = idx
            changed = True
    if changed:
        db.session.flush()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@bp.route('/', methods=['GET'])
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


@bp.route('/', methods=['POST'])
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


@bp.route('/<int:series_id>', methods=['GET'])
def get_series_detail(series_id):
    row = Series.query.get_or_404(series_id)
    payload = _get_optional_jwt_payload()
    viewer = User.query.get(payload.get('user_id')) if payload and payload.get('user_id') else None
    if not _series_can_view(row, viewer):
        return jsonify({'error': '该系列不可见'}), 403
    from sqlalchemy.orm import joinedload as _jl
    links = SeriesPost.query.filter_by(series_id=series_id).options(
        _jl(SeriesPost.post).joinedload(Post.author),
    ).order_by(SeriesPost.order_index.asc(), SeriesPost.id.asc()).all()
    visible_posts = []
    for link in links:
        p = link.post
        if not p:
            continue
        if p.is_hidden and not (viewer and (viewer.is_admin or viewer.id == p.author_id)):
            continue
        visible_posts.append((link, p))
    s_post_ids = [p.id for _, p in visible_posts]
    s_viewer_id = payload.get('user_id') if payload else None
    s_like_counts = {}
    s_comment_counts = {}
    s_user_likes = set()
    s_user_bookmarks = set()
    if s_post_ids:
        s_like_counts = {r[0]: int(r[1] or 0) for r in db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(s_post_ids)).group_by(Like.post_id).all()}
        s_comment_counts = {r[0]: int(r[1] or 0) for r in db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(s_post_ids)).group_by(Comment.post_id).all()}
        if s_viewer_id:
            s_user_likes = {l.post_id for l in Like.query.filter(Like.user_id == s_viewer_id, Like.post_id.in_(s_post_ids)).all()}
            s_user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == s_viewer_id, Bookmark.post_id.in_(s_post_ids)).all()}
    items = []
    for link, p in visible_posts:
        items.append({
            'order_index': link.order_index,
            'post': p.to_dict(
                s_viewer_id,
                likes_count=s_like_counts.get(p.id, 0),
                comments_count=s_comment_counts.get(p.id, 0),
                is_liked=p.id in s_user_likes,
                is_bookmarked=p.id in s_user_bookmarks,
            )
        })
    return jsonify({'series': row.to_dict(), 'items': items})


@bp.route('/<int:series_id>', methods=['PATCH'])
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


@bp.route('/<int:series_id>', methods=['DELETE'])
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


@bp.route('/<int:series_id>/posts', methods=['POST'])
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


@bp.route('/<int:series_id>/posts/<int:post_id>', methods=['DELETE'])
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


@bp.route('/<int:series_id>/order', methods=['PATCH'])
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
