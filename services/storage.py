# 存储服务层：图片上传（ImgBB/本地）、Arweave 永存、IPFS 备份
import os
import json
import time
import hashlib
import secrets
import base64
import requests
from flask import current_app

try:
    from arweave.arweave_lib import Wallet, Transaction
except ImportError:
    Wallet = Transaction = None

_REQUESTS_TIMEOUT = 30
IMGBB_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
IMGBB_ALLOWED_MIMES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
IMGBB_MAX_SIZE = 2 * 1024 * 1024


def _local_upload_fallback(file):
    basedir = current_app.root_path
    upload_dir = os.path.join(basedir, 'static', 'uploads')
    try:
        os.makedirs(upload_dir, exist_ok=True)
    except OSError as e:
        return (None, f"无法创建上传目录: {e}")
    fn = getattr(file, 'filename', None) or 'image.jpg'
    ext = (fn.rsplit('.', 1)[-1] if '.' in fn else 'jpg').lower()
    if ext not in IMGBB_ALLOWED_EXTENSIONS:
        ext = 'jpg'
    safe_name = secrets.token_hex(8) + '.' + ext
    path = os.path.join(upload_dir, safe_name)
    try:
        file.seek(0)
        with open(path, 'wb') as f:
            f.write(file.read())
        return (f'/static/uploads/{safe_name}', None)
    except Exception as e:
        return (None, str(e)[:100])


def upload_to_imgbb(file):
    """返回 (url, error_msg)。无 ImgBB 时走本地上传。"""
    api_key = (current_app.config.get('IMGBB_API_KEY') or '').strip()
    if not api_key:
        return _local_upload_fallback(file)
    if not file or not getattr(file, 'filename', None):
        return (None, "未选择文件")
    filename = (file.filename or '').lower()
    ext = filename.rsplit('.', 1)[-1] if '.' in filename else ''
    if ext not in IMGBB_ALLOWED_EXTENSIONS:
        return (None, f"仅支持 png/jpg/jpeg/gif/webp，当前: {filename or '无扩展名'}")
    content_type = (getattr(file, 'content_type', None) or '').strip().lower()
    if content_type and content_type not in IMGBB_ALLOWED_MIMES:
        return (None, f"图片类型不允许: {content_type}")
    try:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > IMGBB_MAX_SIZE:
            return (None, f"图片超过 2MB（当前 {size // (1024*1024)}MB）")
        img_b64 = base64.b64encode(file.read()).decode('utf-8')
        payload = {"key": api_key, "image": img_b64}
        response = requests.post("https://api.imgbb.com/1/upload", data=payload, timeout=_REQUESTS_TIMEOUT)
        if response.status_code == 200:
            json_resp = response.json()
            if isinstance(json_resp, dict) and json_resp.get('data') and json_resp['data'].get('url'):
                return (json_resp['data']['url'], None)
        try:
            err_info = response.json() if response.text else {}
            msg = err_info.get('error', {}).get('message', response.text[:100] if response.text else f"HTTP {response.status_code}")
        except Exception:
            msg = f"HTTP {response.status_code}"
        return (None, f"ImgBB 上传失败: {msg}")
    except requests.Timeout:
        return (None, "上传超时，请重试")
    except Exception as e:
        return (None, str(e)[:150])


