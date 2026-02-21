#!/usr/bin/env python3
"""确保 posts 表的 tx_hash、ipfs_cid 允许 NULL，便于管理员发帖（无需上链）。
在项目根目录执行：python scripts/migrate_posts_nullable_tx.py
Render 上若管理员发帖报 Database error，可在 Shell 中运行此脚本。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def run():
    from app import app, db
    from sqlalchemy import text
    with app.app_context():
        # PostgreSQL
        dialect = db.engine.dialect.name
        if dialect == 'postgresql':
            for col in ['tx_hash', 'ipfs_cid']:
                try:
                    db.session.execute(text(
                        f'ALTER TABLE posts ALTER COLUMN {col} DROP NOT NULL'
                    ))
                    db.session.commit()
                    print(f'posts.{col} is now nullable.')
                except Exception as e:
                    db.session.rollback()
                    if 'already' in str(e).lower() or 'null' in str(e).lower():
                        print(f'posts.{col} already nullable or unchanged, skip.')
                    else:
                        print(f'Error altering {col}: {e}')
        else:
            print(f'Dialect {dialect}: no ALTER needed (SQLite allows NULL by default).')
    print('Done.')

if __name__ == '__main__':
    run()
