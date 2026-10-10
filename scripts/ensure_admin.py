#!/usr/bin/env python3
"""在数据库中创建或更新管理员账号。

用户名与密码从环境变量读取，禁止在代码中硬编码：
  ADMIN_USERNAME  管理员用户名（必填）
  ADMIN_PASSWORD  管理员密码（必填）

用法：
  ADMIN_USERNAME=xxx ADMIN_PASSWORD=yyy python3 scripts/ensure_admin.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def main():
    from app import app, db
    from app import User

    username = (os.environ.get('ADMIN_USERNAME') or '').strip()
    password = os.environ.get('ADMIN_PASSWORD') or ''
    if not username or not password:
        print('错误：请先设置环境变量 ADMIN_USERNAME 与 ADMIN_PASSWORD', file=sys.stderr)
        return 1

    with app.app_context():
        u = User.query.filter_by(username=username).first()
        if not u:
            u = User(
                username=username,
                nickname=username,
                is_admin=True,
                avatar='👤',
            )
            u.set_password(password)
            db.session.add(u)
            db.session.commit()
            print('已创建管理员账号 %s' % username)
        else:
            u.set_password(password)
            u.is_admin = True
            db.session.commit()
            print('已重置 %s 的密码' % username)
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
