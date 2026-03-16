import json
from datetime import datetime

from flask import current_app


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


def log_event(event, **fields):
    logger = current_app.logger
    payload = {str(k): _safe_value(v) for k, v in (fields or {}).items() if v is not None}
    logger.info('[event:%s] %s', event, json.dumps(payload, ensure_ascii=False, sort_keys=True))
