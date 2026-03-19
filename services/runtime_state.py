import json
import time
from datetime import datetime, timedelta, timezone


def prune_pending_wallet_nonces(store, ttl_minutes, now=None):
    now = now or datetime.now(timezone.utc)
    expired_keys = [
        key for key, value in store.items()
        if not value or not value.get('created_at') or now - value['created_at'] > timedelta(minutes=ttl_minutes)
    ]
    for key in expired_keys:
        store.pop(key, None)


def pending_wallet_nonce_redis_key(prefix, address):
    return f"{prefix}{str(address or '').lower()}"


def set_pending_wallet_nonce(store, redis_conn, redis_key, ttl_minutes, address, nonce, created_at=None):
    created_at = created_at or datetime.now(timezone.utc)
    payload = {
        'nonce': str(nonce or ''),
        'created_at': created_at.isoformat(),
    }
    if redis_conn:
        try:
            redis_conn.set(redis_key, json.dumps(payload, ensure_ascii=False), ex=max(60, ttl_minutes * 60))
            return
        except Exception:
            pass
    store[str(address or '').lower()] = {
        'nonce': payload['nonce'],
        'created_at': created_at,
    }


def get_pending_wallet_nonce(store, redis_conn, redis_key, address, parse_iso_datetime):
    addr = str(address or '').lower()
    if redis_conn:
        try:
            raw = redis_conn.get(redis_key)
            if raw:
                text = raw.decode('utf-8') if isinstance(raw, (bytes, bytearray)) else str(raw)
                obj = json.loads(text) if text and text.startswith('{') else {'nonce': text}
                created_at = parse_iso_datetime(obj.get('created_at')) if obj.get('created_at') else None
                return {
                    'nonce': obj.get('nonce'),
                    'created_at': created_at,
                }
        except Exception:
            pass
    return store.get(addr)


def delete_pending_wallet_nonce(store, redis_conn, redis_key, address):
    addr = str(address or '').lower()
    if redis_conn:
        try:
            redis_conn.delete(redis_key)
        except Exception:
            pass
    store.pop(addr, None)


def prune_view_count_keys(store, ttl_seconds, now):
    expired = [key for key, ts in store.items() if now - ts >= ttl_seconds]
    for key in expired:
        store.pop(key, None)


def allow_view_count_increment(store, redis_conn, ttl_seconds, post_id, ip, fallback_warned=False):
    if redis_conn:
        key = f"view:{post_id}:{ip}"
        try:
            ok = redis_conn.set(key, '1', ex=ttl_seconds, nx=True)
            return bool(ok), fallback_warned, None
        except Exception:
            pass

    now = time.time()
    key = f"{post_id}:{ip}"
    prune_view_count_keys(store, ttl_seconds, now)
    if key in store and now - store[key] < ttl_seconds:
        return False, True, None
    store[key] = now
    warn_message = None
    if not fallback_warned:
        warn_message = '[ViewCount] Redis unavailable, fallback is process-local and may overcount under multi-worker.'
    return True, True, warn_message
