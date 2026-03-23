import os
from datetime import datetime, timezone

from flask import Blueprint, request, jsonify, g, current_app, Response
from web3 import Web3

from extensions import db
from models import (
    User, Post, Tip, UsedTransaction, Notification, Report,
    Announcement, calc_level_info,
)
from utils.security import (
    _rate_limit, _get_optional_jwt_payload, token_required,
)
from services.storage import upload_to_imgbb
from services.blockchain import get_post_fee_usdt_raw, verify_transaction
from services.app_support import (
    humanize_verify_error as _svc_humanize_verify_error,
    tip_amount_to_usdt_str as _svc_tip_amount_to_usdt_str,
)
from services.user_progress import get_user_level as _svc_get_user_level
from services.observability import log_event as _svc_log_event
from services.seo import build_absolute_url, get_site_base_url, ensure_post_seo_fields, story_path

misc_bp = Blueprint('misc', __name__)


def _log_flow_event(event, **fields):
    extra = dict(fields or {})
    extra.setdefault('path', request.path if request else None)
    extra.setdefault('method', request.method if request else None)
    extra.setdefault('user_id', getattr(getattr(g, 'current_user', None), 'id', None))
    extra.setdefault('ip', request.headers.get('X-Forwarded-For', request.remote_addr) if request else None)
    _svc_log_event(event, **extra)


def _humanize_verify_error(message):
    return _svc_humanize_verify_error(message)


def _tip_amount_to_usdt_str(raw_amount):
    return _svc_tip_amount_to_usdt_str(raw_amount, current_app.config['BSC']['USDT_DECIMALS'])


def _get_user_level(user):
    return _svc_get_user_level(user, calc_level_info)


@misc_bp.route('/robots.txt', methods=['GET'])
def robots_txt():
    base = get_site_base_url(request)
    lines = [
        'User-agent: *',
        'Allow: /',
        'Disallow: /login',
        'Disallow: /studio',
        'Disallow: /profile',
        'Disallow: /notifications',
        'Disallow: /notices',
        'Disallow: /api/auth/',
        'Disallow: /api/admin/',
        'Disallow: /api/notifications/',
        'Disallow: /api/reports',
        'Disallow: /api/reports/',
        f'Sitemap: {base}/sitemap.xml',
    ]
    return Response('\n'.join(lines) + '\n', mimetype='text/plain; charset=utf-8')


@misc_bp.route('/sitemap.xml', methods=['GET'])
def sitemap_xml():
    rows = Post.query.filter_by(is_hidden=False).order_by(Post.created_at.desc()).all()
    items = [
        ('/', None),
        ('/stories', None),
        ('/about', None),
    ]
    for row in rows:
        if ensure_post_seo_fields(db.session, row, Post):
            db.session.flush()
        if not row.slug:
            continue
        updated_at = getattr(row, 'updated_at', None) or getattr(row, 'created_at', None)
        items.append((story_path(row), updated_at))
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    xml = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for path, lastmod in items:
        xml.append('<url>')
        xml.append(f'<loc>{build_absolute_url(path, request)}</loc>')
        if lastmod:
            stamp = lastmod if lastmod.tzinfo else lastmod.replace(tzinfo=timezone.utc)
            xml.append(f'<lastmod>{stamp.isoformat()}</lastmod>')
        xml.append('</url>')
    xml.append('</urlset>')
    return Response('\n'.join(xml), mimetype='application/xml; charset=utf-8')


# ---- Config ----

@misc_bp.route('/api/config/fees', methods=['GET'])
def get_fees():
    receive_address = current_app.config['BSC']['RECEIVE_ADDRESS']
    if not receive_address:
        return jsonify({'error': '平台收款地址未配置'}), 503
    fee_raw = get_post_fee_usdt_raw()
    decimals = current_app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_raw / (10 ** decimals), 4)
    return jsonify({
        'fee': str(fee_raw),
        'fee_currency': 'USDT',
        'fee_usdt': fee_usdt,
        'fee_cny': current_app.config['BSC']['POST_FEE_CNY'],
        'chain_id': current_app.config['BSC']['CHAIN_ID'],
        'receive_address': receive_address,
        'usdt_contract': current_app.config['BSC']['USDT_CONTRACT_ADDRESS'],
    })


@misc_bp.route('/api/config/public', methods=['GET'])
def get_public_config():
    return jsonify({
        'walletconnect_project_id': os.environ.get('WALLETCONNECT_PROJECT_ID') or '',
    })


# ---- Announcements (public) ----

@misc_bp.route('/api/announcements/active', methods=['GET'])
def get_active_announcement():
    now = datetime.now(timezone.utc)
    ann = Announcement.query.filter(
        Announcement.entry_type == 'announcement',
        Announcement.is_active == True,
        ((Announcement.starts_at == None) | (Announcement.starts_at <= now)),
        ((Announcement.expires_at == None) | (Announcement.expires_at > now)),
    ).order_by(Announcement.created_at.desc()).first()
    return jsonify({'announcement': ann.to_dict() if ann else None})


