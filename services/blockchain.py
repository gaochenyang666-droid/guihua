# 区块链服务层：BSC 交易校验
import re
import time
import requests
from web3 import Web3
try:
    from web3.middleware.geth_poa import geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware

from flask import current_app
from models import Post, UsedTransaction

_TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

def get_usdt_per_cny():
    try:
        r = requests.get('https://api.exchangerate-api.com/v4/latest/USD', timeout=5)
        if r.ok:
            data = r.json()
            cny_per_usd = float((data.get('rates') or {}).get('CNY', 0) or 0)
            if cny_per_usd > 0:
                return 1.0 / cny_per_usd
    except Exception as e:
        print(f"CNY/USD rate fetch error: {e}")
    return None


def get_post_fee_usdt_raw():
    decimals = current_app.config['BSC']['USDT_DECIMALS']
    cny = current_app.config['BSC']['POST_FEE_CNY']
    usdt_per_cny = get_usdt_per_cny()
    if usdt_per_cny and usdt_per_cny > 0:
        fee_usdt = cny * usdt_per_cny
    else:
        fee_usdt = current_app.config['BSC']['POST_FEE_USDT_FALLBACK']
    return int(fee_usdt * (10 ** decimals))


def _addr_to_topic(addr):
    a = (addr or '').lower().replace('0x', '')
    return '0x' + a.zfill(64)


def verify_transaction(tx_hash, user_address, expected_recipient=None, min_amount=None, payment_type='bnb'):
    if not user_address:
        return False, 'User address not bound'
    if not expected_recipient:
        expected_recipient = current_app.config['BSC'].get('RECEIVE_ADDRESS')
    if not expected_recipient and payment_type == 'usdt':
        return False, 'Platform receive address not configured'
    if min_amount is None:
        if payment_type == 'usdt':
            min_amount = get_post_fee_usdt_raw()
        else:
            min_amount = int(Web3.to_wei(0.0001, 'ether'))
    tx_confirmations = current_app.config.get('TX_CONFIRMATIONS_NEEDED', 2)
    rpc_list = current_app.config.get('BSC_RPC_LIST') or [current_app.config['BSC']['RPC_URL']]

    if not re.match(r"^0x[a-fA-F0-9]{64}$", tx_hash):
        return False, 'Invalid transaction hash format'
    if Post.query.filter_by(tx_hash=tx_hash).first():
        return False, 'Transaction hash already used'
    if UsedTransaction.query.filter_by(tx_hash=tx_hash).first():
        return False, 'Transaction hash already used (history)'

    tx, receipt = None, None
    for attempt in range(5):
        for rpc in rpc_list:
            try:
                provider = Web3(Web3.HTTPProvider(rpc))
                provider.middleware_onion.inject(geth_poa_middleware, layer=0)
                tx = provider.eth.get_transaction(tx_hash)
                receipt = provider.eth.get_transaction_receipt(tx_hash)
                if tx and receipt:
                    break
            except Exception:
                continue
        if tx and receipt:
            break
        time.sleep(2)

    if not tx or not receipt:
        return False, 'Transaction not found on chain (timeout)'

    current_block = receipt.get('blockNumber')
    if current_block is not None:
        latest = None
        for rpc in rpc_list:
            try:
                provider = Web3(Web3.HTTPProvider(rpc))
                provider.middleware_onion.inject(geth_poa_middleware, layer=0)
                latest = provider.eth.block_number
                break
            except Exception:
                continue
        if latest is None:
            return False, 'Could not get latest block'
        if latest - current_block < tx_confirmations:
            return False, f'Transaction needs at least {tx_confirmations} block confirmations'

    try:
        if receipt['status'] != 1:
            return False, 'Transaction failed on chain'
        if tx['from'].lower() != user_address.lower():
            return False, 'Sender mismatch'

        if payment_type == 'usdt':
            usdt_contract = (current_app.config['BSC'].get('USDT_CONTRACT_ADDRESS') or '').lower()
            if not usdt_contract or tx['to'].lower() != usdt_contract:
                return False, 'Not a USDT transfer to platform'
            want_from = _addr_to_topic(user_address)
            want_to = _addr_to_topic(expected_recipient)
            amount_found = 0
            for log in receipt.get('logs', []):
                log_addr = log.get('address')
                log_addr = ('0x' + log_addr.hex()) if hasattr(log_addr, 'hex') else str(log_addr or '')
                if not log_addr.startswith('0x'):
                    log_addr = '0x' + log_addr
                if log_addr.lower() != usdt_contract.lower():
                    continue
                topics = log.get('topics') or []
                if len(topics) < 3:
                    continue
                t0 = topics[0].hex() if hasattr(topics[0], 'hex') else str(topics[0])
                if (t0 if t0.startswith('0x') else '0x' + t0).lower() != _TRANSFER_TOPIC:
                    continue
                t1 = (topics[1].hex() if hasattr(topics[1], 'hex') else str(topics[1])).lower()
                if not t1.startswith('0x'):
                    t1 = '0x' + t1
                t2 = (topics[2].hex() if hasattr(topics[2], 'hex') else str(topics[2])).lower()
                if not t2.startswith('0x'):
                    t2 = '0x' + t2
                if t1 != want_from or t2 != want_to:
                    continue
                data = log.get('data') or b''
                if hasattr(data, 'hex'):
                    data = data.hex()
                if isinstance(data, bytes):
                    data = data.hex()
                if data.startswith('0x'):
                    data = data[2:]
                if len(data) >= 64:
                    amount_found = int(data[:64], 16)
                    break
            if amount_found < min_amount:
                return False, f'Insufficient USDT. Paid: {amount_found}, Expected: {min_amount}'
            return True, amount_found
        else:
            if not tx['to'] or tx['to'].lower() != expected_recipient.lower():
                return False, 'Incorrect recipient'
            if tx['value'] < min_amount:
                return False, 'Insufficient fee'
            return True, tx['value']
    except Exception as e:
        print(f"Verify Tx Error: {e}")
        return False, 'Verification process failed'
