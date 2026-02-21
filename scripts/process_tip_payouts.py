#!/usr/bin/env python3
"""处理未打款的打赏：从平台钱包将 93% BNB 转给作者。可被 cron 定期执行。
用法：在项目根目录执行
  python scripts/process_tip_payouts.py
或
  python -c "from scripts.process_tip_payouts import run; run()"
需配置 .env 中的 PLATFORM_PRIVATE_KEY（平台热钱包私钥）、RECEIVE_ADDRESS、DATABASE_URL 等。
"""
import os
import sys

# 确保项目根在 path 中
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def run():
    from app import app, process_pending_tip_payouts
    with app.app_context():
        total, sent, failed = process_pending_tip_payouts()
    print(f"Processed: {total}, sent: {sent}, failed: {failed}")
    return total, sent, failed

if __name__ == '__main__':
    run()
