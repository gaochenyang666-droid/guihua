from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g, current_app
from sqlalchemy import or_

from extensions import db
from models import (
    User, Post, PendingPublication, FlowEvent, AdminAuditLog,
    Announcement, Report, Notification, AppSetting,
)
from utils.security import token_required, admin_required
from services.site_settings import (
    get_group_link_urls as _svc_get_group_link_urls,
    validate_group_link_urls as _svc_validate_group_link_urls,
    set_setting_value as _svc_set_setting_value,
)
from services.blockchain import get_post_fee_usdt_raw
from services.observability import log_event as _svc_log_event
from services.ops_monitor import build_ops_summary as _svc_build_ops_summary
from services.publish_compensation import (
    run_compensation_batch as _svc_run_compensation_batch,
    compensation_interval_seconds as _svc_compensation_interval_seconds,
    should_start_compensation_worker as _svc_should_start_compensation_worker,
)
from services.app_support import parse_iso_datetime as _svc_parse_iso_datetime
from services.pending_resume import resume_pending_publication_row as _resume_pending_publication_row

admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')

TELEGRAM_GROUP_SETTING_KEYS = {
    'co_create': 'telegram_group_co_create_url',
    'core': 'telegram_group_core_url',
}


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


def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _set_setting_value(setting_key, setting_value):
    return _svc_set_setting_value(db.session, AppSetting, setting_key, setting_value)


def _parse_iso_datetime(value):
    return _svc_parse_iso_datetime(value)


# ---- Group links ----

@admin_bp.route('/group-links', methods=['GET'])
@token_required
@admin_required
def get_admin_group_links():
    return jsonify(_svc_get_group_link_urls(AppSetting, TELEGRAM_GROUP_SETTING_KEYS))


@admin_bp.route('/group-links', methods=['PUT'])
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


# ---- Pending publications ----

@admin_bp.route('/pending-publications', methods=['GET'])
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
            PendingPublication.last_error.ilike(f'%{escaped}%'),
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


@admin_bp.route('/pending-publications/<int:pending_id>/retry', methods=['POST'])
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


@admin_bp.route('/pending-publications/<int:pending_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_pending_publication_admin(pending_id):
    row = PendingPublication.query.get_or_404(pending_id)
    tx_hash = row.tx_hash
    db.session.delete(row)
    db.session.commit()
    _log_flow_event('pending_publication_admin_deleted', pending_id=pending_id, tx_hash=tx_hash, admin_id=g.current_user.id)
    return jsonify({'message': '待恢复记录已删除'})


@admin_bp.route('/pending-publications/retry-batch', methods=['POST'])
@token_required
@admin_required
def retry_pending_publication_batch_admin():
    result = _svc_run_compensation_batch(
        current_app._get_current_object(),
        PendingPublication,
        _resume_pending_publication_row,
        current_app.logger,
        limit=10,
        min_age_seconds=0,
    )
    _log_flow_event('pending_publication_batch_retry', admin_id=g.current_user.id, **result)
    return jsonify({
        'message': '已执行一轮待发布补偿任务',
        'result': result,
    })


# ---- Ops / Flow events ----

@admin_bp.route('/ops/summary', methods=['GET'])
@token_required
@admin_required
def admin_ops_summary():
    summary = _svc_build_ops_summary(FlowEvent, PendingPublication, AdminAuditLog)
    summary['worker'] = {
        'enabled': _svc_should_start_compensation_worker() and _svc_compensation_interval_seconds() > 0,
        'interval_seconds': _svc_compensation_interval_seconds(),
    }
    return jsonify(summary)


@admin_bp.route('/flow-events', methods=['GET'])
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


# ---- Stats (uses @token_required only, manual admin check) ----

@admin_bp.route('/stats', methods=['GET'])
@token_required
def admin_stats():
    if not g.current_user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403

    total_users = User.query.count()
    web3_users = User.query.filter(User.address != None).count()
    web2_users = total_users - web3_users

    total_posts = Post.query.count()
    web3_posts = Post.query.filter(Post.post_type == 1).count()
    web2_posts = total_posts - web3_posts

    fee_usdt_raw = get_post_fee_usdt_raw()
    decimals = current_app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_usdt_raw / (10 ** decimals), 4)
    total_revenue_raw = web3_posts * fee_usdt_raw
    total_revenue_usdt = total_revenue_raw / (10 ** decimals)

    return jsonify({
        'users': {
            'total': total_users,
            'web3': web3_users,
            'web2': web2_users,
            'retention_rate': 'N/A',
        },
        'posts': {
            'total': total_posts,
            'web3': web3_posts,
            'web2': web2_posts,
        },
        'revenue': {
            'total_usdt': round(total_revenue_usdt, 2),
            'fee_per_post_usdt': fee_usdt,
        },
    })


# ---- Posts moderation ----

