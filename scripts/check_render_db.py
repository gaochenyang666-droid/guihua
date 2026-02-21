#!/usr/bin/env python3
"""在 Render Shell 里检查当前数据库连接和表数据量。
在项目根目录执行：python3 scripts/check_render_db.py
会读取环境变量 DATABASE_URL（Render 会注入），并输出各表行数。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def main():
    url = os.environ.get('DATABASE_URL', '')
    if not url:
        print("未设置 DATABASE_URL，将使用默认 SQLite。")
    else:
        # 不打印密码，只显示类型和 host
        if url.startswith('postgresql'):
            print("数据库类型: PostgreSQL (Render 托管)")
            if '@' in url and ':' in url:
                try:
                    part = url.split('@')[1].split('/')[0]
                    print("连接目标: ...@" + part)
                except Exception:
                    pass
        else:
            print("数据库类型: SQLite")
    print("-" * 40)

    from app import app, db
    from sqlalchemy import text

    with app.app_context():
        try:
            db.session.execute(text("SELECT 1"))
        except Exception as e:
            print("连接失败:", e)
            return

        from app import User, Post, Comment, Tip
        for name, model in [('users', User), ('posts', Post), ('comments', Comment), ('tips', Tip)]:
            try:
                n = model.query.count()
                print(f"  {name}: {n} 行")
            except Exception as e:
                print(f"  {name}: 错误 - {e}")

        print("-" * 40)
        print("若 posts=0，可执行: python3 scripts/seed_posts.py 恢复种子帖。")

if __name__ == '__main__':
    main()
