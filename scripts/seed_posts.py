#!/usr/bin/env python3
"""恢复种子数据：若没有「华先生访问记」则插入，并确保 Admin 存在。
帖子被清空后可在项目根目录执行：python scripts/seed_posts.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def main():
    from app import app, db, init_db_data, Post
    with app.app_context():
        before = Post.query.count()
        print(f"当前帖子数: {before}")
        init_db_data()
        after = Post.query.count()
        print(f"执行后帖子数: {after}")
        if after > before:
            print("已恢复种子帖（华先生访问记）。")
        else:
            print("未新增帖子（可能已存在或插入失败，请查看上方日志）。")

if __name__ == '__main__':
    main()
