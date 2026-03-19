import json
import re
from datetime import datetime, timezone

from flask import current_app, request, g
from extensions import db


_REDACTED = '[redacted]'
_HEX_ADDRESS_RE = re.compile(r'^0x[a-fA-F0-9]{40}$')
_HEX_TX_RE = re.compile(r'^0x[a-fA-F0-9]{64}$')
_SENSITIVE_KEY_PARTS = (
    'password', 'token', 'secret', 'signature', 'authorization', 'cookie',
    'private_key', 'secret_key', 'wallet_key'
)


def _mask_address(value):
    text = str(value or '').strip()
    if len(text) < 12:
        return text
    return text[:6] + '...' + text[-4:]


def _mask_tx_hash(value):
    text = str(value or '').strip()
    if len(text) < 16:
        return text
    return text[:10] + '...' + text[-6:]


def _sanitize_key_value(key, value):
    key_name = str(key or '').lower()
    if any(part in key_name for part in _SENSITIVE_KEY_PARTS):
        return _REDACTED
    if key_name == 'nonce':
        return _REDACTED
    if 'address' in key_name and isinstance(value, str):
        return _mask_address(value)
    if 'tx_hash' in key_name and isinstance(value, str):
        return _mask_tx_hash(value)
    if key_name in ('last_error', 'reason', 'details', 'message') and isinstance(value, str):
        return value[:180]
    if isinstance(value, str):
        if _HEX_ADDRESS_RE.match(value.strip()):
            return _mask_address(value)
        if _HEX_TX_RE.match(value.strip()):
            return _mask_tx_hash(value)
    return value


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


def _sanitize_payload(payload):
    sanitized = {}
    for raw_key, raw_value in (payload or {}).items():
        key = str(raw_key)
        value = raw_value
        if isinstance(value, dict):
            value = _sanitize_payload(value)
        elif isinstance(value, (list, tuple, set)):
            items = []
            for item in value:
                if isinstance(item, dict):
                    items.append(_sanitize_payload(item))
                else:
                    items.append(_sanitize_key_value(key, _safe_value(item)))
            value = items
        else:
            value = _sanitize_key_value(key, _safe_value(value))
        sanitized[key] = value
    return sanitized


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
    payload = _sanitize_payload(payload)
    logger.info('[event:%s] %s', event, json.dumps(payload, ensure_ascii=False, sort_keys=True))
    try:
        from models import FlowEvent
        severity = _infer_severity(event, payload)
        row = {
            'event': str(event or ''),
            'severity': severity,
            'payload_json': json.dumps(payload, ensure_ascii=False, sort_keys=True),
            'created_at': datetime.now(timezone.utc),
        }
        with db.engine.begin() as conn:
            conn.execute(FlowEvent.__table__.insert().values(**row))
    except Exception:
        logger.debug('flow event persistence skipped', exc_info=True)


def log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    log_event(event, **extra)
