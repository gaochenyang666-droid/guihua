import os
import threading
import time
from datetime import datetime, timedelta

from extensions import db


_worker_lock = threading.Lock()
_worker_started = False


def compensation_interval_seconds():
    raw = (os.environ.get('PUBLISH_COMPENSATION_INTERVAL_SEC') or '').strip()
    if raw:
        try:
            return max(0, int(raw))
        except Exception:
            return 180
    return 180


def should_start_compensation_worker():
    explicit = (os.environ.get('ENABLE_PUBLISH_COMPENSATION_WORKER') or '').strip().lower()
    if explicit:
        return explicit in ('1', 'true', 'yes', 'on')
    server_software = (os.environ.get('SERVER_SOFTWARE') or '').lower()
    if 'gunicorn' in server_software:
        return False
    if os.environ.get('FLASK_DEBUG', 'false').lower() == 'true':
        return os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    return True


def list_retry_candidate_ids(pending_model, now=None, limit=10, min_age_seconds=60):
    now = now or datetime.utcnow()
    cutoff = now - timedelta(seconds=max(0, int(min_age_seconds or 0)))
    rows = pending_model.query.filter(
        pending_model.status.in_(('initiated', 'payment_verified', 'storage_ready', 'awaiting_retry')),
        pending_model.updated_at <= cutoff,
    ).order_by(pending_model.updated_at.asc(), pending_model.id.asc()).limit(max(1, int(limit or 1))).all()
    return [int(row.id) for row in rows]


def run_compensation_batch(app, pending_model, runner, logger, limit=10, min_age_seconds=60):
    processed = 0
    recovered = 0
    skipped = 0
    errors = 0
    with app.app_context():
        ids = list_retry_candidate_ids(pending_model, limit=limit, min_age_seconds=min_age_seconds)
        for pending_id in ids:
            row = db.session.get(pending_model, pending_id)
            if not row:
                skipped += 1
                continue
            processed += 1
            ok, _, post, pending_row = runner(row, actor_user=None)
            if ok and post:
                recovered += 1
            elif pending_row:
                skipped += 1
            else:
                errors += 1
    logger.info('[publish-compensation] processed=%s recovered=%s skipped=%s errors=%s', processed, recovered, skipped, errors)
    return {
        'processed': processed,
        'recovered': recovered,
        'skipped': skipped,
        'errors': errors,
    }


def start_compensation_worker(app, pending_model, runner, logger, limit=10, min_age_seconds=60):
    global _worker_started
    interval = compensation_interval_seconds()
    if interval <= 0 or not should_start_compensation_worker():
        return False, interval
    with _worker_lock:
        if _worker_started:
            return False, interval
        _worker_started = True

    def loop():
        while True:
            try:
                run_compensation_batch(app, pending_model, runner, logger, limit=limit, min_age_seconds=min_age_seconds)
            except Exception:
                logger.exception('publish compensation worker loop failed')
            time.sleep(interval)

    thread = threading.Thread(target=loop, name='publish-compensation-worker', daemon=True)
    thread.start()
    return True, interval
