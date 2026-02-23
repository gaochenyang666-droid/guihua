# 区块链服务层：BSC 交易校验、USDT 打款、NFT 铸造
import os
import re
import time
import threading
import requests
from web3 import Web3
try:
    from web3.middleware.geth_poa import geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware

from flask import current_app
from extensions import db
from models import Post, UsedTransaction, Tip

_TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'

_w3_cache = None


def get_working_web3():
    global _w3_cache
    rpc_list = current_app.config.get('BSC_RPC_LIST') or [current_app.config['BSC']['RPC_URL']]
    if _w3_cache and _w3_cache.is_connected():
        return _w3_cache
    for rpc in rpc_list:
        try:
            provider = Web3(Web3.HTTPProvider(rpc))
            provider.middleware_onion.inject(geth_poa_middleware, layer=0)
            if provider.is_connected():
                _w3_cache = provider
                return provider
        except Exception as e:
            continue
    provider = Web3(Web3.HTTPProvider(rpc_list[0]))
    provider.middleware_onion.inject(geth_poa_middleware, layer=0)
    return provider


def get_bnb_price_usd():
    try:
        r = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT', timeout=5)
        if r.ok:
            data = r.json()
            return float(data.get('price', 0)) or None
    except Exception as e:
        print(f"BNB price fetch error: {e}")
    return None


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


def _encode_usdt_transfer(to_address, amount_raw):
    try:
        from eth_abi import encode
        amount_raw = int(amount_raw)
        if amount_raw < 0 or amount_raw > (1 << 256) - 1:
            return None
        selector = bytes.fromhex('a9059cbb')
        encoded = encode(['address', 'uint256'], [Web3.to_checksum_address(to_address), amount_raw])
        return '0x' + (selector + encoded).hex()
    except (ImportError, TypeError, ValueError):
        return None


def try_send_tip_payout_raw(to_address, amount_raw):
    pk = os.environ.get('PLATFORM_PRIVATE_KEY')
    if not pk:
        return ('no_key', None)
    if not to_address or not Web3.is_address(to_address) or amount_raw <= 0:
        return ('failed', 'Invalid address or amount')
    usdt_contract = current_app.config['BSC'].get('USDT_CONTRACT_ADDRESS')
    if not usdt_contract:
        return ('failed', 'USDT contract not configured')
    data_hex = _encode_usdt_transfer(to_address, amount_raw)
    if not data_hex:
        return ('failed', 'eth_abi not available')
    try:
        from eth_account import Account
        w3_conn = get_working_web3()
        account = Account.from_key(pk)
        platform_address = account.address
        if platform_address.lower() != (current_app.config['BSC'].get('RECEIVE_ADDRESS') or '').lower():
            return ('failed', 'Platform key does not match RECEIVE_ADDRESS')
        balance_bnb = w3_conn.eth.get_balance(platform_address)
        if balance_bnb < Web3.to_wei(0.0005, 'ether'):
            return ('failed', '平台钱包 BNB 不足')
        nonce = w3_conn.eth.get_transaction_count(platform_address)
        base_gas = w3_conn.eth.gas_price
        gas_price = min(int(base_gas * 1.1), Web3.to_wei(20, 'gwei'))
        tx = {
            'nonce': nonce,
            'chainId': current_app.config['BSC']['CHAIN_ID'],
            'to': Web3.to_checksum_address(usdt_contract),
            'value': 0,
            'data': data_hex,
            'gas': 100000,
            'gasPrice': gas_price
        }
        signed = account.sign_transaction(tx)
        tx_hash = w3_conn.eth.send_raw_transaction(signed.raw_transaction)
        return ('sent', tx_hash.hex())
    except Exception as e:
        return ('failed', str(e)[:500])


def try_send_tip_payout(tip, author_amount_raw):
    if not tip.recipient:
        return ('no_address', None)
    tip_full = int(tip.amount)
    if author_amount_raw <= 0 or author_amount_raw > tip_full:
        return ('failed', 'Invalid payout amount')
    to_address = (tip.recipient.wallet_address or tip.recipient.address or '').strip()
    return try_send_tip_payout_raw(to_address, author_amount_raw)


