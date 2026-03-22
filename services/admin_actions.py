from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass
class AdminActionResult:
    payload: dict
    status_code: int = 200
    audit_action: str | None = None
    audit_target_type: str | None = None
    audit_target_id: str | int | None = None
    audit_details: str | None = None
    flow_event: str | None = None
    flow_fields: dict = field(default_factory=dict)



def _success(payload, *, status_code=200, audit_action=None, audit_target_type=None, audit_target_id=None, audit_details=None, flow_event=None, flow_fields=None):
    return AdminActionResult(
        payload=payload,
        status_code=status_code,
        audit_action=audit_action,
        audit_target_type=audit_target_type,
        audit_target_id=audit_target_id,
        audit_details=audit_details,
        flow_event=flow_event,
        flow_fields=flow_fields or {},
    )



def _error(message, status_code=400):
    return AdminActionResult(payload={'error': message}, status_code=status_code)


def update_group_links(session, setting_model, setting_keys, set_setting_value, co_url, core_url):
    set_setting_value(session, setting_model, setting_keys['co_create'], co_url)
    set_setting_value(session, setting_model, setting_keys['core'], core_url)
    session.commit()
    return _success(
        {'message': '群链接已更新'},
        audit_action='group_links_update',
        audit_target_type='setting',
        audit_target_id='telegram_group_links',
    )



def toggle_post_hidden(session, post):
    post.is_hidden = not post.is_hidden
    session.commit()
    return _success(
        {'message': '帖子可见状态已更新', 'is_hidden': post.is_hidden},
        audit_action='post_toggle_hide',
        audit_target_type='post',
        audit_target_id=post.id,
        audit_details=f'is_hidden={post.is_hidden}',
    )



def toggle_post_pin(session, post_model, post, admin_id, should_pin=None, exclusive=True, now_factory=None):
    if should_pin is None:
        should_pin = not bool(post.is_pinned)
    should_pin = bool(should_pin)
    now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    if should_pin and exclusive:
        post_model.query.filter(post_model.id != post.id, post_model.is_pinned == True).update({
            'is_pinned': False,
            'pinned_at': None,
            'pinned_by': None,
        }, synchronize_session=False)

    post.is_pinned = should_pin
    post.pinned_at = now_factory() if should_pin else None
    post.pinned_by = admin_id if should_pin else None
    session.commit()
    return _success(
        {
            'is_pinned': post.is_pinned,
            'pinned_at': post.pinned_at.isoformat() if post.pinned_at else None,
            'message': '已置顶' if should_pin else '已取消置顶',
        },
        audit_action='post_pin_toggle',
        audit_target_type='post',
        audit_target_id=post.id,
        audit_details=f'is_pinned={post.is_pinned}',
    )



def toggle_post_comments(session, post):
    post.allow_comments = not post.allow_comments
    session.commit()
    return _success(
        {'message': '评论权限已更新', 'allow_comments': post.allow_comments},
        audit_action='post_toggle_comments',
        audit_target_type='post',
        audit_target_id=post.id,
        audit_details=f'allow_comments={post.allow_comments}',
    )



def toggle_user_ban(session, user):
    if user.is_admin:
        return _error('不能封禁管理员', 400)
    user.is_banned = not user.is_banned
    session.commit()
    return _success(
        {'message': '用户封禁状态已更新', 'is_banned': user.is_banned},
        audit_action='user_ban_toggle',
        audit_target_type='user',
        audit_target_id=user.id,
        audit_details=f'is_banned={user.is_banned}',
    )



def create_announcement(session, announcement_model, admin_id, data, parse_datetime):
    title = (data.get('title') or '').strip()
    content = (data.get('content') or '').strip()
    level = (data.get('level') or 'info').strip().lower()
    entry_type = (data.get('entry_type') or 'announcement').strip().lower()
    starts_at = parse_datetime(data.get('starts_at'))
    expires_at = parse_datetime(data.get('expires_at'))
    activate_now = bool(data.get('activate', True))

    if not title or not content:
        return _error('标题和内容不能为空', 400)
    if len(title) > 120 or len(content) > 1000:
        return _error('标题或内容过长', 400)
    if level not in ('info', 'warning', 'critical'):
        return _error('level 仅支持 info/warning/critical', 400)
    if entry_type not in ('announcement', 'activity'):
        return _error('entry_type 仅支持 announcement/activity', 400)

    if activate_now:
        announcement_model.query.filter(announcement_model.entry_type == entry_type).update({'is_active': False}, synchronize_session=False)

    ann = announcement_model(
        title=title,
        content=content,
        entry_type=entry_type,
        level=level,
        is_active=activate_now,
        starts_at=starts_at,
        expires_at=expires_at,
        created_by=admin_id,
    )
    session.add(ann)
    session.commit()
    return _success(
        {'message': '公告已创建', 'announcement': ann.to_dict()},
        status_code=201,
        audit_action='announcement_create',
        audit_target_type='announcement',
        audit_target_id=ann.id,
        audit_details=f'title={ann.title}',
    )



