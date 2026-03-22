from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g, current_app
from extensions import db
from models import (
    User, Post, PendingPublication, FlowEvent, AdminAuditLog,
    Announcement, Report, Notification, AppSetting,
)
from utils.security import token_required, admin_required
from utils.security import get_redis_status as _get_redis_status
from services.site_settings import (
    get_group_link_urls as _svc_get_group_link_urls,
    validate_group_link_urls as _svc_validate_group_link_urls,
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
from services.seo import story_path as _story_path
from services.admin_stats import build_admin_stats as _svc_build_admin_stats
from services.admin_actions import (
    AdminActionResult,
    update_group_links as _svc_update_group_links,
    toggle_post_hidden as _svc_toggle_post_hidden,
    toggle_post_pin as _svc_toggle_post_pin,
    toggle_post_comments as _svc_toggle_post_comments,
    toggle_user_ban as _svc_toggle_user_ban,
    create_announcement as _svc_create_announcement,
    update_announcement as _svc_update_announcement,
    delete_announcement as _svc_delete_announcement,
    retry_pending_publication as _svc_retry_pending_publication,
    delete_pending_publication as _svc_delete_pending_publication,
    retry_pending_publication_batch as _svc_retry_pending_publication_batch,
    update_report as _svc_update_report,
)
from services.admin_queries import (
    list_pending_publications as _svc_list_pending_publications,
    list_flow_events as _svc_list_flow_events,
    list_users as _svc_list_users,
    list_announcements as _svc_list_announcements,
    list_admin_audit_logs as _svc_list_admin_audit_logs,
    list_reports as _svc_list_reports,
    build_admin_ops_payload as _svc_build_admin_ops_payload,
)

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


def _parse_iso_datetime(value):
    return _svc_parse_iso_datetime(value)


def _respond_admin_action(result: AdminActionResult):
    if result.audit_action:
        _log_admin_action(
            result.audit_action,
            result.audit_target_type,
            result.audit_target_id,
            result.audit_details,
        )
    if result.flow_event:
        _log_flow_event(result.flow_event, **(result.flow_fields or {}))
    return jsonify(result.payload), result.status_code


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
    return _respond_admin_action(
        _svc_update_group_links(
            db.session,
            AppSetting,
            TELEGRAM_GROUP_SETTING_KEYS,
            _svc_set_setting_value,
            co_url,
            core_url,
        )
    )


# ---- Pending publications ----

@admin_bp.route('/pending-publications', methods=['GET'])
@token_required
@admin_required
def list_pending_publications():
    return jsonify(_svc_list_pending_publications(
        PendingPublication,
        Post,
        status=request.args.get('status'),
        q=request.args.get('q'),
        limit=request.args.get('limit', 200),
        story_path_fn=_story_path,
    ))


@admin_bp.route('/pending-publications/<int:pending_id>/retry', methods=['POST'])
@token_required
@admin_required
def retry_pending_publication_admin(pending_id):
    row = PendingPublication.query.get_or_404(pending_id)
    return _respond_admin_action(
        _svc_retry_pending_publication(row, g.current_user, _resume_pending_publication_row)
    )


@admin_bp.route('/pending-publications/<int:pending_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_pending_publication_admin(pending_id):
    row = PendingPublication.query.get_or_404(pending_id)
    return _respond_admin_action(
        _svc_delete_pending_publication(db.session, row, g.current_user.id)
    )


@admin_bp.route('/pending-publications/retry-batch', methods=['POST'])
@token_required
@admin_required
def retry_pending_publication_batch_admin():
    return _respond_admin_action(
        _svc_retry_pending_publication_batch(
            run_compensation_batch=_svc_run_compensation_batch,
            app=current_app._get_current_object(),
            pending_model=PendingPublication,
            resume_pending_publication=_resume_pending_publication_row,
            logger=current_app.logger,
            admin_user_id=g.current_user.id,
            limit=10,
            min_age_seconds=0,
        )
    )


# ---- Ops / Flow events ----

@admin_bp.route('/ops/summary', methods=['GET'])
@token_required
@admin_required
def admin_ops_summary():
    return jsonify(_svc_build_admin_ops_payload(
        FlowEvent,
        PendingPublication,
        AdminAuditLog,
        build_ops_summary=_svc_build_ops_summary,
        worker_enabled=_svc_should_start_compensation_worker() and _svc_compensation_interval_seconds() > 0,
        worker_interval_seconds=_svc_compensation_interval_seconds(),
        redis_status=_get_redis_status(),
    ))


@admin_bp.route('/flow-events', methods=['GET'])
@token_required
@admin_required
def admin_flow_events():
    return jsonify(_svc_list_flow_events(
        FlowEvent,
        severity=request.args.get('severity'),
        event_keyword=request.args.get('event'),
        limit=request.args.get('limit', 100),
    ))


# ---- Stats (uses @token_required only, manual admin check) ----

@admin_bp.route('/stats', methods=['GET'])
@token_required
def admin_stats():
    if not g.current_user.is_admin:
        return jsonify({'error': '仅管理员可操作'}), 403
    fee_usdt_raw = get_post_fee_usdt_raw()
    decimals = current_app.config['BSC']['USDT_DECIMALS']
    return jsonify(_svc_build_admin_stats(
        User,
        Post,
        fee_usdt_raw,
        decimals,
        redis_status=_get_redis_status(),
    ))


# ---- Posts moderation ----

@admin_bp.route('/posts/<int:post_id>/hide', methods=['POST'])
@token_required
@admin_required
def toggle_hide_post(post_id):
    post = Post.query.get_or_404(post_id)
    return _respond_admin_action(_svc_toggle_post_hidden(db.session, post))


@admin_bp.route('/posts/<int:post_id>/pin', methods=['POST'])
@token_required
@admin_required
def toggle_pin_post(post_id):
    post = Post.query.get_or_404(post_id)
    payload = request.get_json(silent=True) or {}
    should_pin = payload.get('pinned')
    exclusive = payload.get('exclusive', True)
    return _respond_admin_action(
        _svc_toggle_post_pin(
            db.session,
            Post,
            post,
            g.current_user.id,
            should_pin=should_pin,
            exclusive=exclusive,
        )
    )


@admin_bp.route('/posts/<int:post_id>/toggle-comments', methods=['POST'])
@token_required
@admin_required
def toggle_post_comments(post_id):
    post = Post.query.get_or_404(post_id)
    return _respond_admin_action(_svc_toggle_post_comments(db.session, post))


# ---- Users ----

@admin_bp.route('/users/<int:user_id>/ban', methods=['POST'])
@token_required
@admin_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    return _respond_admin_action(_svc_toggle_user_ban(db.session, user))


@admin_bp.route('/users', methods=['GET'])
@token_required
@admin_required
def list_users():
    return jsonify(_svc_list_users(User))


# ---- Announcements ----

@admin_bp.route('/announcements', methods=['GET'])
@token_required
@admin_required
def list_announcements():
    return jsonify(_svc_list_announcements(Announcement, limit=request.args.get('limit', 100)))


@admin_bp.route('/announcements', methods=['POST'])
@token_required
@admin_required
def create_announcement():
    data = request.get_json(silent=True) or {}
    return _respond_admin_action(
        _svc_create_announcement(db.session, Announcement, g.current_user.id, data, _parse_iso_datetime)
    )


@admin_bp.route('/announcements/<int:announcement_id>', methods=['PUT'])
@token_required
@admin_required
def update_announcement(announcement_id):
    ann = Announcement.query.get_or_404(announcement_id)
    data = request.get_json(silent=True) or {}
    return _respond_admin_action(
        _svc_update_announcement(db.session, Announcement, ann, data, _parse_iso_datetime)
    )


@admin_bp.route('/announcements/<int:announcement_id>', methods=['DELETE'])
@token_required
@admin_required
def delete_announcement(announcement_id):
    ann = Announcement.query.get_or_404(announcement_id)
    return _respond_admin_action(_svc_delete_announcement(db.session, ann))


# ---- Audit logs ----

@admin_bp.route('/audit-logs', methods=['GET'])
@token_required
@admin_required
def list_admin_audit_logs():
    return jsonify(_svc_list_admin_audit_logs(AdminAuditLog, limit=request.args.get('limit', 100)))


# ---- Reports ----

@admin_bp.route('/reports', methods=['GET'])
@token_required
@admin_required
def list_reports():
    return jsonify(_svc_list_reports(Report, status=request.args.get('status'), limit=request.args.get('limit', 200)))


@admin_bp.route('/reports/<int:report_id>', methods=['PUT'])
@token_required
@admin_required
def update_report(report_id):
    r = Report.query.get_or_404(report_id)
    data = request.get_json(silent=True) or {}
    return _respond_admin_action(
        _svc_update_report(db.session, Notification, r, data, g.current_user.id)
    )