def process_pending_tip_payouts():
    fee_percent = current_app.config.get('TIP_PLATFORM_FEE_PERCENT', 7)
    if not os.environ.get('PLATFORM_PRIVATE_KEY'):
        return (0, 0, 0)
    tips = Tip.query.filter(
        Tip.payout_tx_hash.is_(None),
        Tip.payout_status.in_(('pending', 'failed', 'no_address'))
    ).all()
    sent, failed = 0, 0
    for tip in tips:
        full_raw = int(tip.amount)
        author_raw = (full_raw * (100 - fee_percent)) // 100
        status, result = try_send_tip_payout(tip, author_raw)
        tip.payout_status = status
        if status == 'sent':
            tip.payout_tx_hash = result
            tip.payout_error = None
            sent += 1
        elif status == 'failed':
            tip.payout_error = result
            failed += 1
        elif status == 'no_address':
            tip.payout_error = tip.payout_error or 'Author has no wallet address'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return (len(tips), sent, failed)


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


def mint_nft(to_address, token_uri):
    import os
    pk = os.environ.get('ADMIN_PRIVATE_KEY')
    nft_contract = os.environ.get('NFT_CONTRACT_ADDRESS')
    if not pk or not nft_contract or not Web3.is_address(to_address):
        return None, "NFT mint not configured or invalid to_address"
    NFT_MINT_ABI = [{
        "inputs": [{"name": "to", "type": "address"}, {"name": "tokenURI", "type": "string"}],
        "name": "mint",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "nonpayable",
        "type": "function"
    }]
    try:
        from eth_account import Account
        w3_conn = get_working_web3()
        account = Account.from_key(pk)
        contract = w3_conn.eth.contract(
            address=Web3.to_checksum_address(nft_contract),
            abi=NFT_MINT_ABI
        )
        gas_price = min(int(w3_conn.eth.gas_price * 1.1), Web3.to_wei(20, 'gwei'))
        tx = contract.functions.mint(Web3.to_checksum_address(to_address), token_uri).build_transaction({
            'from': account.address,
            'nonce': w3_conn.eth.get_transaction_count(account.address),
            'gas': 200000,
            'gasPrice': gas_price,
            'chainId': current_app.config['BSC']['CHAIN_ID']
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3_conn.eth.send_raw_transaction(signed.raw_transaction)
        for _ in range(30):
            time.sleep(2)
            receipt = w3_conn.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                break
        if not receipt or receipt['status'] != 1:
            return None, "Mint tx failed or timeout"
        token_id = None
        for log in receipt.get('logs', []):
            topics = log.get('topics', [])
            if len(topics) >= 4:
                try:
                    token_id = int(topics[3].hex(), 16)
                    break
                except (IndexError, ValueError, AttributeError):
                    pass
        return token_id, tx_hash.hex()
    except Exception as e:
        return None, str(e)[:300]


def async_mint_nft_for_post(post_id):
    from services.storage import build_and_upload_nft_metadata
    app = current_app._get_current_object()
    def _run():
        with app.app_context():
            try:
                post = Post.query.get(post_id)
                if not post or not post.ipfs_cid or not post.author:
                    return
                to_address = (post.author.wallet_address or post.author.address or '').strip()
                if not to_address or not Web3.is_address(to_address):
                    return
                metadata_tx_id = build_and_upload_nft_metadata(post)
                if not metadata_tx_id:
                    return
                token_uri = f"https://arweave.net/{metadata_tx_id}"
                token_id, tx_hash_or_err = mint_nft(to_address, token_uri)
                if token_id is not None and tx_hash_or_err:
                    post.nft_token_id = token_id
                    post.nft_tx_hash = tx_hash_or_err
                    db.session.commit()
            except Exception as e:
                print(f"async_mint_nft_for_post error: {e}")
    threading.Thread(target=_run, daemon=True).start()
