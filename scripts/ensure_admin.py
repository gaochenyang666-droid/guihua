#!/usr/bin/env python3
"""在数据库中确保管理员账号 siteadmin 存在（密码 CHANGE_ME_ON_DEPLOY）。若不存在则创建，若存在则重置密码。
用法：在项目根目录或 Render Shell 中执行
  python3 scripts/ensure_admin.py
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

    with app.app_context():
        u = User.query.filter_by(username='siteadmin').first()
        if not u:
            u = User(
                username='siteadmin',
                nickname='siteadmin',
                is_admin=True,
                avatar='👤',
            )
            u.set_password('CHANGE_ME_ON_DEPLOY')
            db.session.add(u)
            db.session.commit()
            print('已创建管理员账号 siteadmin，密码：CHANGE_ME_ON_DEPLOY')
        else:
            u.set_password('CHANGE_ME_ON_DEPLOY')
            u.is_admin = True
            db.session.commit()
            print('已重置 siteadmin 密码为：CHANGE_ME_ON_DEPLOY')
    return 0

if __name__ == '__main__':
    sys.exit(main() or 0)
