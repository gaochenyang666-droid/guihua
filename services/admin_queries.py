
def _normalize_text(value):
    return (value or '').strip()


def _parse_limit(raw_value, default_value, max_value):
    try:
        value = int(raw_value or default_value)
    except (TypeError, ValueError):
        value = default_value
    return max(1, min(value, max_value))


def list_pending_publications(pending_model, post_model, *, status='', q='', limit=200, story_path_fn=None):
    status = _normalize_text(status).lower()
    keyword = _normalize_text(q)
    query = pending_model.query
    if status:
        query = query.filter(pending_model.status == status)
    if keyword:
        escaped = keyword.replace('%', '').replace('_', '')
        query = query.filter(
            (pending_model.tx_hash.ilike(f'%{escaped}%')) |
            (pending_model.title.ilike(f'%{escaped}%')) |
            (pending_model.last_error.ilike(f'%{escaped}%'))
        )
    rows = query.order_by(pending_model.updated_at.desc(), pending_model.id.desc()).limit(_parse_limit(limit, 200, 300)).all()
    items = []
    for row in rows:
        existing_post = post_model.query.filter_by(tx_hash=row.tx_hash).first()
        items.append({
            **row.to_dict(),
            'nickname': row.user.nickname if row.user else None,
            'username': row.user.username if row.user else None,
            'profile_url': f'/profile?user={row.user.username}' if row.user and row.user.username else None,
            'post_url': story_path_fn(existing_post) if (existing_post and story_path_fn) else None,
        })
    return {'items': items}


def list_flow_events(flow_event_model, *, severity='', event_keyword='', limit=100):
    severity = _normalize_text(severity).lower()
    event_keyword = _normalize_text(event_keyword)
    query = flow_event_model.query
    if severity in ('info', 'warn', 'error'):
        query = query.filter(flow_event_model.severity == severity)
    if event_keyword:
        escaped = event_keyword.replace('%', '').replace('_', '')
        query = query.filter(flow_event_model.event.ilike(f'%{escaped}%'))
    rows = query.order_by(flow_event_model.created_at.desc(), flow_event_model.id.desc()).limit(_parse_limit(limit, 100, 300)).all()
    return {'items': [row.to_dict() for row in rows]}


def list_users(user_model):
    users = user_model.query.order_by(user_model.created_at.desc()).all()
    return [u.to_dict() for u in users]


def list_announcements(announcement_model, *, limit=100):
    rows = announcement_model.query.order_by(announcement_model.created_at.desc()).limit(_parse_limit(limit, 100, 300)).all()
    return {'announcements': [a.to_dict() for a in rows]}


def list_admin_audit_logs(audit_model, *, limit=100):
    rows = audit_model.query.order_by(audit_model.created_at.desc()).limit(_parse_limit(limit, 100, 300)).all()
    return {'logs': [r.to_dict() for r in rows]}


def list_reports(report_model, *, status='', limit=200):
    status = _normalize_text(status)
    query = report_model.query.order_by(report_model.created_at.desc())
    if status:
        query = query.filter_by(status=status)
    reports = query.limit(_parse_limit(limit, 200, 300)).all()
    return [r.to_dict() for r in reports]


def build_admin_ops_payload(flow_event_model, pending_model, audit_model, *, build_ops_summary, worker_enabled, worker_interval_seconds, redis_status=None):
    summary = build_ops_summary(flow_event_model, pending_model, audit_model)
    summary['worker'] = {
        'enabled': bool(worker_enabled),
        'interval_seconds': worker_interval_seconds,
    }
    if redis_status is not None:
        summary['redis'] = redis_status
    return summary
