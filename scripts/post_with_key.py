#!/usr/bin/env python3
"""用本文件夹内的 BSC 私钥发一帖（支付 0.001 BNB 后调用发帖接口）。
私钥来源（按顺序）：环境变量 WALLET_PRIVATE_KEY、wallet_key.txt、bsc_key.txt。
用法：在项目根目录执行（确保已配置 RECEIVE_ADDRESS 与 POST_FEE）：
  python3 scripts/post_with_key.py
  API_BASE=http://127.0.0.1:5001 python3 scripts/post_with_key.py
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
os.chdir(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv()

def load_wallet_key():
    key = os.environ.get('WALLET_PRIVATE_KEY', '').strip()
    if key:
        return key
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    for name in ('wallet_key.txt', 'bsc_key.txt'):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            with open(path, 'r') as f:
                key = (f.readline() or '').strip()
            if key:
                return key
    return None

def main():
    key = load_wallet_key()
    if not key:
        print("未找到 BSC 私钥。请任选其一：")
        print("  1. 在 .env 中设置 WALLET_PRIVATE_KEY=0x...")
        print("  2. 在项目根目录创建 wallet_key.txt 或 bsc_key.txt，第一行为私钥（0x 开头）")
        return 1

    from eth_account import Account
    from eth_account.messages import encode_defunct
    from web3 import Web3
    from web3.middleware.geth_poa import geth_poa_middleware
    import requests

    account = Account.from_key(key)
    address = account.address
    api_base = os.environ.get('API_BASE', 'http://127.0.0.1:5001').rstrip('/')

    print("钱包地址:", address)
    print("API:", api_base)

    # 1. Nonce
    r = requests.get(f"{api_base}/api/auth/nonce", params={"address": address}, timeout=10)
    if r.status_code != 200:
        print("获取 nonce 失败:", r.status_code, r.text[:200])
        return 1
    nonce = r.json().get("nonce")
    if not nonce:
        print("nonce 为空:", r.json())
        return 1
    message = f"Sign this message to login: {nonce}"
    signed = account.sign_message(encode_defunct(text=message))

    # 2. Login
    r = requests.post(
        f"{api_base}/api/auth/verify",
        json={"address": address, "signature": signed.signature.hex(), "message": message},
        timeout=10,
    )
    if r.status_code != 200:
        print("登录失败:", r.status_code, r.text[:200])
        return 1
    token = r.json().get("token")
    if not token:
        print("登录返回无 token:", r.json())
        return 1
    print("登录成功")

    # 3. Fee config
    r = requests.get(f"{api_base}/api/config/fees", timeout=10)
    if r.status_code != 200:
        print("获取 fees 失败:", r.status_code, r.text[:200])
        return 1
    cfg = r.json()
    receive_addr = cfg.get("receive_address")
    fee_wei_str = cfg.get("fee")
    chain_id = cfg.get("chain_id", 56)
    if not receive_addr or fee_wei_str is None:
        print("fees 缺少 receive_address 或 fee:", cfg)
        return 1
    fee_wei = int(fee_wei_str)
    print("发帖费:", fee_wei, "Wei, 收款:", receive_addr[:20], "...")

    # 4. 发送支付交易（使用当前 RPC 的 chain_id，与 API 返回可能不同，如测试网 97 vs 主网 56）
    from app import app, get_working_web3
    with app.app_context():
        w3 = get_working_web3()
    if not w3.is_connected():
        print("无法连接 BSC RPC，请检查网络或 BSC_RPC_URL")
        return 1
    chain_id_actual = w3.eth.chain_id
    print("当前 RPC chain_id:", chain_id_actual)

    nonce_tx = w3.eth.get_transaction_count(address)
    gas_price = w3.eth.gas_price
    tx = {
        "nonce": nonce_tx,
        "chainId": chain_id_actual,
        "to": Web3.to_checksum_address(receive_addr),
        "value": fee_wei,
        "gas": 21000,
        "gasPrice": gas_price,
    }
    signed_tx = account.sign_transaction(tx)
    tx_hash_hex = w3.eth.send_raw_transaction(signed_tx.rawTransaction).hex()
    print("支付交易已发送:", tx_hash_hex[:20], "...")

    # 5. 等待确认（主网出块约 3s，捕获 TransactionNotFound 后重试）
    import time
    receipt = None
    try:
        from web3.exceptions import TransactionNotFound
    except ImportError:
        TransactionNotFound = Exception
    for _ in range(90):
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash_hex)
        except TransactionNotFound:
            receipt = None
        if receipt and receipt.get("status") == 1:
            break
        time.sleep(2)
    if not receipt or receipt.get("status") != 1:
        print("交易未确认或失败，请稍后在链上查看:", tx_hash_hex)
        return 1
    print("交易已确认")

    # 6. 发帖
    title = "脚本测试发帖"
    content = "<p>这是一条由 scripts/post_with_key.py 使用本地 key 发出的测试帖。</p>"
    r = requests.post(
        f"{api_base}/api/posts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={
            "title": title,
            "content": content,
            "tx_hash": tx_hash_hex,
            "region": "其他",
            "cover_image": "",
            "images": [],
        },
        timeout=30,
    )
    if r.status_code not in (200, 201):
        print("发帖失败:", r.status_code, r.text[:300])
        return 1
    post = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if "post" in post:
        post = post["post"]
    print("发帖成功! post_id:", post.get("id"), "title:", post.get("title"))
    return 0

if __name__ == "__main__":
    sys.exit(main())
