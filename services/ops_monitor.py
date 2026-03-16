from datetime import datetime, timedelta

from sqlalchemy import func, case


def build_ops_summary(flow_event_model, pending_model, admin_audit_model, now=None):
    now = now or datetime.utcnow()
    one_hour_ago = now - timedelta(hours=1)
    one_day_ago = now - timedelta(days=1)

    pending_rows = pending_model.query.order_by(pending_model.updated_at.asc(), pending_model.id.asc()).limit(200).all()
    pending_total = len(pending_rows)
    status_counts = {}
    oldest_age_minutes = 0
    for row in pending_rows:
        key = str(row.status or 'unknown')
        status_counts[key] = int(status_counts.get(key, 0)) + 1
        updated_at = getattr(row, 'updated_at', None) or getattr(row, 'created_at', None)
        if updated_at:
            oldest_age_minutes = max(oldest_age_minutes, int(max(0, (now - updated_at).total_seconds()) // 60))

    recent_events = flow_event_model.query.order_by(flow_event_model.created_at.desc(), flow_event_model.id.desc()).limit(20).all()
    last_hour = flow_event_model.query.with_entities(
        func.count(flow_event_model.id),
        func.sum(case((flow_event_model.severity == 'error', 1), else_=0)),
        func.sum(case((flow_event_model.severity == 'warn', 1), else_=0)),
    ).filter(flow_event_model.created_at >= one_hour_ago).first()
    total_last_hour = int((last_hour[0] or 0) if last_hour else 0)
    error_last_hour = int((last_hour[1] or 0) if last_hour else 0)
    warn_last_hour = int((last_hour[2] or 0) if last_hour else 0)

    audit_last_day = admin_audit_model.query.filter(admin_audit_model.created_at >= one_day_ago).count()

    alerts = []
    if status_counts.get('awaiting_retry', 0) >= 1:
        alerts.append({
            'severity': 'error',
            'title': '存在待人工关注的发布失败',
            'message': f"当前有 {status_counts.get('awaiting_retry', 0)} 条待发布记录处于 awaiting_retry。",
        })
    if oldest_age_minutes >= 30 and pending_total:
        alerts.append({
            'severity': 'warn',
            'title': '待发布记录停留时间较长',
            'message': f"最早一条待发布记录已停留约 {oldest_age_minutes} 分钟。",
        })
    if error_last_hour >= 5:
        alerts.append({
            'severity': 'error',
            'title': '最近一小时错误事件偏多',
            'message': f"最近一小时记录到 {error_last_hour} 条 error 级事件。",
        })
    elif warn_last_hour >= 8:
        alerts.append({
            'severity': 'warn',
            'title': '最近一小时告警事件偏多',
            'message': f"最近一小时记录到 {warn_last_hour} 条 warn 级事件。",
        })
    if not alerts:
        alerts.append({
            'severity': 'info',
            'title': '当前未发现明显异常',
            'message': '待发布队列与最近一小时事件数处于正常范围。',
        })

    return {
        'pending': {
            'total': pending_total,
            'status_counts': status_counts,
            'oldest_age_minutes': oldest_age_minutes,
        },
        'events': {
            'last_hour': {
                'total': total_last_hour,
                'error': error_last_hour,
                'warn': warn_last_hour,
            },
            'latest': [row.to_dict() for row in recent_events],
        },
        'audits': {
            'last_24h_total': int(audit_last_day or 0),
        },
        'alerts': alerts,
    }
