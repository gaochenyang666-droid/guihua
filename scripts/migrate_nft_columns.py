#!/usr/bin/env python3
"""为 posts 表添加 NFT 铸造相关字段（仅需在已有数据库上运行一次）。
在项目根目录执行：python scripts/migrate_nft_columns.py
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
        for col, sql in [
            ('nft_token_id', 'ALTER TABLE posts ADD COLUMN nft_token_id BIGINT'),
            ('nft_tx_hash', 'ALTER TABLE posts ADD COLUMN nft_tx_hash VARCHAR(66)'),
        ]:
            try:
                db.session.execute(text(sql))
                db.session.commit()
                print(f'Added column: {col}')
            except Exception as e:
                db.session.rollback()
                if 'duplicate' in str(e).lower() or 'already exists' in str(e).lower():
                    print(f'Column {col} already exists, skip.')
                else:
                    print(f'Error adding {col}: {e}')
    print('Done.')

if __name__ == '__main__':
    run()