@admin_bp.route('/posts/<int:post_id>/hide', methods=['POST'])
@token_required
@admin_required
def toggle_hide_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_hidden = not post.is_hidden
    db.session.commit()
    _log_admin_action('post_toggle_hide', 'post', post_id, f"is_hidden={post.is_hidden}")
    return jsonify({'message': '帖子可见状态已更新', 'is_hidden': post.is_hidden})


@admin_bp.route('/posts/<int:post_id>/pin', methods=['POST'])
@token_required
@admin_required
def toggle_pin_post(post_id):
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
            'pinned_by': None,
        }, synchronize_session=False)

    post.is_pinned = should_pin
    post.pinned_at = datetime.now(timezone.utc) if should_pin else None
    post.pinned_by = g.current_user.id if should_pin else None
    db.session.commit()
    _log_admin_action('post_pin_toggle', 'post', post_id, f"is_pinned={post.is_pinned}")
    return jsonify({
        'message': '已置顶' if should_pin else '已取消置顶',
        'is_pinned': post.is_pinned,
        'pinned_at': post.pinned_at.isoformat() if post.pinned_at else None,
    })


@admin_bp.route('/posts/<int:post_id>/toggle-comments', methods=['POST'])
@token_required
@admin_required
def toggle_post_comments(post_id):
    post = Post.query.get_or_404(post_id)
    post.allow_comments = not post.allow_comments
    db.session.commit()
    _log_admin_action('post_toggle_comments', 'post', post_id, f"allow_comments={post.allow_comments}")
    return jsonify({'message': '评论权限已更新', 'allow_comments': post.allow_comments})


# ---- Users ----

@admin_bp.route('/users/<int:user_id>/ban', methods=['POST'])
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


@admin_bp.route('/users', methods=['GET'])
@token_required
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])


# ---- Announcements ----

@admin_bp.route('/announcements', methods=['GET'])
@token_required
@admin_required
def list_announcements():
    rows = Announcement.query.order_by(Announcement.created_at.desc()).limit(100).all()
    return jsonify({'announcements': [a.to_dict() for a in rows]})


@admin_bp.route('/announcements', methods=['POST'])
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
        created_by=g.current_user.id,
    )
    db.session.add(ann)
    db.session.commit()
    _log_admin_action('announcement_create', 'announcement', ann.id, f"title={title}")
    return jsonify({'message': '公告已创建', 'announcement': ann.to_dict()}), 201


@admin_bp.route('/announcements/<int:announcement_id>', methods=['PUT'])
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
                Announcement.entry_type == ann.entry_type,
            ).update({'is_active': False}, synchronize_session=False)
        ann.is_active = make_active
    db.session.commit()
    _log_admin_action('announcement_update', 'announcement', ann.id)
    return jsonify({'message': '公告已更新', 'announcement': ann.to_dict()})


@admin_bp.route('/announcements/<int:announcement_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_announcement(announcement_id):
    ann = Announcement.query.get_or_404(announcement_id)
    db.session.delete(ann)
    db.session.commit()
    _log_admin_action('announcement_delete', 'announcement', announcement_id)
    return jsonify({'message': '公告已删除'})


# ---- Audit logs ----

@admin_bp.route('/audit-logs', methods=['GET'])
@token_required
@admin_required
def list_admin_audit_logs():
    limit = min(request.args.get('limit', 100, type=int), 300)
    rows = AdminAuditLog.query.order_by(AdminAuditLog.created_at.desc()).limit(limit).all()
    return jsonify({'logs': [r.to_dict() for r in rows]})


# ---- Reports ----

@admin_bp.route('/reports', methods=['GET'])
@token_required
@admin_required
def list_reports():
    status = request.args.get('status')
    q = Report.query.order_by(Report.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    reports = q.limit(200).all()
    return jsonify([r.to_dict() for r in reports])


@admin_bp.route('/reports/<int:report_id>', methods=['PUT'])
@token_required
@admin_required
def update_report(report_id):
    r = Report.query.get_or_404(report_id)
    data = request.get_json(silent=True) or {}
    old_status = (r.status or '').strip()
    if data.get('status') in ('resolved', 'dismissed'):
        r.status = data['status']
    if ('admin_notes' in data) or ('admin_note' in data):
        notes = (data.get('admin_notes', data.get('admin_note')) or '')[:500]
        r.admin_notes = notes
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
            link=f"/?post={r.post_id}" if r.post_id else None,
        )
        db.session.add(notif)
        r.result_notified_at = datetime.now(timezone.utc)
    db.session.commit()
    _log_admin_action('report_update', 'report', report_id, f"status={r.status}")
    _log_flow_event('report_updated', report_id=report_id, old_status=old_status, new_status=r.status, notified=bool(should_notify_result))
    return jsonify({'message': '已更新', 'report': r.to_dict()})
