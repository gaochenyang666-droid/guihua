from sqlalchemy import text


def ensure_users_wallet_address(db_session, dialect):
    try:
        if dialect == 'postgresql':
            row = db_session.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='wallet_address'"
            ))
            if row.scalar() is not None:
                return
            db_session.execute(text('ALTER TABLE users ADD COLUMN wallet_address VARCHAR(42)'))
            db_session.commit()
            print('[Startup] users.wallet_address added.')
            return
        if dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(users)")).fetchall()
            existing = {col[1] for col in cols}
            if 'wallet_address' not in existing:
                db_session.execute(text('ALTER TABLE users ADD COLUMN wallet_address VARCHAR(42)'))
                db_session.commit()
                print('[Startup] users.wallet_address added.')
    except Exception as exc:
        db_session.rollback()
        if 'already exists' not in str(exc).lower():
            print(f'[Startup] users.wallet_address skip: {exc}')


def ensure_users_withdrawable_balance(db_session, dialect):
    try:
        if dialect == 'postgresql':
            row = db_session.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='withdrawable_balance'"
            ))
            if row.scalar() is not None:
                return
            db_session.execute(text("ALTER TABLE users ADD COLUMN withdrawable_balance VARCHAR(50) DEFAULT '0'"))
            db_session.commit()
            print('[Startup] users.withdrawable_balance added.')
            return
        if dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(users)")).fetchall()
            existing = {col[1] for col in cols}
            if 'withdrawable_balance' not in existing:
                db_session.execute(text("ALTER TABLE users ADD COLUMN withdrawable_balance VARCHAR(50) DEFAULT '0'"))
                db_session.commit()
                print('[Startup] users.withdrawable_balance added.')
    except Exception as exc:
        db_session.rollback()
        if 'already exists' not in str(exc).lower():
            print(f'[Startup] users.withdrawable_balance skip: {exc}')


def ensure_users_checkin_columns(db_session, dialect):
    targets = (
        ('experience_points', "INTEGER DEFAULT 0", "users.experience_points added."),
        ('checkin_streak', "INTEGER DEFAULT 0", "users.checkin_streak added."),
        ('last_checkin_date', "DATE", "users.last_checkin_date added."),
        ('equipped_achievement_key', "VARCHAR(64)", "users.equipped_achievement_key added."),
        ('show_tip_thanks', "BOOLEAN DEFAULT false" if dialect == 'postgresql' else "BOOLEAN DEFAULT 0", "users.show_tip_thanks added."),
    )
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='users' AND column_name IN
                ('experience_points','checkin_streak','last_checkin_date','equipped_achievement_key','show_tip_thanks')
            """)).fetchall()
            existing = {col[0] for col in cols}
        elif dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(users)")).fetchall()
            existing = {col[1] for col in cols}
        else:
            return

        changed = False
        for name, sql_type, log_line in targets:
            if name in existing:
                continue
            db_session.execute(text(f"ALTER TABLE users ADD COLUMN {name} {sql_type}"))
            print(f'[Startup] {log_line}')
            changed = True
        if changed:
            db_session.commit()
    except Exception as exc:
        db_session.rollback()
        if 'already exists' not in str(exc).lower():
            print(f'[Startup] users checkin columns skip: {exc}')


def ensure_posts_tx_nullable(db_session, dialect):
    if dialect != 'postgresql':
        return
    for col in ('tx_hash', 'ipfs_cid'):
        try:
            row = db_session.execute(text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name='posts' AND column_name=:col"
            ), {'col': col}).fetchone()
            if not row or row[0] == 'YES':
                continue
            db_session.execute(text(f'ALTER TABLE posts ALTER COLUMN {col} DROP NOT NULL'))
            db_session.commit()
            print(f'[Startup] posts.{col} set nullable.')
        except Exception as exc:
            db_session.rollback()
            lower = str(exc).lower()
            if 'already' not in lower and 'does not exist' not in lower:
                print(f'[Startup] posts.{col} nullable skip: {exc}')


def ensure_posts_pin_columns(db_session, dialect):
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='posts' AND column_name IN ('is_pinned','pinned_at','pinned_by')
            """)).fetchall()
            existing = {col[0] for col in cols}
            if 'is_pinned' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT false"))
                print('[Startup] posts.is_pinned added.')
            if 'pinned_at' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN pinned_at TIMESTAMP NULL"))
                print('[Startup] posts.pinned_at added.')
            if 'pinned_by' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN pinned_by BIGINT NULL"))
                print('[Startup] posts.pinned_by added.')
            db_session.commit()
            return
        if dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(posts)")).fetchall()
            existing = {col[1] for col in cols}
            changed = False
            if 'is_pinned' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN is_pinned BOOLEAN DEFAULT 0"))
                print('[Startup] posts.is_pinned added.')
                changed = True
            if 'pinned_at' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN pinned_at DATETIME"))
                print('[Startup] posts.pinned_at added.')
                changed = True
            if 'pinned_by' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN pinned_by BIGINT"))
                print('[Startup] posts.pinned_by added.')
                changed = True
            if changed:
                db_session.commit()
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] posts pin columns skip: {exc}')