def upload_to_pinata(json_data):
    api_key = current_app.config.get('PINATA_API_KEY')
    secret = current_app.config.get('PINATA_SECRET_API_KEY')
    if not api_key or not secret:
        if current_app.config.get('DEBUG'):
            return 'Qm' + secrets.token_hex(22) + '(Mock)'
        return None
    url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
    headers = {"pinata_api_key": api_key, "pinata_secret_api_key": secret, "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=json_data, headers=headers, timeout=_REQUESTS_TIMEOUT)
        if response.status_code == 200:
            return response.json().get('IpfsHash')
        return None
    except Exception as e:
        print(f"Pinata Exception: {e}")
        return None


def get_arweave_wallet():
    if not Wallet or not Transaction:
        return None
    key_data_str = os.environ.get('AR_KEY_DATA')
    if key_data_str:
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmp:
                tmp.write(key_data_str)
                tmp_path = tmp.name
            wallet = Wallet(tmp_path)
            wallet.api_url = current_app.config.get('ARWEAVE_GATEWAY', 'https://arweave.net')
            return wallet
        except Exception as e:
            print(f"Error loading wallet from AR_KEY_DATA: {e}")
            return None
        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
    key_file_env = os.environ.get('AR_KEY_FILE')
    if key_file_env and os.path.exists(key_file_env):
        try:
            wallet = Wallet(key_file_env)
            wallet.api_url = current_app.config.get('ARWEAVE_GATEWAY', 'https://arweave.net')
            return wallet
        except Exception as e:
            print(f"Error loading wallet from AR_KEY_FILE: {e}")
    for filename in ['ar_key.json', 'arweave-key.json']:
        if os.path.exists(filename):
            try:
                wallet = Wallet(filename)
                wallet.api_url = current_app.config.get('ARWEAVE_GATEWAY', 'https://arweave.net')
                return wallet
            except Exception as e:
                print(f"Error loading wallet from {filename}: {e}")
    return None


def upload_to_arweave_native(data):
    if not Wallet or not Transaction:
        return (None, "arweave library not installed")
    wallet = get_arweave_wallet()
    if not wallet:
        msg = "Arweave 钱包未配置"
        if current_app.config.get('DEBUG'):
            return ('ArMock_' + secrets.token_hex(20), None)
        return (None, msg)
    try:
        json_str = json.dumps(data)
        transaction = Transaction(wallet, data=json_str)
        transaction.add_tag('Content-Type', 'application/json')
        transaction.add_tag('App-Name', 'GuiHua-Web3')
        transaction.add_tag('App-Version', '1.0.0')
        transaction.add_tag('Unix-Time', str(int(time.time())))
        transaction.sign()
        transaction.send()
        return (transaction.id, None)
    except Exception as e:
        return (None, f"Arweave 上传异常: {str(e)[:200]}")


def upload_to_pinata_with_reason(json_data):
    api_key = current_app.config.get('PINATA_API_KEY')
    secret = current_app.config.get('PINATA_SECRET_API_KEY')
    if not api_key or not secret:
        if current_app.config.get('DEBUG'):
            return ('Qm' + secrets.token_hex(22) + '(Mock)', None)
        return (None, "Pinata 未配置")
    url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
    headers = {"pinata_api_key": api_key, "pinata_secret_api_key": secret, "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=json_data, headers=headers, timeout=_REQUESTS_TIMEOUT)
        if response.status_code == 200:
            cid = response.json().get('IpfsHash')
            if cid:
                return (cid, None)
            return (None, "Pinata 返回无 IpfsHash")
        return (None, f"Pinata HTTP {response.status_code}: {response.text[:150]}")
    except Exception as e:
        return (None, str(e)[:150])


def upload_to_arweave_with_retry(data, retries=3):
    last_error = None
    for attempt in range(max(1, retries + 1)):
        tx_id, err = upload_to_arweave_native(data)
        if tx_id:
            return (tx_id, 'arweave', None)
        last_error = err
        if attempt < retries:
            time.sleep(3)
    if current_app.config.get('PINATA_API_KEY') and current_app.config.get('PINATA_SECRET_API_KEY'):
        for attempt in range(2):
            cid, err = upload_to_pinata_with_reason(data)
            if cid:
                return (cid, 'ipfs', None)
            last_error = err
            if attempt < 1:
                time.sleep(2)
    else:
        if not last_error:
            last_error = "Pinata 未配置，无法兜底"
    return (None, None, last_error)


def build_and_upload_nft_metadata(post):
    try:
        content_hash = hashlib.sha256((post.content or '').encode('utf-8')).hexdigest()
        external_url = f"https://arweave.net/{post.ipfs_cid}" if post.ipfs_cid else ""
        metadata = {
            "name": (post.title or "")[:200],
            "description": (post.content or "").replace("<", " ").replace(">", " ")[:500],
            "content_hash": content_hash,
            "author_id": post.author_id,
            "image": post.cover_image or "",
            "external_url": external_url,
            "platform": "GuiHua Web3",
            "post_id": post.id,
            "created_at": post.created_at.isoformat() if post.created_at else ""
        }
        tx_id, _ = upload_to_arweave_native(metadata)
        return tx_id
    except Exception as e:
        print(f"NFT metadata upload error: {e}")
        return None