@misc_bp.route('/api/announcements', methods=['GET'])
def list_public_announcements():
    now = datetime.now(timezone.utc)
    entry_type = (request.args.get('type') or '').strip().lower()
    active_only = request.args.get('is_active')
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    query = Announcement.query
    if entry_type in ('announcement', 'activity'):
        query = query.filter(Announcement.entry_type == entry_type)
    if active_only in ('1', 'true', 'yes'):
        query = query.filter(
            Announcement.is_active == True,
            ((Announcement.starts_at == None) | (Announcement.starts_at <= now)),
            ((Announcement.expires_at == None) | (Announcement.expires_at > now)),
        )
    query = query.order_by(Announcement.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return jsonify({
        'announcements': [a.to_dict() for a in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
    })


# ---- Upload ----

@misc_bp.route('/api/upload', methods=['POST'])
@token_required
def upload():
    if _rate_limit('upload', 30):
        return jsonify({'error': '上传过于频繁，请稍后再试'}), 429
    if 'file' not in request.files:
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['file']
    if not file or (getattr(file, 'filename', None) or '').strip() == '':
        return jsonify({'error': '未选择文件'}), 400
    url, err = upload_to_imgbb(file)
    if url:
        return jsonify({'url': url})
    return jsonify({'error': err or '上传失败'}), 500


# ---- Tips ----

@misc_bp.route('/api/users/<int:user_id>/tips-received', methods=['GET'])
def list_tips_received(user_id):
    user = User.query.get_or_404(user_id)
    payload = _get_optional_jwt_payload()
    viewer_id = payload.get('user_id') if payload else None
    viewer = User.query.get(viewer_id) if viewer_id else None
    is_owner = bool(viewer and viewer.id == user.id)
    is_admin = bool(viewer and viewer.is_admin)
    if not (is_owner or is_admin or bool(getattr(user, 'show_tip_thanks', False))):
        return jsonify({'error': '作者未开启感谢名单展示'}), 403

    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    include_amount = (request.args.get('show_amount') or '').strip().lower() in ('1', 'true', 'yes')
    if not (is_owner or is_admin):
        include_amount = False

    q = Tip.query.filter_by(to_user_id=user.id).order_by(Tip.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    rows = []
    for t in pagination.items:
        sender = t.sender.to_dict() if t.sender else None
        item = {
            'id': t.id,
            'post_id': t.post_id,
            'token_symbol': t.token_symbol or 'USDT',
            'tx_hash': t.tx_hash,
            'created_at': t.created_at.isoformat() if t.created_at else None,
            'from_user': sender,
        }
        if include_amount:
            item['amount_usdt'] = _tip_amount_to_usdt_str(t.amount)
        rows.append(item)
    return jsonify({
        'items': rows,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'show_amount': include_amount,
        'show_tip_thanks': bool(getattr(user, 'show_tip_thanks', False)),
    })


@misc_bp.route('/api/posts/<int:post_id>/tips', methods=['GET'])
def list_post_tips(post_id):
    post = Post.query.get_or_404(post_id)
    page = max(1, request.args.get('page', 1, type=int))
    per_page = min(max(1, request.args.get('per_page', 20, type=int)), 50)
    q = Tip.query.filter_by(post_id=post.id).order_by(Tip.created_at.desc())
    pagination = q.paginate(page=page, per_page=per_page, error_out=False)
    rows = []
    for t in pagination.items:
        rows.append({
            'id': t.id,
            'from_user': t.sender.to_dict() if t.sender else None,
            'created_at': t.created_at.isoformat() if t.created_at else None,
        })
    return jsonify({
        'items': rows,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page,
        'post_id': post.id,
    })


@misc_bp.route('/api/tips/verify', methods=['POST'])
@token_required
def verify_tip():
    USDT_DECIMALS = current_app.config['BSC']['USDT_DECIMALS']
    TIP_MIN_USDT_RAW = 10 ** USDT_DECIMALS

    if _rate_limit('tip_verify', 30):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    if not data:
        return jsonify({'error': '请求体不能为空'}), 400
    tx_hash = data.get('tx_hash')
    post_id = data.get('post_id')
    if not tx_hash or not post_id:
        return jsonify({'error': '缺少必要参数'}), 400
    post = Post.query.get_or_404(post_id)
    if not post.author:
        return jsonify({'error': '未找到帖子作者'}), 400
    author_address = (post.author.wallet_address or post.author.address or '').strip()
    if not author_address or not Web3.is_address(author_address):
        return jsonify({'error': '作者未绑定钱包，暂无法打赏'}), 400
    if not g.current_user.address:
        return jsonify({'error': '请先绑定钱包后再进行打赏'}), 400
    is_valid, result = verify_transaction(
        tx_hash,
        g.current_user.address,
        expected_recipient=author_address,
        min_amount=TIP_MIN_USDT_RAW,
        payment_type='usdt',
    )
    if not is_valid:
        return jsonify({'error': _humanize_verify_error(result)}), 400
    amount_full = int(result)
    if Tip.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': '该打赏交易已记录，无需重复提交'}), 400
    decimals = USDT_DECIMALS
    tip = Tip(
        tx_hash=tx_hash,
        from_user_id=g.current_user.id,
        to_user_id=post.author.id,
        post_id=post.id,
        amount=str(amount_full),
    )
    used_tx = UsedTransaction(tx_hash=tx_hash, user_id=g.current_user.id)
    try:
        db.session.add(tip)
        db.session.add(used_tx)
        if post.author.id != g.current_user.id:
            notif = Notification(
                user_id=post.author.id,
                sender_id=g.current_user.id,
                post_id=post.id,
                type='tip',
                content='给你打赏了帖子',
                link=f"/?post={post.id}",
            )
            db.session.add(notif)
        db.session.commit()
    except Exception:
        db.session.rollback()
        current_app.logger.exception(
            'Verify tip failed: post_id=%s user_id=%s tx_hash=%s',
            post_id, getattr(g.current_user, 'id', None), tx_hash,
        )
        return jsonify({'error': '服务器错误，请稍后重试'}), 500
    amount_usdt = amount_full / (10 ** decimals)
    return jsonify({
        'message': '打赏成功，已直接转入作者钱包',
        'tip': {
            'amount': str(amount_full),
            'tx_hash': tx_hash,
            'amount_usdt': round(amount_usdt, 2),
            'author_receives_usdt': round(amount_usdt, 2),
        },
    })


# ---- Reports (user-facing) ----

@misc_bp.route('/api/reports', methods=['POST'])
@token_required
def create_report():
    if _rate_limit('report', 20):
        return jsonify({'error': '举报过于频繁，请稍后再试'}), 429
    data = request.get_json(silent=True) or {}
    post_id = data.get('post_id')
    reported_user_id = data.get('reported_user_id')
    reason = (data.get('reason') or '').strip()
    if not reason or len(reason) > 500:
        _log_flow_event('report_blocked', reason='invalid_reason')
        return jsonify({'error': '请填写举报原因（最多500字）'}), 400
    if not post_id and not reported_user_id:
        _log_flow_event('report_blocked', reason='missing_target')
        return jsonify({'error': '请指定举报的帖子或用户'}), 400
    target_type = 'user'
    target_id = 0
    if post_id:
        post = Post.query.get(post_id)
        if not post:
            _log_flow_event('report_blocked', reason='post_missing', post_id=post_id)
            return jsonify({'error': '帖子不存在'}), 404
        reported_user_id = post.author_id
        target_type = 'post'
        target_id = int(post_id)
    elif reported_user_id:
        target_type = 'user'
        try:
            target_id = int(reported_user_id)
        except (TypeError, ValueError):
            _log_flow_event('report_blocked', reason='invalid_user_id', reported_user_id=reported_user_id)
            return jsonify({'error': '被举报用户 ID 非法'}), 400
    r = Report(
        reporter_id=g.current_user.id,
        target_type=target_type,
        target_id=target_id,
        reported_user_id=reported_user_id,
        post_id=post_id,
        reason=reason,
        status='pending',
    )
    db.session.add(r)
    db.session.commit()
    _log_flow_event('report_created', report_id=r.id, target_type=target_type, target_id=target_id, post_id=post_id)
    return jsonify({'message': '举报已提交，管理员会尽快处理', 'id': r.id}), 201


@misc_bp.route('/api/reports/priority', methods=['POST'])
@token_required
def report_priority():
    if _rate_limit('report_priority', 20):
        return jsonify({'error': '举报过于频繁，请稍后再试'}), 429
    level = _get_user_level(g.current_user)
    is_admin = bool(getattr(g.current_user, 'is_admin', False))
    if is_admin:
        level = 9999
    if level < 2:
        _log_flow_event('priority_report_blocked', reason='level_too_low', level=level)
        return jsonify({'error': '等级达到 2 才能解锁该举报权限'}), 403
    data = request.get_json(silent=True) or {}
    extra_reason = (data.get('reason') or '').strip()
    if len(extra_reason) > 460:
        _log_flow_event('priority_report_blocked', reason='reason_too_long')
        return jsonify({'error': '补充说明最多 460 字'}), 400
    reason = '等级权益举报'
    if extra_reason:
        reason = f'{reason} | {extra_reason}'
    row = Report(
        reporter_id=g.current_user.id,
        target_type='user',
        target_id=0,
        reported_user_id=None,
        post_id=None,
        reason=reason,
        status='pending',
    )
    db.session.add(row)
    db.session.commit()
    _log_flow_event('priority_report_created', report_id=row.id, level=level)
    return jsonify({'message': '已提交快速举报', 'id': row.id}), 201
