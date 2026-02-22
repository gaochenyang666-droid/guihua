#!/usr/bin/env python3
"""自动打款：对可提现余额 >= 10 USDT 且已绑定钱包的作者，从平台钱包转 USDT 到其绑定钱包。
用法：在项目根目录执行
  python scripts/process_withdrawals.py
或配合 cron 定时执行（如每天一次）：
  0 2 * * * cd /path/to/guihua.online.py && python scripts/process_withdrawals.py
需配置 .env 中的 PLATFORM_PRIVATE_KEY、RECEIVE_ADDRESS、USDT 合约等。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def run():
    from app import app, process_auto_withdrawals
    with app.app_context():
        processed, sent, failed = process_auto_withdrawals()
    print(f"Auto withdrawals: processed={processed}, sent={sent}, failed={failed}")
    return processed, sent, failed

if __name__ == '__main__':
    run()
    sys.exit(0)
