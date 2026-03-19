from flask import Blueprint, render_template, request, redirect

from utils.security import _get_optional_jwt_payload

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    return render_template('index.html')


@pages_bp.route('/studio')
def studio():
    return render_template('studio.html')


@pages_bp.route('/login')
def login_page():
    return render_template('login.html')


@pages_bp.route('/profile')
def profile():
    user_param = request.args.get('user')
    if not user_param:
        payload = _get_optional_jwt_payload()
        if not payload or not payload.get('user_id'):
            return redirect('/login?next=%2Fprofile')
    return render_template('profile.html')


@pages_bp.route('/series/<int:series_id>')
def series_page(series_id):
    return render_template('series.html', series_id=series_id)


@pages_bp.route('/post/<int:post_id>')
def post_page(post_id):
    return render_template('post.html', post_id=post_id)


@pages_bp.route('/notices')
def notices_page():
    notice_type = (request.args.get('type') or 'announcement').strip().lower()
    if notice_type not in ('announcement', 'activity'):
        notice_type = 'announcement'
    return render_template('notice_center.html', notice_type=notice_type)


@pages_bp.route('/notifications')
def notifications_page():
    return render_template('notifications.html')