def ensure_posts_special_column(db_session, dialect):
    try:
        if dialect == 'postgresql':
            row = db_session.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='posts' AND column_name='is_special_announcement'"
            ))
            if row.scalar() is None:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN is_special_announcement BOOLEAN DEFAULT false"))
                db_session.commit()
                print('[Startup] posts.is_special_announcement added.')
            return
        if dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(posts)")).fetchall()
            existing = {col[1] for col in cols}
            if 'is_special_announcement' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN is_special_announcement BOOLEAN DEFAULT 0"))
                db_session.commit()
                print('[Startup] posts.is_special_announcement added.')
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] posts special column skip: {exc}')


def ensure_posts_tags_column(db_session, dialect):
    try:
        if dialect == 'postgresql':
            row = db_session.execute(text(
                "SELECT 1 FROM information_schema.columns WHERE table_name='posts' AND column_name='tags'"
            ))
            if row.scalar() is None:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN tags TEXT"))
                db_session.commit()
                print('[Startup] posts.tags added.')
            return
        if dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(posts)")).fetchall()
            existing = {col[1] for col in cols}
            if 'tags' not in existing:
                db_session.execute(text("ALTER TABLE posts ADD COLUMN tags TEXT"))
                db_session.commit()
                print('[Startup] posts.tags added.')
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] posts tags column skip: {exc}')


def ensure_posts_seo_columns(db_session, dialect):
    targets = (
        ('slug', "VARCHAR(160)", "posts.slug added."),
        ('excerpt', "VARCHAR(300)", "posts.excerpt added."),
        ('seo_title', "VARCHAR(160)", "posts.seo_title added."),
        ('seo_description', "VARCHAR(255)", "posts.seo_description added."),
        ('updated_at', "TIMESTAMP NULL" if dialect == 'postgresql' else "DATETIME", "posts.updated_at added."),
    )
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='posts' AND column_name IN ('slug','excerpt','seo_title','seo_description','updated_at')
            """)).fetchall()
            existing = {col[0] for col in cols}
        elif dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(posts)")).fetchall()
            existing = {col[1] for col in cols}
        else:
            return

        changed = False
        for name, sql_type, log_line in targets:
            if name in existing:
                continue
            db_session.execute(text(f"ALTER TABLE posts ADD COLUMN {name} {sql_type}"))
            print(f'[Startup] {log_line}')
            changed = True
        if changed:
            db_session.commit()
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] posts seo columns skip: {exc}')


def backfill_posts_seo_fields(db_session, post_model):
    try:
        from services.seo import ensure_post_seo_fields
    except Exception as exc:
        print(f'[Startup] posts seo backfill skip: {exc}')
        return

    changed = 0
    try:
        rows = db_session.query(post_model).order_by(post_model.id.asc()).all()
        for row in rows:
            if ensure_post_seo_fields(db_session, row, post_model):
                changed += 1
        if changed:
            db_session.commit()
            print(f'[Startup] posts seo fields backfilled: {changed}')
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] posts seo backfill skip: {exc}')


def ensure_notifications_columns(db_session, dialect):
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='notifications' AND column_name IN ('content','link')
            """)).fetchall()
            existing = {col[0] for col in cols}
        elif dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(notifications)")).fetchall()
            existing = {col[1] for col in cols}
        else:
            return

        changed = False
        if 'content' not in existing:
            db_session.execute(text("ALTER TABLE notifications ADD COLUMN content VARCHAR(500)"))
            print('[Startup] notifications.content added.')
            changed = True
        if 'link' not in existing:
            db_session.execute(text("ALTER TABLE notifications ADD COLUMN link VARCHAR(500)"))
            print('[Startup] notifications.link added.')
            changed = True
        if changed:
            db_session.commit()
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] notifications columns skip: {exc}')


