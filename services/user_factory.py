from datetime import datetime, timezone

from sqlalchemy import func

from extensions import db
from models import User


def new_user(**kwargs):
    """SQLite 上 BigInteger 主键不自增，创建用户时补一个递增 ID。"""
    if db.engine.dialect.name == 'sqlite' and not kwargs.get('id'):
        max_id = db.session.query(func.max(User.id)).scalar()
        seed = int(datetime.now(timezone.utc).strftime('%Y') + '1000000')
        next_id = int(max_id) + 1 if max_id else seed
        kwargs['id'] = next_id
    return User(**kwargs)
