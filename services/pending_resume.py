import json
import re
from datetime import datetime, timezone

import bleach
from flask import g, request
from sqlalchemy import func

from extensions import db
from models import (
    User, Post, PendingPublication, UsedTransaction, Notification,
    Series, SeriesPost,
)
from services.blockchain import inspect_transaction_status as _svc_inspect_transaction_status
from services.storage import upload_to_arweave_with_retry
from services.publish_recovery import clear_pending_publication as _svc_clear_pending_publication
from services.observability import log_event as _svc_log_event
from services.posts_logic import (
    extract_mention_tokens as _svc_extract_mention_tokens,
    resolve_mentioned_users as _svc_resolve_mentioned_users,
    series_can_edit as _svc_series_can_edit,
)
from utils.security import bleach_clean_post_content as _bleach_clean_post_content


def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _extract_mention_tokens(text_value):
    return _svc_extract_mention_tokens(text_value)


def _resolve_mentioned_users(tokens, exclude_user_id=None):
    return _svc_resolve_mentioned_users(
        tokens,
        username_lookup=lambda token: User.query.filter(func.lower(User.username) == token.lower()).first(),
        nickname_lookup=lambda token: User.query.filter(func.lower(User.nickname) == token.lower()).first(),
        exclude_user_id=exclude_user_id,
    )


def _series_can_edit(series_obj, viewer):
    return _svc_series_can_edit(series_obj, viewer)


def resume_pending_publication_row(row, actor_user=None):
    from flask import current_app
    TX_CONFIRMATIONS_NEEDED = current_app.config.get('TX_CONFIRMATIONS_NEEDED', 2)

    if not row:
        return False, '未找到待恢复记录', None, None
    owner = db.session.get(User, row.user_id)
    if not owner:
        return False, '该待恢复记录对应的用户不存在', None, row
    existing_post = Post.query.filter_by(tx_hash=row.tx_hash).first()
    if existing_post:
        _svc_clear_pending_publication(PendingPublication, db.session, tx_hash=row.tx_hash)
        db.session.commit()
        return True, '帖子已存在，已同步清理待恢复记录', existing_post, None

    inspect = _svc_inspect_transaction_status(row.tx_hash, tx_confirmations=TX_CONFIRMATIONS_NEEDED)
    row.confirmations = int(inspect.get('confirmations', 0) or 0)
    if not inspect.get('ok') and inspect.get('stage') != 'confirmed':
        row.status = 'awaiting_retry'
        row.last_error = inspect.get('message') or '交易状态异常'
        db.session.commit()
        return False, row.last_error, None, row
    if inspect.get('stage') not in ('confirmed',) and inspect.get('stage') not in ('awaiting_confirmation', 'broadcasted'):
        row.status = 'awaiting_retry'
        row.last_error = inspect.get('message') or '交易状态异常'
        db.session.commit()
        return False, row.last_error, None, row
    if inspect.get('stage') in ('awaiting_confirmation', 'broadcasted'):
        row.status = 'payment_verified'
        row.last_error = inspect.get('message') or '链上确认中'
        db.session.commit()
        return False, row.last_error, None, row

    try:
        normalized_tags = []
        try:
            normalized_tags = json.loads(row.tags) if row.tags else []
        except Exception:
            normalized_tags = []
        if not isinstance(normalized_tags, list):
            normalized_tags = []

        clean_title = bleach.clean(row.title or '', strip=True)
        clean_content = _bleach_clean_post_content(row.content or '')
        if not clean_title or not clean_content.strip():
            row.status = 'awaiting_retry'
            row.last_error = '待恢复记录缺少完整标题或正文'
            db.session.commit()
            return False, row.last_error, None, row

        target_series = db.session.get(Series, row.series_id) if row.series_id else None
        if target_series and not _series_can_edit(target_series, owner):
            target_series = None

        if not row.ipfs_cid:
            payload = {
                'title': clean_title,
                'content': clean_content,
                'tags': normalized_tags,
                'author': owner.address,
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'tx_hash': row.tx_hash,
                'region': row.region or '其他',
                'platform': 'GuiHua Web3 (Arweave)'
            }
            storage_id, storage_type, last_error = upload_to_arweave_with_retry(payload, retries=3)
            if not storage_id:
                row.status = 'awaiting_retry'
                row.last_error = '支付已确认，但永存档案写入失败。可直接继续发布重试，无需再次支付。'
                db.session.commit()
                return False, row.last_error, None, row
            row.ipfs_cid = storage_id
            row.status = 'storage_ready'
            row.last_error = None
            db.session.flush()

        post = Post(
            title=clean_title,
            content=clean_content,
            cover_image=None,
            images='[]',
            tags=json.dumps(normalized_tags, ensure_ascii=False),
            author_id=owner.id,
            tx_hash=row.tx_hash,
            ipfs_cid=row.ipfs_cid,
            is_paid=True,
            is_on_chain=True,
            region=row.region or '其他',
            is_special_announcement=bool(row.is_special_announcement) if owner.is_admin else False,
            post_type=1
        )
        db.session.add(post)
        db.session.flush()

        if target_series:
            max_order = db.session.query(func.max(SeriesPost.order_index)).filter(SeriesPost.series_id == target_series.id).scalar() or 0
            db.session.add(SeriesPost(series_id=target_series.id, post_id=post.id, order_index=int(max_order) + 1))

        if not UsedTransaction.query.filter_by(tx_hash=row.tx_hash).first():
            db.session.add(UsedTransaction(tx_hash=row.tx_hash, user_id=owner.id))

        mention_source = re.sub(r'<[^>]+>', ' ', clean_content or '')
        mention_tokens = _extract_mention_tokens(mention_source)
        mention_users = _resolve_mentioned_users(mention_tokens, exclude_user_id=owner.id)
        for u in mention_users:
            db.session.add(Notification(
                user_id=u.id,
                sender_id=owner.id,
                post_id=post.id,
                comment_id=None,
                type='mention',
                content='在帖子中提到了你',
                link=f"/?post={post.id}"
            ))

        db.session.delete(row)
        db.session.commit()
        _log_flow_event(
            'pending_publication_recovered',
            tx_hash=post.tx_hash,
            post_id=post.id,
            operator_user_id=getattr(actor_user, 'id', None),
            target_user_id=owner.id,
        )
        return True, '待恢复发布已补偿完成', post, None
    except Exception as e:
        db.session.rollback()
        row = PendingPublication.query.filter_by(tx_hash=row.tx_hash).first()
        if row:
            row.status = 'awaiting_retry'
            row.last_error = '支付已确认，但发布流程未完成。可直接继续发布重试。'
            db.session.commit()
        _log_flow_event('pending_publication_recovery_failed', tx_hash=getattr(row, 'tx_hash', None), reason=str(e)[:180])
        return False, '待恢复发布补偿失败，请稍后重试', None, row
