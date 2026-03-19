from .pages import pages_bp
from .auth import auth_bp
from .user import bp as user_bp
from .posts import posts_bp
from .series import bp as series_bp
from .notifications import notifications_bp
from .admin import admin_bp
from .misc import misc_bp


def register_blueprints(app):
    app.register_blueprint(pages_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(user_bp)
    app.register_blueprint(posts_bp)
    app.register_blueprint(series_bp)
    app.register_blueprint(notifications_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(misc_bp)
