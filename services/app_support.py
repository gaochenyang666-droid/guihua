import os
import time
from datetime import datetime, timezone


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def humanize_verify_error(message):
    raw = (message or '').strip()
    if not raw:
        return '链上校验失败，请稍后重试'
    low = raw.lower()
    if 'invalid transaction hash format' in low:
        return '交易哈希格式不正确'
    if 'transaction hash already used' in low:
        return '该交易哈希已被使用'
    if 'transaction not found on chain' in low:
        return '链上未找到该交易，请稍后重试'
    if 'transaction needs at least' in low:
        return '交易确认中，请稍后重试'
    if 'transaction failed on chain' in low:
        return '链上交易执行失败'
    if 'sender mismatch' in low:
        return '付款钱包与当前登录钱包不一致'
    if 'not a usdt transfer to platform' in low:
        return '未检测到向目标地址的 USDT 转账'
    if 'insufficient usdt' in low or 'insufficient fee' in low:
        return '支付金额不足'
    if 'incorrect recipient' in low:
        return '收款地址不正确'
    if 'platform receive address not configured' in low:
        return '平台收款地址未配置'
    if 'user address not bound' in low:
        return '当前账号未绑定钱包地址'
    if 'verification process failed' in low or 'could not get latest block' in low:
        return '链上校验失败，请稍后重试'
    return raw


def is_post_permanent(post_obj):
    if not post_obj:
        return False
    tx_hash = getattr(post_obj, 'tx_hash', None)
    ipfs_cid = getattr(post_obj, 'ipfs_cid', None)
    is_on_chain = bool(getattr(post_obj, 'is_on_chain', False))
    post_type = int(getattr(post_obj, 'post_type', 0) or 0)
    return bool(tx_hash or ipfs_cid or is_on_chain or post_type == 1)


def tip_amount_to_usdt_str(raw_amount, decimals):
    try:
        value = int(raw_amount or 0)
    except Exception:
        value = 0
    scale = float(10 ** int(decimals or 18))
    return round(value / scale, 4)


def compute_asset_version(root_dir, override=''):
    override = (override or '').strip()
    if override:
        return override
    candidates = [
        os.path.join(root_dir, 'static', 'style.css'),
        os.path.join(root_dir, 'static', 'common.js'),
        os.path.join(root_dir, 'static', 'toast.js'),
        os.path.join(root_dir, 'static', 'index.js'),
    ]
    latest_mtime = 0
    for path in candidates:
        try:
            latest_mtime = max(latest_mtime, int(os.path.getmtime(path)))
        except Exception:
            continue
    return str(latest_mtime or int(time.time()))


def load_text_file(path):
    if not path:
        return ''
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            return fh.read().strip()
    except Exception:
        return ''
