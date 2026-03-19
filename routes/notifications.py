from flask import Blueprint, request, jsonify, g
from sqlalchemy.orm import joinedload

from extensions import db
from models import Notification
from utils.security import token_required

notifications_bp = Blueprint('notifications', __name__, url_prefix='/api/notifications')


@notifications_bp.route('', methods=['GET'])
@token_required
def get_notifications():
    page = request.args.get('page', 1, type=int)
    per_page = 20

    pagination = Notification.query.filter_by(user_id=g.current_user.id)\
        .options(
            joinedload(Notification.sender),
            joinedload(Notification.post),
        )\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)

    notifs = pagination.items

    return jsonify({
        'notifications': [n.to_dict() for n in notifs],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })


@notifications_bp.route('/<int:id>/read', methods=['PUT'])
@token_required
def read_notification(id):
    notif = Notification.query.get_or_404(id)
    if notif.user_id != g.current_user.id:
        return jsonify({'error': '这不是你的通知'}), 403

    notif.is_read = True
    db.session.commit()
    return jsonify({'message': '已标记为已读'})


@notifications_bp.route('/read_all', methods=['PUT'])
@token_required
def read_all_notifications():
    Notification.query.filter_by(user_id=g.current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': '已全部标记为已读'})
