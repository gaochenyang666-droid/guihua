import json


def upsert_pending_publication(pending_model, db_session, user_id, tx_hash, payload=None, status='initiated',
                               last_error=None, ipfs_cid=None, confirmations=None):
    row = pending_model.query.filter_by(tx_hash=tx_hash).first()
    if not row:
        row = pending_model(user_id=user_id, tx_hash=tx_hash)
        db_session.add(row)
    if payload:
        row.title = payload.get('title') or row.title
        row.content = payload.get('content') or row.content
        row.region = payload.get('region') or row.region or '其他'
        row.series_id = payload.get('series_id') if payload.get('series_id') not in ('', None) else None
        row.is_special_announcement = bool(payload.get('is_special_announcement', row.is_special_announcement))
        tags = payload.get('tags')
        if tags is not None:
            row.tags = json.dumps(tags if isinstance(tags, list) else [], ensure_ascii=False)
    if status:
        row.status = status
    if last_error is not None:
        row.last_error = last_error[:500] if last_error else None
    if ipfs_cid is not None:
        row.ipfs_cid = ipfs_cid
    if confirmations is not None:
        try:
            row.confirmations = int(confirmations or 0)
        except Exception:
            row.confirmations = 0
    return row


def clear_pending_publication(pending_model, db_session, tx_hash=None, user_id=None):
    row = None
    if tx_hash:
        row = pending_model.query.filter_by(tx_hash=tx_hash).first()
    elif user_id:
        row = pending_model.query.filter_by(user_id=user_id).order_by(
            pending_model.updated_at.desc(), pending_model.id.desc()
        ).first()
    if row:
        db_session.delete(row)
    return row


def get_latest_pending_publication(pending_model, user_id):
    return pending_model.query.filter(
        pending_model.user_id == user_id,
        pending_model.status != 'published'
    ).order_by(pending_model.updated_at.desc(), pending_model.id.desc()).first()

