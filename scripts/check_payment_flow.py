#!/usr/bin/env python3
"""支付流程自检：不发真实交易，只测校验逻辑与配置。
在项目根目录执行：python3 scripts/check_payment_flow.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def main():
    from app import app, verify_transaction

    errors = []
    with app.app_context():
        # 1. get_fees 逻辑：有 RECEIVE_ADDRESS 时应有 fee/chain_id
        addr = app.config.get('BSC', {}).get('RECEIVE_ADDRESS')
        fee = app.config.get('BSC', {}).get('POST_FEE')
        chain_id = app.config.get('BSC', {}).get('CHAIN_ID')
        if addr:
            if fee is not None and chain_id is not None:
                print("[OK] BSC RECEIVE_ADDRESS + POST_FEE + CHAIN_ID 已配置")
            else:
                errors.append("RECEIVE_ADDRESS 已配置但 POST_FEE 或 CHAIN_ID 缺失")
        else:
            print("[--] RECEIVE_ADDRESS 未配置（生产需配置）")

        # 2. verify_transaction：user_address 为空
        ok, msg = verify_transaction("0x" + "a" * 64, None, expected_recipient="0x123", min_amount=0)
        if not ok and "address" in msg.lower():
            print("[OK] verify_transaction(user_address=None) -> False, msg 含 address")
        else:
            errors.append("verify_transaction(None) 期望 False: ok=%s msg=%s" % (ok, msg))

        # 3. verify_transaction：非法 tx_hash 格式
        ok, msg = verify_transaction(
            "invalid",
            "0x1234567890123456789012345678901234567890",
            expected_recipient="0x123",
            min_amount=0,
        )
        if not ok and "format" in msg.lower():
            print("[OK] verify_transaction(非法 hash 格式) -> False")
        else:
            errors.append("verify_transaction(非法格式) 期望 False: ok=%s msg=%s" % (ok, msg))

        # 4. expected_recipient 显式传空时应收款地址未配置
        save_addr = app.config["BSC"].get("RECEIVE_ADDRESS")
        try:
            app.config["BSC"]["RECEIVE_ADDRESS"] = None
            ok, msg = verify_transaction(
                "0x" + "b" * 64,
                "0x1234567890123456789012345678901234567890",
                expected_recipient=None,
                min_amount=0,
            )
            if not ok and ("receive" in msg.lower() or "configured" in msg.lower() or "not configured" in msg.lower()):
                print("[OK] verify_transaction(收款地址未配置) -> False")
            else:
                errors.append("verify_transaction(无收款地址) 期望 False: ok=%s msg=%s" % (ok, msg[:50]))
        finally:
            app.config["BSC"]["RECEIVE_ADDRESS"] = save_addr

    if errors:
        print("\n[FAIL] %d 项异常:" % len(errors))
        for e in errors:
            print("  -", e)
        return 1
    print("\n[PASS] 支付流程自检通过。")
    return 0

if __name__ == "__main__":
    sys.exit(main())
