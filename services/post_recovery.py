def build_check_tx_payload(post_model, pending_model, tx_hash, inspect_transaction_status, confirmations_needed):
    post = post_model.query.filter_by(tx_hash=tx_hash).first()
    if post:
        return {
            'status': 'success',
            'stage': 'published',
            'message': '帖子已成功发布',
            'post_id': post.id,
            'post_title': post.title,
        }, 200

    pending_row = pending_model.query.filter_by(tx_hash=tx_hash).first()
    if pending_row:
        if pending_row.status == 'awaiting_retry':
            return {
                'status': 'pending',
                'stage': 'awaiting_retry',
                'message': pending_row.last_error or '支付已确认，但永存写入失败，可直接继续发布重试',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': confirmations_needed,
                'pending_publication': pending_row.to_dict(),
            }, 200
        if pending_row.status == 'storage_ready':
            return {
                'status': 'pending',
                'stage': 'storage_ready',
                'message': '永存档案已写入，正在创建帖子记录',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': confirmations_needed,
                'pending_publication': pending_row.to_dict(),
            }, 200
        if pending_row.status in ('payment_verified', 'initiated'):
            return {
                'status': 'pending',
                'stage': pending_row.status,
                'message': '支付已记录，正在继续处理发布',
                'confirmations': int(getattr(pending_row, 'confirmations', 0) or 0),
                'confirmations_needed': confirmations_needed,
                'pending_publication': pending_row.to_dict(),
            }, 200

    inspect = inspect_transaction_status(tx_hash, tx_confirmations=confirmations_needed)
    if inspect.get('stage') == 'confirmed':
        return {
            'status': 'pending',
            'stage': 'confirmed_processing',
            'message': '链上支付已确认，正在写入永存档案并创建帖子',
            'confirmations': inspect.get('confirmations', 0),
            'confirmations_needed': inspect.get('confirmations_needed', confirmations_needed),
        }, 200
    if inspect.get('ok'):
        return {
            'status': 'pending',
            'stage': inspect.get('stage') or 'pending',
            'message': inspect.get('message') or '处理中',
            'confirmations': inspect.get('confirmations', 0),
            'confirmations_needed': inspect.get('confirmations_needed', confirmations_needed),
        }, 200
    return {
        'status': 'error',
        'stage': inspect.get('stage') or 'error',
        'message': inspect.get('message') or '交易状态异常',
        'confirmations': inspect.get('confirmations', 0),
        'confirmations_needed': inspect.get('confirmations_needed', confirmations_needed),
    }, 200


def clear_pending_publication_for_user(session, pending_model, user_id, tx_hash=None, latest_getter=None):
    row = None
    if tx_hash:
        row = pending_model.query.filter_by(tx_hash=tx_hash, user_id=user_id).first()
    elif latest_getter:
        row = latest_getter(pending_model, user_id)
    if row:
        session.delete(row)
        session.commit()
        return row
    return None


def retry_pending_publication_for_user(
    *,
    session,
    pending_model,
    user,
    data,
    normalize_tags,
    upsert_pending_publication,
    resume_pending_publication,
):
    tx_hash = (data.get('tx_hash') or '').strip()
    if not tx_hash:
        return {'error': '缺少交易哈希'}, 400

    row = pending_model.query.filter_by(tx_hash=tx_hash, user_id=user.id).first()
    if not row:
        payload = {
            'title': data.get('title') or '',
            'content': data.get('content') or '',
            'tags': normalize_tags(data.get('tags') or data.get('tag_names')),
            'region': data.get('region') or '其他',
            'series_id': data.get('series_id'),
            'is_special_announcement': bool(data.get('is_special_announcement')) if user.is_admin else False,
        }
        row = upsert_pending_publication(
            pending_model,
            session,
            user.id,
            tx_hash,
            payload=payload,
            status='initiated',
        )
        session.commit()

    ok, message, post, pending_row = resume_pending_publication(row, actor_user=user)
    if ok:
        return {'message': message, 'post': post.to_dict(user.id)}, 200
    if pending_row:
        return {'error': message, 'pending': pending_row.to_dict()}, 503
    return {'error': message}, 400