def ensure_reports_columns(db_session, dialect):
    names = ('target_type', 'target_id', 'reported_user_id', 'post_id', 'admin_note', 'admin_notes', 'result_notified_at')
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text(f"""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='reports' AND column_name IN {names}
            """)).fetchall()
            existing = {col[0] for col in cols}
            specs = {
                'target_type': "VARCHAR(20) NOT NULL DEFAULT 'user'",
                'target_id': "BIGINT NOT NULL DEFAULT 0",
                'reported_user_id': "BIGINT NULL",
                'post_id': "BIGINT NULL",
                'admin_note': "VARCHAR(500) NULL",
                'admin_notes': "VARCHAR(500) NULL",
                'result_notified_at': "TIMESTAMP NULL",
            }
        elif dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(reports)")).fetchall()
            existing = {col[1] for col in cols}
            specs = {
                'target_type': "VARCHAR(20) NOT NULL DEFAULT 'user'",
                'target_id': "BIGINT NOT NULL DEFAULT 0",
                'reported_user_id': "BIGINT",
                'post_id': "BIGINT",
                'admin_note': "VARCHAR(500)",
                'admin_notes': "VARCHAR(500)",
                'result_notified_at': "DATETIME",
            }
        else:
            return

        changed = False
        for name, spec in specs.items():
            if name in existing:
                continue
            db_session.execute(text(f"ALTER TABLE reports ADD COLUMN {name} {spec}"))
            print(f'[Startup] reports.{name} added.')
            changed = True
        if changed:
            db_session.commit()
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] reports columns skip: {exc}')


def ensure_announcements_columns(db_session, dialect):
    try:
        if dialect == 'postgresql':
            cols = db_session.execute(text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name='announcements' AND column_name IN ('entry_type','starts_at')
            """)).fetchall()
            existing = {col[0] for col in cols}
            specs = {
                'entry_type': "VARCHAR(20) DEFAULT 'announcement'",
                'starts_at': "TIMESTAMP NULL",
            }
        elif dialect == 'sqlite':
            cols = db_session.execute(text("PRAGMA table_info(announcements)")).fetchall()
            existing = {col[1] for col in cols}
            specs = {
                'entry_type': "VARCHAR(20) DEFAULT 'announcement'",
                'starts_at': "DATETIME",
            }
        else:
            return

        changed = False
        for name, spec in specs.items():
            if name in existing:
                continue
            db_session.execute(text(f"ALTER TABLE announcements ADD COLUMN {name} {spec}"))
            print(f'[Startup] announcements.{name} added.')
            changed = True
        if changed:
            db_session.commit()
    except Exception as exc:
        db_session.rollback()
        print(f'[Startup] announcements columns skip: {exc}')
