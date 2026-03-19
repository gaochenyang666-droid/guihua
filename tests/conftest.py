import os
import pytest
from datetime import datetime, timezone

os.environ.setdefault('SECRET_KEY', 'test-secret-key-for-pytest')
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['FLASK_DEBUG'] = 'false'

import app as app_module


def _fix_naive_tz(target, _context):
    """SQLite drops timezone info; re-attach UTC on load so model methods work."""
    for attr in ('created_at', 'nonce_created_at', 'pinned_at', 'updated_at'):
        val = getattr(target, attr, None)
        if isinstance(val, datetime) and val.tzinfo is None:
            object.__setattr__(target, attr, val.replace(tzinfo=timezone.utc))


def _fix_naive_tz_refresh(target, _context, _attrs):
    _fix_naive_tz(target, None)


_ALL_MODELS = None


def _get_all_models():
    global _ALL_MODELS
    if _ALL_MODELS is None:
        from models import (
            User, Post, Comment, Notification, PendingPublication,
            Announcement, AdminAuditLog, Report, Series, SeriesPost,
            CheckinLog, FlowEvent,
        )
        _ALL_MODELS = (
            User, Post, Comment, Notification, PendingPublication,
            Announcement, AdminAuditLog, Report, Series, SeriesPost,
            CheckinLog, FlowEvent,
        )
    return _ALL_MODELS


@pytest.fixture(scope='session')
def flask_app():
    """Create the Flask app once per test session."""
    from sqlalchemy import event
    application = app_module.app
    application.config['TESTING'] = True
    application.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite://'
    for model in _get_all_models():
        event.listen(model, 'load', _fix_naive_tz)
        event.listen(model, 'refresh', _fix_naive_tz_refresh)
    return application


@pytest.fixture(autouse=True)
def _setup_db(flask_app):
    """Create fresh tables before each test, rollback after."""
    from extensions import db
    with flask_app.app_context():
        db.create_all()
        yield
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()


@pytest.fixture
def db_session(flask_app):
    """Direct DB session access."""
    from extensions import db
    return db.session


@pytest.fixture
def seed_user(flask_app, db_session):
    """Create a regular test user and return (user, auth_headers)."""
    from models import User
    from werkzeug.security import generate_password_hash
    with flask_app.app_context():
        user = User(
            id=1000001,
            username='testuser',
            nickname='Test User',
            password_hash=generate_password_hash('password123'),
            is_admin=False,
        )
        db_session.add(user)
        db_session.commit()

        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        token = pyjwt.encode(
            {'user_id': user.id, 'exp': datetime.now(timezone.utc) + timedelta(hours=24)},
            flask_app.config['SECRET_KEY'],
            algorithm='HS256',
        )
        headers = {'Authorization': f'Bearer {token}'}
        return user, headers


@pytest.fixture
def seed_admin(flask_app, db_session):
    """Create an admin user and return (user, auth_headers)."""
    from models import User
    from werkzeug.security import generate_password_hash
    with flask_app.app_context():
        admin = User(
            id=2000001,
            username='adminuser',
            nickname='Admin',
            password_hash=generate_password_hash('admin123'),
            is_admin=True,
        )
        db_session.add(admin)
        db_session.commit()

        import jwt as pyjwt
        from datetime import datetime, timedelta, timezone
        token = pyjwt.encode(
            {'user_id': admin.id, 'exp': datetime.now(timezone.utc) + timedelta(hours=24)},
            flask_app.config['SECRET_KEY'],
            algorithm='HS256',
        )
        headers = {'Authorization': f'Bearer {token}'}
        return admin, headers
