import os


def ensure_bootstrap_admin(user_model, db_session, new_user_factory):
    admin = user_model.query.filter_by(is_admin=True).first()
    if admin:
        return admin

    bootstrap_username = (os.environ.get('BOOTSTRAP_ADMIN_USERNAME') or '').strip()
    bootstrap_password = (os.environ.get('BOOTSTRAP_ADMIN_PASSWORD') or '').strip()
    if not bootstrap_username or not bootstrap_password:
        print("Skip bootstrap admin: set BOOTSTRAP_ADMIN_USERNAME and BOOTSTRAP_ADMIN_PASSWORD to enable.")
        return None

    existing = user_model.query.filter_by(username=bootstrap_username).first()
    if existing:
        existing.is_admin = True
        if not existing.password_hash:
            existing.set_password(bootstrap_password)
        admin = existing
    else:
        admin = new_user_factory(
            username=bootstrap_username,
            nickname=bootstrap_username,
            is_admin=True,
            avatar='👺',
        )
        admin.set_password(bootstrap_password)
        db_session.add(admin)
    try:
        db_session.commit()
        print(f"Bootstrap admin ensured: {bootstrap_username}")
        return admin
    except Exception as exc:
        db_session.rollback()
        print(f"Init Data Error (bootstrap admin): {exc}")
        return None


def seed_default_article(post_model, db_session, admin_id, load_content_fn):
    title = '甘肃“再生人”华先生访问记'
    try:
        existing = post_model.query.filter(post_model.title.ilike('%华先生访问记%')).first()
    except Exception as exc:
        print(f"Init DB: seed post check failed: {exc}")
        return
    if existing or not admin_id:
        return

    content = load_content_fn()
    if not content:
        print("Init DB: seed content missing, skip article creation.")
        return

    try:
        post = post_model(
            title=title,
            content=content,
            cover_image=None,
            author_id=admin_id,
            is_paid=True,
        )
        db_session.add(post)
        db_session.commit()
        print("Article created.")
    except Exception as exc:
        db_session.rollback()
        print(f"Init DB: seed article insert failed: {exc}")


def ensure_table(table, engine, label):
    try:
        table.create(engine, checkfirst=True)
    except Exception as exc:
        print(f'[Startup] {label} skip: {exc}')


def check_receive_address(receive_address):
    if receive_address and str(receive_address).strip():
        return
    print('=' * 60)
    print('ERROR: RECEIVE_ADDRESS is not set or empty.')
    print('  Set RECEIVE_ADDRESS in .env (or environment) to enable:')
    print('  - Post fee collection')
    print('  - Donate to platform')
    print('  Example: RECEIVE_ADDRESS=0xYourBSCWalletAddress')
    print('=' * 60)


def should_run_init_db():
    return os.environ.get('ALLOW_INIT_DB', '').strip().lower() in ('true', '1', 'yes')