def update_announcement(session, announcement_model, announcement, data, parse_datetime):
    if 'title' in data:
        announcement.title = (data.get('title') or '').strip()[:120]
    if 'content' in data:
        announcement.content = (data.get('content') or '').strip()[:1000]
    if 'entry_type' in data:
        entry_type = (data.get('entry_type') or 'announcement').strip().lower()
        if entry_type not in ('announcement', 'activity'):
            return _error('entry_type 仅支持 announcement/activity', 400)
        announcement.entry_type = entry_type
    if 'level' in data:
        level = (data.get('level') or 'info').strip().lower()
        if level not in ('info', 'warning', 'critical'):
            return _error('level 仅支持 info/warning/critical', 400)
        announcement.level = level
    if 'starts_at' in data:
        announcement.starts_at = parse_datetime(data.get('starts_at'))
    if 'expires_at' in data:
        announcement.expires_at = parse_datetime(data.get('expires_at'))
    if 'is_active' in data:
        make_active = bool(data.get('is_active'))
        if make_active:
            announcement_model.query.filter(
                announcement_model.id != announcement.id,
                announcement_model.entry_type == announcement.entry_type,
            ).update({'is_active': False}, synchronize_session=False)
        announcement.is_active = make_active
    session.commit()
    return _success(
        {'message': '公告已更新', 'announcement': announcement.to_dict()},
        audit_action='announcement_update',
        audit_target_type='announcement',
        audit_target_id=announcement.id,
    )



def delete_announcement(session, announcement):
    announcement_id = announcement.id
    session.delete(announcement)
    session.commit()
    return _success(
        {'message': '公告已删除'},
        audit_action='announcement_delete',
        audit_target_type='announcement',
        audit_target_id=announcement_id,
    )


def retry_pending_publication(row, actor_user, resume_pending_publication):
    ok, message, post, pending_row = resume_pending_publication(row, actor_user=actor_user)
    if ok:
        return _success({'message': message, 'post': post.to_dict(actor_user.id)})
    if pending_row:
        return AdminActionResult(
            payload={'error': message, 'pending': pending_row.to_dict()},
            status_code=503,
        )
    return _error(message, 400)


def delete_pending_publication(session, row, admin_user_id):
    pending_id = row.id
    tx_hash = row.tx_hash
    session.delete(row)
    session.commit()
    return _success(
        {'message': '待恢复记录已删除'},
        flow_event='pending_publication_admin_deleted',
        flow_fields={
            'pending_id': pending_id,
            'tx_hash': tx_hash,
            'admin_id': admin_user_id,
        },
    )


def retry_pending_publication_batch(
    *,
    run_compensation_batch,
    app,
    pending_model,
    resume_pending_publication,
    logger,
    admin_user_id,
    limit=10,
    min_age_seconds=0,
):
    result = run_compensation_batch(
        app,
        pending_model,
        resume_pending_publication,
        logger,
        limit=limit,
        min_age_seconds=min_age_seconds,
    )
    return _success(
        {
            'message': '已执行一轮待发布补偿任务',
            'result': result,
        },
        flow_event='pending_publication_batch_retry',
        flow_fields={
            'admin_id': admin_user_id,
            **result,
        },
    )



def update_report(session, notification_model, report, data, admin_user_id, now_factory=None):
    old_status = (report.status or '').strip()
    if data.get('status') in ('resolved', 'dismissed'):
        report.status = data['status']
    if ('admin_notes' in data) or ('admin_note' in data):
        notes = (data.get('admin_notes', data.get('admin_note')) or '')[:500]
        report.admin_notes = notes
        report.admin_note = notes

    now_factory = now_factory or (lambda: datetime.now(timezone.utc))
    should_notify_result = (
        report.reporter_id
        and report.status in ('resolved', 'dismissed')
        and report.status != old_status
        and report.result_notified_at is None
    )
    if should_notify_result:
        msg = '您提交的举报已处理，感谢反馈。' if report.status == 'resolved' else '您提交的举报经核实暂不处理。'
        notif = notification_model(
            user_id=report.reporter_id,
            sender_id=admin_user_id,
            post_id=report.post_id,
            type='report_result',
            content=msg,
            link=f"/?post={report.post_id}" if report.post_id else None,
        )
        session.add(notif)
        report.result_notified_at = now_factory()

    session.commit()
    return _success(
        {'message': '已更新', 'report': report.to_dict()},
        audit_action='report_update',
        audit_target_type='report',
        audit_target_id=report.id,
        audit_details=f'status={report.status}',
        flow_event='report_updated',
        flow_fields={
            'report_id': report.id,
            'old_status': old_status,
            'new_status': report.status,
            'notified': bool(should_notify_result),
        },
    )
