import json
from datetime import datetime

from flask import current_app
from extensions import db


def _safe_value(value):
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _safe_value(v) for k, v in value.items()}
    return str(value)


def _infer_severity(event, payload):
    name = str(event or '').lower()
    if any(flag in name for flag in ('failed', 'error', 'invalid', 'forbidden', 'missing')):
        return 'error'
    if any(flag in name for flag in ('blocked', 'retry', 'awaiting', 'warn')):
        return 'warn'
    if payload.get('severity') in ('error', 'warn', 'info'):
        return payload.get('severity')
    return 'info'


def log_event(event, **fields):
    logger = current_app.logger
    payload = {str(k): _safe_value(v) for k, v in (fields or {}).items() if v is not None}
    logger.info('[event:%s] %s', event, json.dumps(payload, ensure_ascii=False, sort_keys=True))
    try:
        from models import FlowEvent
        severity = _infer_severity(event, payload)
        row = {
            'event': str(event or ''),
            'severity': severity,
            'payload_json': json.dumps(payload, ensure_ascii=False, sort_keys=True),
            'created_at': datetime.utcnow(),
        }
        with db.engine.begin() as conn:
            conn.execute(FlowEvent.__table__.insert().values(**row))
    except Exception:
        logger.debug('flow event persistence skipped', exc_info=True)
