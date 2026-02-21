import os
import re
import json
import hashlib
import secrets
import threading
import bleach
import requests
import base64
import random
import time
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, g, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from web3 import Web3
from web3.middleware.geth_poa import geth_poa_middleware
import arweave
from arweave.arweave_lib import Wallet, Transaction

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)

# ImgBB Configuration
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY')
if not IMGBB_API_KEY:
    print("Warning: IMGBB_API_KEY not set")

# Arweave Configuration
ARWEAVE_GATEWAY = 'https://arweave.net'

# Pinata (IPFS) Configuration (Legacy/Backup)
PINATA_API_KEY = os.environ.get('PINATA_API_KEY')
PINATA_SECRET_API_KEY = os.environ.get('PINATA_SECRET_API_KEY')

# Database Configuration（SQLite 建议用绝对路径，避免重启后工作目录变化导致数据“丢失”）
basedir = os.path.abspath(os.path.dirname(__file__))
_db_url = os.environ.get('DATABASE_URL', '').strip() or None
if _db_url and _db_url.startswith('sqlite:///') and not _db_url.startswith('sqlite:////'):
    # 相对路径如 sqlite:///guijing.db 转为基于项目目录的绝对路径，防止重启后 cwd 不同导致丢数据
    _rel = _db_url.replace('sqlite:///', '')
    if _rel and not os.path.isabs(_rel):
        _db_url = 'sqlite:///' + os.path.join(basedir, _rel)
if not _db_url:
    _db_url = 'sqlite:///' + os.path.join(basedir, 'guijing.db')
app.config['SQLALCHEMY_DATABASE_URI'] = _db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# timeout 仅用于 SQLite（防锁库）；PostgreSQL 不支持该 DSN 选项，否则会报 invalid connection option "timeout"
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'connect_args': {'timeout': 30} if _db_url.startswith('sqlite') else {}
}

# Persistent SECRET_KEY
secret_file = os.path.join(basedir, '.secret_key')
if os.path.exists(secret_file):
    with open(secret_file, 'r') as f:
        app.config['SECRET_KEY'] = f.read().strip()
else:
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY') or secrets.token_hex(32)
    try:
        with open(secret_file, 'w') as f:
            f.write(app.config['SECRET_KEY'])
    except:
        pass # In read-only envs, fallback to memory key (will reset on restart)

if not app.config['SECRET_KEY']:
    raise ValueError("No SECRET_KEY set for Flask application")

# BSC Mainnet Configuration (真实 BNB，请务必核对 RECEIVE_ADDRESS 与 POST_FEE)
BSC_RPC_LIST = [
    os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/'),
    'https://bsc-dataseed1.defibit.io/',
    'https://bsc-dataseed1.ninicoin.io/',
    'https://bsc.publicnode.com'
]

# 发帖费：动态为 1 USD 等值 BNB；取价失败则用 .env POST_FEE（BNB 单位）兜底
# 打赏平台抽成比例（7% 平台建设费，93% 给作者；打赏必须先打到平台钱包，再由平台转给作者）
TIP_PLATFORM_FEE_PERCENT = 7
POST_FEE_FALLBACK_BNB = os.environ.get('POST_FEE', '0.001')
app.config['BSC'] = {
    'RPC_URL': BSC_RPC_LIST[0],
    'CHAIN_ID': 56,
    'RECEIVE_ADDRESS': os.environ.get('RECEIVE_ADDRESS'),
    'POST_FEE': Web3.to_wei(POST_FEE_FALLBACK_BNB, 'ether')
}

def get_bnb_price_usd():
    """获取 BNB 美元价格（Binance 现货），失败返回 None。"""
    try:
        r = requests.get('https://api.binance.com/api/v3/ticker/price?symbol=BNBUSDT', timeout=5)
        if r.ok:
            data = r.json()
            return float(data.get('price', 0)) or None
    except Exception as e:
        print(f"BNB price fetch error: {e}")
    return None

def get_post_fee_wei():
    """发帖费（Wei）：1 USD 等值 BNB；取价失败时用环境变量 POST_FEE 兜底。"""
    price = get_bnb_price_usd()
    if price and price > 0:
        bnb_per_usd = 1.0 / price
        return int(Web3.to_wei(bnb_per_usd, 'ether'))
    return app.config['BSC']['POST_FEE']

db = SQLAlchemy(app)
w3 = Web3(Web3.HTTPProvider(app.config['BSC']['RPC_URL']))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

def get_working_web3():
    """Try to find a working RPC provider from the list"""
    # First try the default global w3
    if w3.is_connected():
        return w3
    
    # If default fails, try others
    print("Default RPC failed, trying backups...")
    for rpc in BSC_RPC_LIST:
        try:
            provider = Web3(Web3.HTTPProvider(rpc))
            provider.middleware_onion.inject(geth_poa_middleware, layer=0)
            if provider.is_connected():
                print(f"Connected to backup RPC: {rpc}")
                return provider
        except:
            continue
    return w3 # Return default even if failed, to let caller handle error

# 平台热钱包私钥（用于打赏自动打款：从平台钱包把 93% 转给作者）。不配置则只记账不自动转款
PLATFORM_PRIVATE_KEY = os.environ.get('PLATFORM_PRIVATE_KEY')

def try_send_tip_payout(tip, author_wei):
    """从平台钱包向作者地址转 author_wei（93% 部分）。返回 (status, tx_hash_or_error)。"""
    if not PLATFORM_PRIVATE_KEY or not tip.recipient:
        return ('no_key', None)
    author_address = (tip.recipient.wallet_address or tip.recipient.address or '').strip()
    if not author_address or not Web3.is_address(author_address):
        return ('no_address', None)
    try:
        from eth_account import Account
        w3_conn = get_working_web3()
        account = Account.from_key(PLATFORM_PRIVATE_KEY)
        platform_address = account.address
        if platform_address.lower() != (app.config['BSC']['RECEIVE_ADDRESS'] or '').lower():
            return ('failed', 'Platform key does not match RECEIVE_ADDRESS')
        nonce = w3_conn.eth.get_transaction_count(platform_address)
        gas_price = w3_conn.eth.gas_price
        tx = {
            'nonce': nonce,
            'chainId': app.config['BSC']['CHAIN_ID'],
            'to': Web3.to_checksum_address(author_address),
            'value': author_wei,
            'gas': 21000,
            'gasPrice': gas_price
        }
        signed = account.sign_transaction(tx)
        tx_hash = w3_conn.eth.send_raw_transaction(signed.raw_transaction)
        return ('sent', tx_hash.hex())
    except Exception as e:
        return ('failed', str(e)[:500])

def process_pending_tip_payouts():
    """处理所有未打款的打赏（payout_status 为 pending/failed/no_address 且无 payout_tx_hash）。返回 (处理数, 成功数, 失败数)。"""
    if not PLATFORM_PRIVATE_KEY:
        return (0, 0, 0)
    tips = Tip.query.filter(
        Tip.payout_tx_hash.is_(None),
        Tip.payout_status.in_(('pending', 'failed', 'no_address'))
    ).all()
    sent, failed = 0, 0
    for tip in tips:
        full_wei = int(tip.amount)
        author_wei = (full_wei * (100 - TIP_PLATFORM_FEE_PERCENT)) // 100
        status, result = try_send_tip_payout(tip, author_wei)
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

# ============== Models ==============
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    address = db.Column(db.String(42), unique=True, nullable=True, index=True)
    nonce = db.Column(db.String(32), default=lambda: secrets.token_hex(16))
    nonce_created_at = db.Column(db.DateTime, default=datetime.utcnow) # Added for nonce expiration
    username = db.Column(db.String(50), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    nickname = db.Column(db.String(50))
    avatar = db.Column(db.String(500), default='👻')
    bio = db.Column(db.String(500), default='')
    has_nft_badge = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False) # Added for user banning
    wallet_address = db.Column(db.String(42), nullable=True) # For tipping
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def refresh_nonce(self):
        self.nonce = secrets.token_hex(16)
        self.nonce_created_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'type': 'web3' if self.address else 'web2',
            'address': self.address,
            'wallet_address': self.wallet_address or self.address, # Fallback to login address
            'username': self.username,
            'nickname': self.nickname or self.username or (self.address[:6] + '...' if self.address else 'Unknown'),
            'avatar': self.avatar,
            'bio': self.bio,
            'has_nft_badge': self.has_nft_badge,
            'is_admin': self.is_admin,
            'is_banned': self.is_banned,
        }

class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    cover_image = db.Column(db.String(500), nullable=True)
    images = db.Column(db.Text) # JSON list
    author_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    view_count = db.Column(db.Integer, default=0)
    tx_hash = db.Column(db.String(66), unique=True, nullable=True)
    ipfs_cid = db.Column(db.String(100), nullable=True)
    nft_token_id = db.Column(db.BigInteger, nullable=True, index=True)
    nft_tx_hash = db.Column(db.String(66), nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    
    # New: Region and On-Chain Status
    region = db.Column(db.String(20), default='其他')
    is_on_chain = db.Column(db.Boolean, default=False)
    
    # Post Type (web2, web3, mixed)
    # 0: Web2, 1: Web3 (On-chain), 2: Mixed
    post_type = db.Column(db.Integer, default=0, index=True)

    # Admin controls
    is_hidden = db.Column(db.Boolean, default=False, index=True)
    allow_comments = db.Column(db.Boolean, default=True)

    # Repost logic
    is_repost = db.Column(db.Boolean, default=False)
    original_post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    repost_comment = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    
    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    likes = db.relationship('Like', backref='post', lazy='dynamic')
    votes = db.relationship('Vote', backref='post', lazy='dynamic') # Votes relationship
    original_post = db.relationship('Post', remote_side=[id], backref='reposts')
    
    def to_dict(self, current_user_id=None):
        try:
            images_list = json.loads(self.images) if self.images else []
        except (TypeError, ValueError):
            images_list = []
        is_liked = False
        is_bookmarked = False
        if current_user_id:
            is_liked = Like.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            is_bookmarked = Bookmark.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            
        original_post_data = None
        if self.original_post:
            op_author = self.original_post.author.to_dict() if self.original_post.author else {'id': self.original_post.author_id, 'nickname': '已注销', 'avatar': '👻'}
            original_post_data = {
                'id': self.original_post.id,
                'title': self.original_post.title,
                'content': self.original_post.content,
                'author': op_author
            }
            
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'cover_image': self.cover_image,
            'images': images_list,
            'author': self.author.to_dict() if self.author else {'id': self.author_id, 'nickname': '已注销', 'username': None, 'avatar': '👻'},
            'view_count': self.view_count,
            'likes_count': self.likes.count(),
            'comments_count': self.comments.count(),
            'votes': [v.to_dict() for v in self.votes], # Return votes
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'tx_hash': self.tx_hash,
            'ipfs_cid': self.ipfs_cid,
            'nft_token_id': self.nft_token_id,
            'nft_tx_hash': self.nft_tx_hash,
            'post_type': self.post_type,
            'created_at': self.created_at.isoformat(),
            'is_repost': self.is_repost,
            'original_post_id': self.original_post_id,
            'original_post': original_post_data,
            'repost_comment': self.repost_comment,
            'is_hidden': self.is_hidden,
            'allow_comments': self.allow_comments,
            'region': self.region,
            'is_on_chain': self.is_on_chain
        }

class Vote(db.Model):
    __tablename__ = 'votes'
    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    option_text = db.Column(db.String(100))
    vote_count = db.Column(db.Integer, default=0)
    
    def to_dict(self):
        return {
            'id': self.id,
            'option_text': self.option_text,
            'vote_count': self.vote_count
        }

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text)
    author_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    author = db.relationship('User', backref='comments')
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')
    
    def to_dict(self, recursive=False):
        author_data = self.author.to_dict() if self.author else {'id': self.author_id, 'nickname': '已注销', 'avatar': '👻'}
        data = {
            'id': self.id,
            'content': self.content,
            'author': author_data,
            'created_at': self.created_at.isoformat(),
            'parent_id': self.parent_id
        }
        if recursive:
            data['replies'] = [reply.to_dict(recursive=True) for reply in self.replies.all()]
        return data


def build_comment_tree(comments):
    """将扁平评论列表在内存中组装成树形结构，避免递归查询 N+1。comments 需已 joinedload(Comment.author)。"""
    by_parent = {}
    for c in comments:
        pid = c.parent_id
        if pid not in by_parent:
            by_parent[pid] = []
        by_parent[pid].append(c)

    def to_dict_node(c):
        author_data = c.author.to_dict() if c.author else {'id': c.author_id, 'nickname': '已注销', 'avatar': '👻'}
        return {
            'id': c.id,
            'content': c.content,
            'author': author_data,
            'created_at': c.created_at.isoformat(),
            'parent_id': c.parent_id,
            'replies': []
        }

    def fill_replies(nodes):
        for n in nodes:
            d = to_dict_node(n)
            children = by_parent.get(n.id) or []
            d['replies'] = list(fill_replies(children))
            yield d

    roots = sorted(by_parent.get(None) or [], key=lambda c: c.created_at, reverse=True)
    return list(fill_replies(roots))

class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_like'),)

class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_user_post_bookmark'),)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id')) # Recipient
    sender_id = db.Column(db.BigInteger, db.ForeignKey('users.id')) # Triggered by
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    type = db.Column(db.String(20)) # 'comment', 'reply', 'like', 'system'
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    recipient = db.relationship('User', foreign_keys=[user_id], backref='notifications')
    sender = db.relationship('User', foreign_keys=[sender_id])
    post = db.relationship('Post')
    
    def to_dict(self):
        return {
            'id': self.id,
            'type': self.type,
            'sender': self.sender.to_dict() if self.sender else None,
            'post_id': self.post_id,
            'post_title': self.post.title if self.post else None,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat()
        }

class UsedTransaction(db.Model):
    __tablename__ = 'used_transactions'
    id = db.Column(db.Integer, primary_key=True)
    tx_hash = db.Column(db.String(66), unique=True, nullable=False, index=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class UserVote(db.Model):
    __tablename__ = 'user_votes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    vote_id = db.Column(db.Integer, db.ForeignKey('votes.id'))
    __table_args__ = (db.UniqueConstraint('user_id', 'vote_id', name='unique_user_vote'),)

class Tip(db.Model):
    __tablename__ = 'tips'
    id = db.Column(db.Integer, primary_key=True)
    tx_hash = db.Column(db.String(66), unique=True, nullable=False, index=True)
    from_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    to_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    amount = db.Column(db.String(50)) # Store as string (Wei)，整笔打赏金额
    token_symbol = db.Column(db.String(10), default='BNB')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    # 自动打款：平台钱包将 93% 转给作者
    payout_tx_hash = db.Column(db.String(66), nullable=True, index=True)
    payout_status = db.Column(db.String(20), default='pending')  # pending, sent, failed, no_address
    payout_error = db.Column(db.String(500), nullable=True)
    
    sender = db.relationship('User', foreign_keys=[from_user_id])
    recipient = db.relationship('User', foreign_keys=[to_user_id])
    post = db.relationship('Post')

# ============== Helpers ==============
ALLOWED_AVATARS = ['👻', '💀', '👽', '👾', '🤖', '🎃', '🧛', '🧟', '🧞', '🧝', '🧙', '🧚', '🧜', '👼', '👿', '👺', '👹', '🤡', '💩', '🦄']

def get_random_avatar():
    return random.choice(ALLOWED_AVATARS)

IMGBB_MAX_SIZE = 2 * 1024 * 1024  # 2MB
IMGBB_ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

def upload_to_imgbb(file):
    if not file or not getattr(file, 'filename', None):
        return None
    filename = (file.filename or '').lower()
    if '.' not in filename or filename.rsplit('.', 1)[-1] not in IMGBB_ALLOWED_EXTENSIONS:
        return None
    try:
        file.seek(0, os.SEEK_END)
        size = file.tell()
        file.seek(0)
        if size > IMGBB_MAX_SIZE:
            return None
        img_b64 = base64.b64encode(file.read()).decode('utf-8')
        # According to docs: don't add expiration for permanent storage
        payload = {
            "key": IMGBB_API_KEY,
            "image": img_b64
        }
        response = requests.post("https://api.imgbb.com/1/upload", data=payload)
        if response.status_code == 200:
            json_resp = response.json()
            if 'data' in json_resp and 'url' in json_resp['data']:
                return json_resp['data']['url']
        return None
    except Exception as e:
        print(f"ImgBB Error: {e}")
        return None

def upload_to_pinata(json_data):
    if not PINATA_API_KEY or not PINATA_SECRET_API_KEY:
        print("Pinata keys missing")
        # In dev mode, generate a mock CID
        if app.config.get('DEBUG'):
            return 'Qm' + secrets.token_hex(22) + '(Mock)'
        return None
        
    url = "https://api.pinata.cloud/pinning/pinJSONToIPFS"
    headers = {
        "pinata_api_key": PINATA_API_KEY,
        "pinata_secret_api_key": PINATA_SECRET_API_KEY,
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(url, json=json_data, headers=headers)
        if response.status_code == 200:
            return response.json()['IpfsHash']
        print(f"Pinata Error: {response.text}")
        return None
    except Exception as e:
        print(f"Pinata Exception: {e}")
        return None

def get_arweave_wallet():
    """
    Load Arweave wallet from environment variable or local file.
    Priority:
    1. AR_KEY_DATA (Environment Variable - JSON String)
    2. AR_KEY_FILE (Environment Variable - File Path)
    3. ar_key.json (Local File)
    """
    # 1. Try Environment Variable (JSON Data)
    key_data_str = os.environ.get('AR_KEY_DATA')
    if key_data_str:
        import tempfile
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode='w+', delete=False) as tmp:
                tmp.write(key_data_str)
                tmp_path = tmp.name
            wallet = Wallet(tmp_path)
            wallet.api_url = ARWEAVE_GATEWAY
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

    # 2. Try Environment Variable (File Path)
    key_file_env = os.environ.get('AR_KEY_FILE')
    if key_file_env and os.path.exists(key_file_env):
        try:
            wallet = Wallet(key_file_env)
            wallet.api_url = ARWEAVE_GATEWAY
            return wallet
        except Exception as e:
            print(f"Error loading wallet from AR_KEY_FILE: {e}")

    # 3. Try Default Local Files
    for filename in ['ar_key.json', 'arweave-key.json']:
        if os.path.exists(filename):
            try:
                wallet = Wallet(filename)
                wallet.api_url = ARWEAVE_GATEWAY
                return wallet
            except Exception as e:
                print(f"Error loading wallet from {filename}: {e}")
                
    return None

def upload_to_arweave_native(data):
    """
    Upload JSON data to Arweave Permanent Storage
    Returns: Transaction ID (TXID)
    """
    wallet = get_arweave_wallet()
    
    if not wallet:
        print("Arweave wallet not found (Check AR_KEY_DATA or ar_key.json)")
        # In dev mode, generate a mock Arweave TXID
        if app.config.get('DEBUG'):
            return 'ArMock_' + secrets.token_hex(20)
        return None
        
    try:
        # Prepare data
        json_str = json.dumps(data)
        
        # Create and sign transaction
        transaction = Transaction(wallet, data=json_str)
        transaction.add_tag('Content-Type', 'application/json')
        transaction.add_tag('App-Name', 'GuiHua-Web3')
        transaction.add_tag('App-Version', '1.0.0')
        transaction.add_tag('Unix-Time', str(int(time.time())))
        
        transaction.sign()
        transaction.send()
        
        print(f"Arweave Upload Success: {transaction.id}")
        return transaction.id
    except Exception as e:
        print(f"Arweave Upload Error: {e}")
        return None


def build_and_upload_nft_metadata(post):
    """
    按 NFT 标准生成 metadata（name, description, content_hash, author_id, image, external_url），
    上传至 Arweave，返回 metadata 的 Arweave tx id（即 tokenURI 路径），失败返回 None。
    """
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
        tx_id = upload_to_arweave_native(metadata)
        return tx_id
    except Exception as e:
        print(f"NFT metadata upload error: {e}")
        return None


# NFT 铸造：.env 中 ADMIN_PRIVATE_KEY（铸造用私钥）、NFT_CONTRACT_ADDRESS（ERC-721 合约地址）
ADMIN_PRIVATE_KEY = os.environ.get('ADMIN_PRIVATE_KEY')
NFT_CONTRACT_ADDRESS = os.environ.get('NFT_CONTRACT_ADDRESS')

# ERC-721 常见 mint 接口：mint(address to, string tokenURI) 或 safeMint(address to, string tokenURI)
NFT_MINT_ABI = [{
    "inputs": [{"name": "to", "type": "address"}, {"name": "tokenURI", "type": "string"}],
    "name": "mint",
    "outputs": [{"name": "", "type": "uint256"}],
    "stateMutability": "nonpayable",
    "type": "function"
}]

def mint_nft(to_address, token_uri):
    """
    调用合约 mint(to, tokenURI)。使用 ADMIN_PRIVATE_KEY 发送交易。
    返回 (token_id, tx_hash) 成功；(None, error_msg) 失败。
    """
    if not ADMIN_PRIVATE_KEY or not NFT_CONTRACT_ADDRESS or not Web3.is_address(to_address):
        return None, "NFT mint not configured or invalid to_address"
    try:
        from eth_account import Account
        w3_conn = get_working_web3()
        account = Account.from_key(ADMIN_PRIVATE_KEY)
        contract = w3_conn.eth.contract(
            address=Web3.to_checksum_address(NFT_CONTRACT_ADDRESS),
            abi=NFT_MINT_ABI
        )
        tx = contract.functions.mint(Web3.to_checksum_address(to_address), token_uri).build_transaction({
            'from': account.address,
            'nonce': w3_conn.eth.get_transaction_count(account.address),
            'gas': 200000,
            'chainId': app.config['BSC']['CHAIN_ID']
        })
        signed = account.sign_transaction(tx)
        tx_hash = w3_conn.eth.send_raw_transaction(signed.raw_transaction)
        receipt = None
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
    """后台线程：为帖子生成 NFT 元数据、上传 Arweave、铸造 NFT、更新 Post.nft_token_id / nft_tx_hash。"""
    with app.app_context():
        try:
            post = Post.query.get(post_id)
            if not post or not post.ipfs_cid or not post.author:
                return
            to_address = (post.author.wallet_address or post.author.address or '').strip()
            if not to_address or not Web3.is_address(to_address):
                print(f"Post {post_id}: author has no wallet address, skip mint")
                return
            metadata_tx_id = build_and_upload_nft_metadata(post)
            if not metadata_tx_id:
                print(f"Post {post_id}: metadata upload failed, skip mint")
                return
            token_uri = f"https://arweave.net/{metadata_tx_id}"
            token_id, tx_hash_or_err = mint_nft(to_address, token_uri)
            if token_id is not None and tx_hash_or_err:
                post.nft_token_id = token_id
                post.nft_tx_hash = tx_hash_or_err
                db.session.commit()
                print(f"Post {post_id} NFT minted: token_id={token_id}, tx={tx_hash_or_err}")
            else:
                print(f"Post {post_id} mint failed: {tx_hash_or_err}")
        except Exception as e:
            print(f"async_mint_nft_for_post error: {e}")


def verify_transaction(tx_hash, user_address, expected_recipient=None, min_amount=None):
    """
    Verify transaction on BSC.
    Checks: Status, Sender (必须为当前用户), Receiver (必须为平台收款地址), Amount (>= 发帖费), Uniqueness.
    收款地址与最低金额均从环境变量来，不硬编码。查交易时多 RPC 兜底。
    """
    if not user_address:
        return False, 'User address not bound'

    if not expected_recipient:
        expected_recipient = app.config['BSC']['RECEIVE_ADDRESS']
    if not expected_recipient:
        return False, 'Platform receive address not configured'
    if min_amount is None:
        min_amount = get_post_fee_wei()  # 使用配置发帖费（1 USD 等值 BNB），勿硬编码

    # Check format
    if not re.match(r"^0x[a-fA-F0-9]{64}$", tx_hash):
        return False, 'Invalid transaction hash format'

    # Check uniqueness (prevent replay)
    if Post.query.filter_by(tx_hash=tx_hash).first():
        return False, 'Transaction hash already used'
    if UsedTransaction.query.filter_by(tx_hash=tx_hash).first():
        return False, 'Transaction hash already used (history)'

    print(f"Verifying tx: {tx_hash} for user {user_address}")

    tx = None
    receipt = None
    # 主网免费 RPC 同步慢：15 轮 × 3 秒；每轮内多节点兜底，某节点超时/异常即换下一个
    for attempt in range(15):
        for rpc in BSC_RPC_LIST:
            try:
                provider = Web3(Web3.HTTPProvider(rpc))
                provider.middleware_onion.inject(geth_poa_middleware, layer=0)
                tx = provider.eth.get_transaction(tx_hash)
                receipt = provider.eth.get_transaction_receipt(tx_hash)
                if tx and receipt:
                    print(f"Tx found after attempt {attempt + 1} via {rpc[:50]}...")
                    break
            except Exception as e:
                print(f"RPC {rpc[:50]}... attempt {attempt + 1}: {e}")
                continue
        if tx and receipt:
            break
        time.sleep(3)

    if not tx or not receipt:
        print(f"Timeout verifying tx: {tx_hash}")
        return False, 'Transaction not found on chain (timeout)'

    try:
        # 1. Check Status (1 = Success)
        if receipt['status'] != 1:
            return False, 'Transaction failed on chain'

        # 必须校验（防白嫖、防少付、防冒用）：
        # 2. 发起人 from == 当前登录用户（否则 A 付钱 B 可盗用哈希发帖）
        if tx['from'].lower() != user_address.lower():
            return False, f'Sender mismatch. Tx: {tx["from"]}, User: {user_address}'
        # 3. 收款人 to == 平台地址 RECEIVE_ADDRESS（否则用户给自己转 0.000001 也能过）
        if not tx['to'] or tx['to'].lower() != expected_recipient.lower():
            return False, f'Incorrect recipient. Expected: {expected_recipient}, Got: {tx["to"]}'
        # 4. 金额 value >= 发帖费 POST_FEE（否则付 0.000001 BNB 也能过）
        if tx['value'] < min_amount:
            return False, f'Insufficient fee. Paid: {tx["value"]}, Expected: {min_amount}'

        return True, tx['value'] # Return amount on success
    except Exception as e:
        print(f"Verify Tx Error: {e}")
        return False, 'Verification process failed'


def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split(" ")
            if len(parts) == 2:
                token = parts[1]
        
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            user = User.query.get(data['user_id'])
            if not user:
                return jsonify({'error': 'User not found'}), 401
            
            if user.is_banned:
                return jsonify({'error': 'Account has been banned'}), 403
                
            g.current_user = user
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token expired'}), 401
        except Exception:
            return jsonify({'error': 'Token is invalid'}), 401
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not g.current_user.is_admin:
            return jsonify({'error': 'Admin privilege required'}), 403
        return f(*args, **kwargs)
    return decorated

# ============== Routes ==============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/studio')
def studio():
    return render_template('studio.html')

@app.route('/profile')
def profile():
    return render_template('profile.html')

# --- Auth ---

@app.route('/api/auth/nonce', methods=['GET'])
def get_nonce():
    address = request.args.get('address')
    if not address: return jsonify({'error': 'Missing address'}), 400
    
    # Normalize address
    try:
        address = Web3.to_checksum_address(address)
    except:
        return jsonify({'error': 'Invalid address format'}), 400

    user = User.query.filter_by(address=address).first()
    if not user:
        try:
            user = User(address=address, nickname=f"User_{address[:6]}", avatar=get_random_avatar())
            db.session.add(user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            return jsonify({'error': 'Failed to create user, please retry'}), 500
    
    # Always refresh nonce
    user.refresh_nonce()
    db.session.commit()
    
    return jsonify({'nonce': user.nonce})

@app.route('/api/auth/verify', methods=['POST'])
def verify_signature():
    data = request.get_json()
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')
    
    # Normalize address
    try:
        address = Web3.to_checksum_address(address)
    except:
        return jsonify({'error': 'Invalid address format'}), 400
    
    # In production, verify signature here using web3
    from eth_account.messages import encode_defunct
    from eth_account import Account
    
    user = User.query.filter_by(address=address).first()
    if not user: return jsonify({'error': 'User not found'}), 404

    # Check nonce expiration (5 mins)
    if not user.nonce_created_at or datetime.utcnow() - user.nonce_created_at > timedelta(minutes=5):
        return jsonify({'error': 'Nonce expired, please sign again'}), 401

    # 严格全文本匹配，防止假站用同一 nonce 骗用户签名后到本站登录
    expected_message = f"Sign this message to login: {user.nonce}"
    if not message or message.strip() != expected_message:
        return jsonify({'error': 'Message does not match expected format'}), 400

    try:
        msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(msg, signature=signature)
        
        if recovered_address.lower() != address.lower():
             return jsonify({'error': 'Invalid signature'}), 401
    except Exception as e:
        print(f"Verify Error: {e}")
        return jsonify({'error': 'Verification failed'}), 400
    
    # Rotate nonce to prevent replay attacks
    user.refresh_nonce()
    db.session.commit()
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({'token': token, 'user': user.to_dict()})

@app.route('/api/auth/web2/register', methods=['POST'])
def register():
    try:
        data = request.get_json()
        if not data:
             return jsonify({'error': 'Missing JSON data'}), 400
             
        username = data.get('username')
        password = data.get('password')
        
        if not username or not password:
            return jsonify({'error': 'Username and password are required'}), 400
        
        if User.query.filter_by(username=username).first():
            return jsonify({'error': 'Username already exists'}), 400

        try:
            user = User(username=username, nickname=username, avatar=get_random_avatar())
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Register Error: {e}")
            return jsonify({'error': 'Registration failed'}), 500
        
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({'token': token, 'user': user.to_dict()}), 201
    except Exception as e:
        print(f"Register Error: {e}")
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/auth/web2/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    if user and user.check_password(password):
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({'token': token, 'user': user.to_dict()})
    
    return jsonify({'error': 'Invalid credentials'}), 401

@app.route('/api/auth/web2/change-password', methods=['POST'])
def change_password_no_login():
    """找回/修改密码：凭账号和原密码即可设置新密码，无需登录。"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Missing data'}), 400
    username = data.get('username')
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    if not username or not old_password or not new_password:
        return jsonify({'error': '请填写用户名、原密码和新密码'}), 400
    user = User.query.filter_by(username=username).first()
    if not user:
        return jsonify({'error': '用户不存在'}), 404
    if not user.check_password(old_password):
        return jsonify({'error': '原密码错误'}), 401
    if not user.password_hash:
        return jsonify({'error': '该账号为钱包登录，无密码可修改'}), 400
    user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': '密码已修改，请用新密码登录'})

@app.route('/api/user/me', methods=['GET', 'PUT'])
@token_required
def user_me():
    if request.method == 'GET':
        return jsonify(g.current_user.to_dict())
    
    # PUT: Update profile
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    nickname = data.get('nickname')
    bio = data.get('bio')
    avatar = data.get('avatar')
    refresh_avatar = data.get('refresh_avatar', False)
    
    if nickname:
        if len(nickname) > 50: return jsonify({'error': 'Nickname too long'}), 400
        g.current_user.nickname = bleach.clean(nickname, strip=True)
        
    if bio is not None:
        if len(bio) > 500: return jsonify({'error': 'Bio too long'}), 400
        g.current_user.bio = bleach.clean(bio, strip=True)
        
    if avatar:
        if avatar not in ALLOWED_AVATARS:
            return jsonify({'error': 'Invalid avatar. Only emojis are allowed.'}), 400
        g.current_user.avatar = avatar
    elif refresh_avatar:
        g.current_user.avatar = get_random_avatar()
        
    db.session.commit()
    return jsonify({'message': 'Profile updated', 'user': g.current_user.to_dict()})

@app.route('/api/user/password', methods=['PUT'])
@token_required
def change_password():
    data = request.get_json()
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({'error': 'Missing password fields'}), 400
        
    if not g.current_user.check_password(old_password):
        return jsonify({'error': 'Incorrect old password'}), 401
        
    g.current_user.set_password(new_password)
    db.session.commit()
    return jsonify({'message': 'Password updated'})

@app.route('/api/user/bind_wallet', methods=['POST'])
@token_required
def bind_wallet():
    # Only Web2 users (without address) can bind
    if g.current_user.address:
        return jsonify({'error': 'Wallet already bound'}), 400
        
    data = request.get_json()
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')
    
    if not address or not signature or not message:
        return jsonify({'error': 'Missing parameters'}), 400
        
    # Check if address already used
    if User.query.filter_by(address=address).first():
        return jsonify({'error': 'Address already bound to another account'}), 400
        
    # Verify signature
    from eth_account.messages import encode_defunct
    from eth_account import Account
    
    try:
        msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(msg, signature=signature)
        
        if recovered_address.lower() != address.lower():
             return jsonify({'error': 'Invalid signature'}), 401
    except Exception as e:
        print(f"Verify Error: {e}")
        return jsonify({'error': 'Verification failed'}), 400
        
    g.current_user.address = address
    db.session.commit()
    
    return jsonify({'message': 'Wallet bound successfully', 'user': g.current_user.to_dict()})

@app.route('/api/config/fees', methods=['GET'])
def get_fees():
    receive_address = app.config['BSC']['RECEIVE_ADDRESS']
    if not receive_address:
        return jsonify({'error': 'Platform receive address not configured'}), 503
    fee_wei = get_post_fee_wei()
    bnb_price_usd = get_bnb_price_usd()
    return jsonify({
        'fee': str(fee_wei),
        'chain_id': app.config['BSC']['CHAIN_ID'],
        'receive_address': receive_address,
        'fee_usd': 1,
        'bnb_price_usd': round(bnb_price_usd, 4) if bnb_price_usd else None
    })

@app.route('/api/gas/price', methods=['GET'])
def get_gas_price():
    try:
        w3 = get_working_web3()
        gas_price = w3.eth.gas_price
        return jsonify({
            'gas_price_wei': gas_price,
            'gas_price_gwei': float(Web3.from_wei(gas_price, 'gwei'))
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Posts ---

@app.route('/api/search', methods=['GET'])
def search_posts():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'posts': []})
    # 转义 LIKE 通配符，防止 %/_ 导致全表扫描或注入
    escaped_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    posts = Post.query.filter(
        (Post.title.ilike(f'%{escaped_q}%', escape='\\')) |
        (Post.content.ilike(f'%{escaped_q}%', escape='\\'))
    ).filter_by(is_hidden=False).order_by(Post.created_at.desc()).limit(20).all()
    return jsonify({'posts': [p.to_dict() for p in posts]})

@app.route('/api/posts/check_tx', methods=['GET'])
def check_tx_status():
    tx_hash = request.args.get('tx_hash')
    if not tx_hash:
        return jsonify({'error': 'Missing tx_hash'}), 400
        
    # Check if it exists in Post (Published successfully)
    post = Post.query.filter_by(tx_hash=tx_hash).first()
    if post:
        return jsonify({'status': 'success', 'post_id': post.id, 'post_title': post.title})
        
    return jsonify({'status': 'pending'})

@app.route('/api/admin/stats', methods=['GET'])
@token_required
def admin_stats():
    if not g.current_user.is_admin:
        return jsonify({'error': 'Admin only'}), 403
        
    # Stats
    total_users = User.query.count()
    web3_users = User.query.filter(User.address != None).count()
    web2_users = total_users - web3_users
    
    total_posts = Post.query.count()
    web3_posts = Post.query.filter(Post.post_type == 1).count() # Or filter by tx_hash
    web2_posts = total_posts - web3_posts
    
    # Calculate revenue (Approximation: web3_posts * POST_FEE)
    # Note: fee is in Wei (int), convert to Ether for display
    fee_wei = app.config['BSC']['POST_FEE']
    total_revenue_wei = web3_posts * fee_wei
    total_revenue_bnb = w3.from_wei(total_revenue_wei, 'ether')
    
    return jsonify({
        'users': {
            'total': total_users,
            'web3': web3_users,
            'web2': web2_users,
            'retention_rate': 'N/A' # Requires login history tracking
        },
        'posts': {
            'total': total_posts,
            'web3': web3_posts,
            'web2': web2_posts
        },
        'revenue': {
            'total_bnb': float(total_revenue_bnb),
            'fee_per_post': float(w3.from_wei(fee_wei, 'ether'))
        }
    })

@app.route('/api/users/<username>', methods=['GET'])
def get_user_profile(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        # Try finding by address
        if username.startswith('0x'):
            user = User.query.filter_by(address=username).first()
            
    if not user:
        return jsonify({'error': 'User not found'}), 404

    posts = Post.query.filter_by(author_id=user.id, is_hidden=False).order_by(Post.created_at.desc()).all()
    user_data = user.to_dict()
    user_data['posts_count'] = len(posts)

    return jsonify({
        'user': user_data,
        'posts': [p.to_dict() for p in posts]
    })

@app.route('/api/notifications', methods=['GET'])
@token_required
def get_notifications():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    pagination = Notification.query.filter_by(user_id=g.current_user.id)\
        .order_by(Notification.created_at.desc())\
        .paginate(page=page, per_page=per_page, error_out=False)
        
    notifs = pagination.items
    
    return jsonify({
        'notifications': [n.to_dict() for n in notifs],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/notifications/<int:id>/read', methods=['PUT'])
@token_required
def read_notification(id):
    notif = Notification.query.get_or_404(id)
    if notif.user_id != g.current_user.id:
        return jsonify({'error': 'Not your notification'}), 403
        
    notif.is_read = True
    db.session.commit()
    return jsonify({'message': 'Marked as read'})

@app.route('/api/notifications/read_all', methods=['PUT'])
@token_required
def read_all_notifications():
    Notification.query.filter_by(user_id=g.current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    return jsonify({'message': 'All marked as read'})

@app.route('/api/posts', methods=['GET'])
def get_posts():
    token = None
    current_user_id = None
    if 'Authorization' in request.headers:
        try:
            token = request.headers['Authorization'].split(" ")[1]
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            current_user_id = data['user_id']
        except: pass

    sort_by = request.args.get('sort', 'new')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    region = request.args.get('region') # Filter by region
    
    from sqlalchemy.orm import joinedload
    query = Post.query.options(
        joinedload(Post.author),
        joinedload(Post.votes),
    )

    if sort_by == 'hot':
        # Simple hot sort
        from sqlalchemy import func
        query = query.outerjoin(Like).group_by(Post.id).order_by(func.count(Like.id).desc())
    elif sort_by == 'bookmarks':
        if current_user_id:
            query = query.join(Bookmark).filter(Bookmark.user_id == current_user_id)
        else:
            return jsonify({'posts': [], 'total': 0, 'pages': 0, 'current_page': 1})
    else: # 'new'
        query = query.order_by(Post.created_at.desc())

    # Filter by Region
    if region:
        query = query.filter_by(region=region)

    # Filter hidden posts unless admin
    current_user = None
    if current_user_id:
        current_user = User.query.get(current_user_id)
        
    if not current_user or not current_user.is_admin:
        query = query.filter_by(is_hidden=False)

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    posts = pagination.items
    
    # Batch fetch likes/bookmarks for current user to avoid N+1
    user_likes = set()
    user_bookmarks = set()
    
    if current_user_id and posts:
        post_ids = [p.id for p in posts]
        likes = Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()
        user_likes = {l.post_id for l in likes}
        
        bookmarks = Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()
        user_bookmarks = {b.post_id for b in bookmarks}

    # Manual to_dict construction to inject pre-fetched state
    posts_data = []
    for p in posts:
        # We use a modified to_dict logic here or update the object temporarily (not recommended for persistent session)
        # Better to construct dict manually or pass state to a helper
        p_dict = p.to_dict() # Call basic to_dict without user_id
        p_dict['is_liked'] = p.id in user_likes
        p_dict['is_bookmarked'] = p.id in user_bookmarks
        posts_data.append(p_dict)
    
    return jsonify({
        'posts': posts_data,
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/posts', methods=['POST'])
@token_required
def create_post():
    # 1. Permission Check
    if not g.current_user.is_admin and not g.current_user.address:
        return jsonify({'error': 'Wallet binding required'}), 400
    
    # Check if multipart/form-data (for image upload)
    if 'image' in request.files:
        title = request.form.get('title')
        content = request.form.get('content')
        image_file = request.files.get('image')
        tx_hash = request.form.get('tx_hash')
        region = request.form.get('region', '其他')
        vote_options_str = request.form.get('vote_options')
        vote_options = json.loads(vote_options_str) if vote_options_str else []
        # 封面可选：有上传文件则走 ImgBB，否则用表单里的 cover_image URL 或留空
        cover_url = None
        if image_file and getattr(image_file, 'filename', None) and image_file.filename.strip():
            cover_url = upload_to_imgbb(image_file)
            if not cover_url:
                return jsonify({'error': 'Image upload failed'}), 500
        else:
            cover_url = (request.form.get('cover_image') or '').strip() or None
        data = {
            'title': title,
            'content': content,
            'cover_image': cover_url,
            'tx_hash': tx_hash,
            'ipfs_cid': request.form.get('ipfs_cid'),
            'images': [],
            'region': region,
            'vote_options': vote_options
        }
    else:
        # JSON fallback
        data = request.get_json()
    
    tx_hash = data.get('tx_hash')
    ipfs_cid = data.get('ipfs_cid')
    region = data.get('region', '其他')
    vote_options = data.get('vote_options', [])
    
    # 2. Region Validation
    valid_regions = ['中国', '台湾', '香港', '澳门', '新加坡', '马来西亚', '日本', '韩国', '其他']
    if region not in valid_regions:
        return jsonify({'error': f'Invalid region. Allowed: {", ".join(valid_regions)}'}), 400

    # 3. Logic Branching（is_paid 仅由后端校验结果决定，绝不信任客户端传入）
    is_paid = False
    is_on_chain = False

    if g.current_user.is_admin:
        # 管理员直接发帖：不上链、不支付，仅普通论坛帖，仅管理员可发
        tx_hash = None
        ipfs_cid = None
    else:
        # Regular User: 必须带 tx_hash，且经 verify_transaction 校验 to/from/value 与唯一性（min_amount = 1 USD 等值 BNB）
        if not tx_hash:
            return jsonify({'error': 'Transaction hash required'}), 400
        is_valid, error_msg = verify_transaction(tx_hash, g.current_user.address, min_amount=get_post_fee_wei())
        if not is_valid:
            return jsonify({'error': error_msg}), 400
            
        is_paid = True
        is_on_chain = True
        
        # Arweave Upload (Server pays)
        clean_content = bleach.clean(data.get('content', ''), tags=['b','i','u','img','p','br','div','span'], strip=True)
        payload = {
            'title': data.get('title'),
            'content': clean_content,
            'cover_image': data.get('cover_image'),
            'author': g.current_user.address,
            'timestamp': datetime.utcnow().isoformat(),
            'tx_hash': tx_hash,
            'region': region,
            'platform': 'GuiHua Web3 (Arweave)'
        }
        
        ar_tx_id = upload_to_arweave_native(payload)
        if ar_tx_id:
            ipfs_cid = ar_tx_id
        else:
            # Fallback to Pinata if Arweave fails
            if PINATA_API_KEY:
                ipfs_cid = upload_to_pinata(payload)

    # 防重复：保存前再次确认该交易哈希未被任何帖子使用（与 verify_transaction + unique 约束三重保险，防并发）
    if tx_hash:
        existing_post = Post.query.filter_by(tx_hash=tx_hash).first()
        if existing_post:
            return jsonify({'error': '该交易已用于其他帖子'}), 400

    # 4. Create Post
    clean_content = bleach.clean(data.get('content', ''), tags=['b','i','u','img','p','br','div','span'], strip=True)
    clean_title = bleach.clean(data.get('title', ''), strip=True)
    if not clean_title or not clean_title.strip():
        return jsonify({'error': '标题不能为空'}), 400
    if not clean_content or not clean_content.strip():
        return jsonify({'error': '正文不能为空'}), 400

    # 封面选填：空字符串规范为 None
    cover_image = data.get('cover_image')
    if isinstance(cover_image, str):
        cover_image = cover_image.strip() or None
    if not cover_image:
        cover_image = None
    post = Post(
        title=clean_title,
        content=clean_content,
        cover_image=cover_image,
        images=json.dumps(data.get('images', [])),
        author_id=g.current_user.id,
        tx_hash=tx_hash,
        ipfs_cid=ipfs_cid,
        is_paid=is_paid,
        is_on_chain=is_on_chain,
        region=region,
        post_type=1 if is_on_chain else 0
    )
    
    try:
        db.session.add(post)
        db.session.flush() # Get ID for votes
        
        # 5. Handle Votes
        if vote_options and isinstance(vote_options, list):
            for opt in vote_options:
                if opt and isinstance(opt, str) and len(opt.strip()) > 0:
                    clean_opt = bleach.clean(opt.strip(), strip=True)
                    vote = Vote(post_id=post.id, option_text=clean_opt)
                    db.session.add(vote)
        
        # 6. Record Transaction (Prevent Replay)
        if tx_hash and not g.current_user.is_admin:
            used_tx = UsedTransaction(tx_hash=tx_hash, user_id=g.current_user.id)
            db.session.add(used_tx)
            
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        if 'unique' in str(e).lower() and 'tx_hash' in str(e).lower():
            return jsonify({'error': 'Transaction hash already used'}), 400
        print(f"Create Post DB Error: {e}")
        return jsonify({'error': 'Database error'}), 500

    if post.ipfs_cid and ADMIN_PRIVATE_KEY and NFT_CONTRACT_ADDRESS:
        threading.Thread(target=async_mint_nft_for_post, args=(post.id,), daemon=True).start()
    
    return jsonify({'message': 'Post created', 'post': post.to_dict()}), 201

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        # Check if user can see it
        token = None
        current_user_id = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].split(" ")[1]
                data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
                current_user_id = data['user_id']
            except: pass
            
        post_data = post.to_dict(current_user_id)

        from sqlalchemy.orm import joinedload
        all_comments = Comment.query.filter_by(post_id=post_id).options(
            joinedload(Comment.author)
        ).order_by(Comment.created_at.asc()).all()
        post_data['comments'] = build_comment_tree(all_comments)
        post_data['comments_count'] = len(all_comments)

        return jsonify(post_data)
    except Exception as e:
        print(f"Post Detail Error: {e}")
        return jsonify({'error': 'Failed to load post'}), 500

@app.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    data = request.get_json()
    content = data.get('content', '')
    
    original_post = Post.query.get_or_404(post_id)
    target_id = original_post.original_post_id if original_post.original_post_id else post_id
    
    clean_comment = bleach.clean(content, tags=[], strip=True)

    new_post = Post(
        title=bleach.clean(f"转发: {original_post.title}", strip=True),
        content="",
        repost_comment=clean_comment,
        author_id=g.current_user.id,
        is_repost=True,
        original_post_id=target_id,
        is_paid=True
    )
    
    db.session.add(new_post)
    db.session.commit()
    return jsonify(new_post.to_dict()), 201

@app.route('/api/posts/<int:post_id>/vote', methods=['POST'])
@token_required
def vote_post(post_id):
    post = Post.query.get_or_404(post_id)
    data = request.get_json()
    option_id = data.get('option_id')
    
    if not option_id:
        return jsonify({'error': 'Option ID required'}), 400
        
    vote_option = Vote.query.get(option_id)
    if not vote_option or vote_option.post_id != post_id:
        return jsonify({'error': 'Invalid vote option'}), 400
    
    # Check if already voted
    existing_vote = UserVote.query.filter_by(user_id=g.current_user.id, vote_id=option_id).first()
    if existing_vote:
        return jsonify({'error': 'You have already voted for this option'}), 400
    
    # Record vote
    try:
        user_vote = UserVote(user_id=g.current_user.id, vote_id=option_id)
        db.session.add(user_vote)
        vote_option.vote_count += 1
        db.session.commit()
    except Exception as e: # IntegrityError catch
        db.session.rollback()
        return jsonify({'error': 'Already voted'}), 400
    
    return jsonify({
        'message': 'Voted successfully',
        'votes': [v.to_dict() for v in post.votes]
    })

# --- Interactions ---

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    if not post.allow_comments and not g.current_user.is_admin:
        return jsonify({'error': 'Comments are closed for this post'}), 403

    data = request.get_json()
    content = data.get('content')
    parent_id = data.get('parent_id')
    
    if not content: return jsonify({'error': 'Content empty'}), 400
    
    clean_content = bleach.clean(content, tags=[], strip=True)
    
    # Verify parent exists if provided
    if parent_id:
        parent = Comment.query.get(parent_id)
        if not parent or parent.post_id != post_id:
            return jsonify({'error': 'Invalid parent comment'}), 400
    
    comment = Comment(content=clean_content, author_id=g.current_user.id, post_id=post.id, parent_id=parent_id)
    db.session.add(comment)
    db.session.commit()
    
    # Notification Logic
    try:
        if parent_id:
            # Reply to comment
            parent_comment = Comment.query.get(parent_id)
            if parent_comment.author_id != g.current_user.id:
                notif = Notification(
                    user_id=parent_comment.author_id,
                    sender_id=g.current_user.id,
                    post_id=post.id,
                    comment_id=comment.id,
                    type='reply'
                )
                db.session.add(notif)
        elif post.author_id != g.current_user.id:
            # Comment on post
            notif = Notification(
                user_id=post.author_id,
                sender_id=g.current_user.id,
                post_id=post.id,
                comment_id=comment.id,
                type='comment'
            )
            db.session.add(notif)
        db.session.commit()
    except Exception as e:
        print(f"Notification Error: {e}")

    return jsonify({'message': 'Comment added', 'comment': comment.to_dict()}), 201

@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    try:
        like = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
        if like:
            db.session.delete(like)
            msg = 'Unliked'
        else:
            db.session.add(Like(user_id=g.current_user.id, post_id=post.id))
            msg = 'Liked'
            # Notification
            if post.author_id != g.current_user.id:
                notif = Notification(
                    user_id=post.author_id,
                    sender_id=g.current_user.id,
                    post_id=post.id,
                    type='like'
                )
                db.session.add(notif)
        db.session.commit()
        return jsonify({'message': msg})
    except Exception as e:
        db.session.rollback()
        # If it's an integrity error, it means we tried to like a liked post (race condition)
        # We can treat it as 'already liked'
        return jsonify({'message': 'Operation failed', 'error': str(e)}), 400

@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    try:
        bm = Bookmark.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
        if bm:
            db.session.delete(bm)
            msg = 'Unbookmarked'
        else:
            db.session.add(Bookmark(user_id=g.current_user.id, post_id=post.id))
            msg = 'Bookmarked'
        db.session.commit()
        return jsonify({'message': msg})
    except Exception as e:
        db.session.rollback()
        return jsonify({'message': 'Operation failed', 'error': str(e)}), 400

@app.route('/api/upload', methods=['POST'])
@token_required
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
        
    url = upload_to_imgbb(file)
    if url:
        return jsonify({'url': url})
    return jsonify({'error': 'Upload failed'}), 500

@app.route('/api/upload/ipfs', methods=['POST'])
@token_required
def upload_ipfs():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
        
    # Add metadata
    data['pinned_by'] = g.current_user.username or g.current_user.address
    data['pinned_at'] = datetime.utcnow().isoformat()
    
    # Try Arweave first
    ar_id = upload_to_arweave_native(data)
    if ar_id:
        return jsonify({'cid': ar_id, 'storage': 'arweave'})
    
    # Fallback to Pinata
    cid = upload_to_pinata(data)
    if cid:
        return jsonify({'cid': cid, 'storage': 'ipfs'})
    
    # Fallback for dev if no keys
    if app.config.get('DEBUG'):
         # Generate mock Arweave ID
         mock_id = 'ArMock_' + secrets.token_hex(20)
         return jsonify({'cid': mock_id, 'mock': True})
         
    return jsonify({'error': 'Storage upload failed'}), 500

# --- Admin & Debug ---

@app.route('/api/tips/verify', methods=['POST'])
@token_required
def verify_tip():
    """打赏必须先打到平台钱包 RECEIVE_ADDRESS，平台抽 7% 建设费，93% 归作者（后续由平台钱包转给作者）。"""
    data = request.get_json()
    tx_hash = data.get('tx_hash')
    post_id = data.get('post_id')
    if not tx_hash or not post_id:
        return jsonify({'error': 'Missing parameters'}), 400
    post = Post.query.get_or_404(post_id)
    if not post.author:
        return jsonify({'error': 'Post author not found'}), 400
    platform_address = app.config['BSC']['RECEIVE_ADDRESS']
    if not platform_address:
        return jsonify({'error': 'Platform receive address not configured'}), 503
    min_tip = Web3.to_wei(0.0001, 'ether')
    # 校验：打赏必须打到平台钱包，不能直接打给作者
    is_valid, result = verify_transaction(
        tx_hash,
        g.current_user.address,
        expected_recipient=platform_address,
        min_amount=min_tip
    )
    if not is_valid:
        return jsonify({'error': result}), 400
    amount_full = int(result)
    if Tip.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': 'Tip already recorded'}), 400
    # 7% 平台建设费，93% 给作者（作者实得）
    fee_percent = TIP_PLATFORM_FEE_PERCENT
    platform_fee_wei = (amount_full * fee_percent) // 100
    author_wei = amount_full - platform_fee_wei
    tip = Tip(
        tx_hash=tx_hash,
        from_user_id=g.current_user.id,
        to_user_id=post.author.id,
        post_id=post.id,
        amount=str(amount_full)
    )
    used_tx = UsedTransaction(tx_hash=tx_hash, user_id=g.current_user.id)
    try:
        db.session.add(tip)
        db.session.add(used_tx)
        if post.author.id != g.current_user.id:
            notif = Notification(
                user_id=post.author.id,
                sender_id=g.current_user.id,
                post_id=post.id,
                type='tip'
            )
            db.session.add(notif)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    # 自动打款：从平台钱包把 93% 转给作者（需配置 PLATFORM_PRIVATE_KEY）
    payout_status, payout_result = try_send_tip_payout(tip, author_wei)
    tip.payout_status = payout_status
    if payout_status == 'sent':
        tip.payout_tx_hash = payout_result
    elif payout_status == 'failed':
        tip.payout_error = payout_result
    elif payout_status == 'no_address':
        tip.payout_error = 'Author has no wallet address'
    try:
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({
        'message': 'Tip verified',
        'tip': {
            'amount': str(amount_full),
            'tx_hash': tx_hash,
            'amount_bnb': str(w3.from_wei(amount_full, 'ether')),
            'platform_fee_percent': fee_percent,
            'platform_fee_bnb': str(w3.from_wei(platform_fee_wei, 'ether')),
            'author_receives_bnb': str(w3.from_wei(author_wei, 'ether')),
            'payout_tx_hash': tip.payout_tx_hash,
            'payout_status': tip.payout_status
        }
    })

@app.route('/api/user/revenue', methods=['GET'])
@token_required
def get_revenue():
    """作者收入：打赏的 93%（7% 为平台建设费已扣除）"""
    tips = Tip.query.filter_by(to_user_id=g.current_user.id).order_by(Tip.created_at.desc()).all()
    total_author_wei = 0
    tips_data = []
    for tip in tips:
        full_wei = int(tip.amount)
        author_wei = (full_wei * (100 - TIP_PLATFORM_FEE_PERCENT)) // 100
        total_author_wei += author_wei
        tips_data.append({
            'from': tip.sender.nickname if tip.sender else 'Unknown',
            'post_title': tip.post.title if tip.post else 'Unknown',
            'amount_wei': str(author_wei),
            'amount_full_wei': tip.amount,
            'platform_fee_percent': TIP_PLATFORM_FEE_PERCENT,
            'tx_hash': tip.tx_hash,
            'payout_tx_hash': getattr(tip, 'payout_tx_hash', None),
            'payout_status': getattr(tip, 'payout_status', 'pending'),
            'created_at': tip.created_at.isoformat()
        })
    total_bnb = float(w3.from_wei(total_author_wei, 'ether'))
    return jsonify({
        'total_wei': str(total_author_wei),
        'total_bnb': total_bnb,
        'tips': tips_data,
        'wallet_address': g.current_user.address,
        'platform_fee_percent': TIP_PLATFORM_FEE_PERCENT
    })

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Allow admin or author to delete
    if not g.current_user.is_admin and post.author_id != g.current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    # Delete related
    Comment.query.filter_by(post_id=post.id).delete()
    Like.query.filter_by(post_id=post.id).delete()
    Bookmark.query.filter_by(post_id=post.id).delete()
    Vote.query.filter_by(post_id=post.id).delete()
    
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Post deleted'})

@app.route('/api/posts/<int:post_id>', methods=['PUT'])
@token_required
def update_post(post_id):
    post = Post.query.get_or_404(post_id)
    
    # Only author can edit
    if post.author_id != g.current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
        
    # Cannot edit if on-chain (immutable)
    if post.is_on_chain:
        return jsonify({'error': 'Cannot edit on-chain content'}), 400
        
    data = request.get_json()
    title = data.get('title')
    content = data.get('content')
    
    if title:
        post.title = bleach.clean(title, strip=True)
    if content:
        post.content = bleach.clean(content, tags=['b','i','u','img','p','br','div','span'], strip=True)
        
    db.session.commit()
    return jsonify({'message': 'Post updated', 'post': post.to_dict()})

@app.route('/api/admin/posts/<int:post_id>/hide', methods=['POST'])
@token_required
@admin_required
def toggle_hide_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_hidden = not post.is_hidden
    db.session.commit()
    return jsonify({'message': 'Toggled hide status', 'is_hidden': post.is_hidden})

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
@admin_required
def toggle_post_comments(post_id):
    post = Post.query.get_or_404(post_id)
    post.allow_comments = not post.allow_comments
    db.session.commit()
    return jsonify({'message': 'Toggled comments status', 'allow_comments': post.allow_comments})

@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@token_required
@admin_required
def ban_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_admin:
        return jsonify({'error': 'Cannot ban admin'}), 400
        
    user.is_banned = not user.is_banned
    db.session.commit()
    return jsonify({'message': 'User ban status toggled', 'is_banned': user.is_banned})

@app.route('/api/admin/users', methods=['GET'])
@token_required
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return jsonify([u.to_dict() for u in users])

@app.route('/api/admin/process-tip-payouts', methods=['POST'])
@token_required
@admin_required
def admin_process_tip_payouts():
    """手动触发：处理所有未打款的打赏（需配置 PLATFORM_PRIVATE_KEY）。"""
    total, sent, failed = process_pending_tip_payouts()
    return jsonify({
        'message': 'Processed pending tip payouts',
        'processed': total,
        'sent': sent,
        'failed': failed
    })

# /api/debug/seed 已移除，生产环境不可暴露造数接口；造数请用 Flask shell 或独立脚本

def init_db_data():
    """Auto-initialize basic data on startup"""
    try:
        # Ensure Admin exists（按 is_admin 或用户名查，避免与 AdminGao 不一致导致重复创建）
        from sqlalchemy import or_
        admin = User.query.filter(
            or_(User.username == 'admin', User.username == 'AdminGao', User.is_admin == True)
        ).first()
        if not admin:
            admin = User(
                username='AdminGao',
                nickname='Admin',
                is_admin=True,
                avatar='👺',
                address='0x1234567890123456789012345678901234567890'
            )
            admin.set_password('Gao200430')
            db.session.add(admin)
            try:
                db.session.commit()
                print("Admin created.")
            except Exception as e:
                db.session.rollback()
                if 'unique' in str(e).lower() or 'IntegrityError' in type(e).__name__:
                    pass  # 已存在（如地址冲突），忽略
                else:
                    print(f"Init Data Error (admin): {e}")
        
        # Ensure 'Hua Xiansheng' article exists（用 ilike 避免标题弯引号导致编码/匹配或 f405）
        db.session.rollback()
        title = '甘肃“再生人”华先生访问记'
        try:
            existing = Post.query.filter(Post.title.ilike('%华先生访问记%')).first()
        except Exception as e:
            print(f"Init DB: seed post check failed: {e}")
            existing = None
        if not existing:
            try:
                content = """<p><strong>——某县局长，清晰讲述前世地主及死后做鬼经历</strong><br>
《传统文化文摘》记者李懿桐采写<br>
原文出处 高耀峰的博客</p>

<p>阿弥陀佛！大家好！</p>

<p>“再生人”，就是民间人们说的没喝孟婆汤，转世后还能清楚记得前世的那些人，媒体报道过湖南坪阳乡出现的一百多位“再生人”故事，轰动全国。这一篇访问记的内容是发生在我们身边的，近在咫尺的甘肃的一位“再生人”故事。那么在正式开篇之前，请先让末学为读者们简单介绍一下这次访问的缘起吧！</p>

<p>高耀峰老师，退休前为甘肃省公安厅宣传部处长，喜爱写作，为中国作家协会会员。在多年创作之余，高老师发现了许多科学难以解释的奇异鬼神事件，遂入迷，致力于研究鬼神现象，并因此遇到一个重大的，可以说非比寻常的机缘，这就是大家熟所知的与一个2000多年前的灵魂——凯撒大帝的三王子进行对话的机会。高老师对三王子的采访前后历经三年，成书一部——《凯撒军团东征中国之谜》。这部书的问世，让学佛的同修和现在还未步入佛门，但是对鬼神现象很感兴趣的朋友们都对六道轮回、因果报应的真实性消除了疑虑，发自真心的相信了这个世界原本就真实存在的纷繁复杂。但是唯一遗憾的是，这本书在国内不能印刷，大家所看到的版本是在台湾印刷的，因此而成本高昂，数量有限，再版不易，不能大量流通。为了让更多的人们能读到这本书，从现代真实的鬼神附体现象中发起深信因果轮回的真心，</p>

<p>陈崇跃老师发大愿，承办杂志，起名《因果》，以连载此书，广为流通，以使更多的朋友能从这一罕见的大事因缘中获得法益，为众生尽此生得以脱离这苦海无边的娑婆世界，尽一份自己的力量。当然，编辑部还会整理刊载其他反应因果轮回的真实事件。这一篇访问记，就是创办《因果》杂志以来，编辑部第一次对真人轮回事件的采访。</p>

<p>主人公华先生，生于1965年农历5月27日，现年51岁，男，现工作居住在甘肃武都市某县。大家看到“某”县，一定觉得不过瘾，怎么又要隐瞒，难道国家政策还象几十年前一样有所忌讳？不允许！</p>

<p>非也！</p>

<p>也非编辑部不自信，怕此事经不起考察，怕好较真的读者朋友们核实挑刺，实为华先生自己有一个顾虑！</p>

<p>其实国家现实情况是这样：2014年在湘西、黔东北、桂北三省交界地带发现了数百名此类人后，国家及这三省包括国内外各类媒体如报纸、杂志、广播、电视台、有线电视、公众微信号反复刋登、传播，也有国家、地方的不少官办、私营生命科学研究机构和个人爱好者纷纷前往探寻采访，持续掀起研究热潮，一些身处当地的汉、苗、桐、彝族出身的公职人员、大中小学老师、作家、民俗研究专家纷纷利用近在咫尺的优势以亲见亲历者的身份写文章、开博客，三省交界处的当地乡县政府的公务员、领导也积极配合外地外省外国的媒体记者、学者的调查，也同时形成了一批业余及半研究专家，如怀化通道县坪阳乡文化站站长杨盛玉同志利用所处的地理优势对全乡发现确定的110位再生人进行了系统的调查，建立了档案。一些县乡政府很支持外界的采访，当做一项提高地方知名度的具体措施。有些地方领导正在探索利用“再生人”现象发展地方旅游的新路子。</p>

<p>华先生现为在职在权位国家干部，且处在县级领导干部的岗位，分管人事编制，职权不算小。当地县乡无论县长书记普通百姓甚至上级市级机关的领导都知道他的故事。因为他一岁起就忍不住开始讲他的故事。而且在省会兰州上商学院期间也常给同学讲，回到县上分配到某局给同事讲，还在当乡长时给同事、村干部讲，湘黔桂三省交界处的故事他当然会知道。更知道国家眼下形势非常宽松。他也发心愿以他的亲身经历证明六道轮回的存在。可当升了县级领导以后，又担心一个新问题：杂志流通开来，一些人当然再也无法给他扣“封建迷信”“反革命”帽子，他也不怕仅凭此一项上级会撤销他的县级干部的职务，但他担心有人会有闲言碎语：说他自己以“再生人”的所谓的特殊身份沽名钓誉，心思没放在工作上。因为官多年，干过人事，又当过乡长，总会得罪一些人，自然有嫉妒者，也有政敌。所以要求发文时隐去真实姓名及处所。我们也是公务员，理解他的顾虑，所以决定尊重华先生的这个想法。虽然我们感觉他过于谨小慎微了：从一岁没离娘奶就给人说，可正式采访他又担心有人说他沽名钓鱼了。末学在此代华先生请大家谅解了！阿弥陀佛！</p>

<p>线索提供人：甘肃省陇南市某县招商局章局长<br>
采访时间：2016年8月23日<br>
采访地点：甘肃省陇南市某县宾馆<br>
采访人：陈祟耀、高耀峰、李懿桐<br>
整理：李懿桐</p>

<p>华先生不胖不瘦，戴一副白边眼镜，很是一位学者。文质彬彬，双目炯炯有神，待人很热情。在与接待我们的当地朋友碰头时，朋友事先并没告知我们华先生也在其中，以为会安排我们第二天再进行采访，却不知热情的华先生早早的就跟朋友们一起来迎接我们了。华先生自报家门后，我们觉得真是意外的惊喜，这么快就见到了采访对象，急切的想采访的心情把彼此还不熟悉的陌生感一扫而空，坐定寒暄一阵，大家的谈话就进入了正题。</p>

<p>以下就是我们以问答的形式整理的访谈内容。</p>

<p><strong>高老师：华先生，您好！你前世是做什么的？</strong></p>

<p>华先生：我前世是当地一个较大的地主，管辖周边七个乡的收税事情，我从下边的保长、甲长处收来，然后集中运到县上交给县政府。因为我们这个县境内全是高山密林，山大沟深，动辄离县上二三百里，缴纳税费非常不方便。全县甚至没有一块三四亩大的连片的平地。全县人口极为分散，因为川坝子太窄太小，甚至一个农家小院里里都有台阶。人口百分之八十都住在河坝两边的山上。全县两条沟。一个沟里的河叫白龙江，另一个沟里的河叫白水江两条河，在离我们县城二三十里的下游处会合了，最后流到嘉陵江去了。</p>

<p><strong>高老师：你前世姓什么？</strong></p>

<p>华先生：前世姓吴，具体名字记不清了，听别人喊我张明亿（音）。说是地主，其实手里边银元并不多，都是些铜板。家里有老婆、孩子，有转角楼，有专门的大牲畜圈房，养猪、鸡的圈舍，有较多的田地，大都是山地。家里有雇工，出产和收入以种植大黄、当归等中药材为主，没有别的生意。我受国民党县政府委托维护当地的社会治安，兼代收税费。税费有时是粮食，有时是钱。给我发了盒子枪，但是我没拿枪打过人。坐过轿子，可我坐轿子给轿夫给钱的。</p>

<p><strong>问：你前世几个儿子？现在也都70多岁了吧？</strong></p>

<p>华先生：有两个儿子，现在都已经过世了。</p>

<p><strong>问：他们有没有来看过你？</strong></p>

<p>华先生：二儿子在粉碎“四人帮”后带他的孩子来看过我。我1965年转世后，一岁就能说话，开始说前世的事。说的还很流利。村子里的人都认为我是神童，特别喜欢抱我出去玩，让我给他们讲以前的事，有时候天都黑了，都不送我回家，我妈天天满村子找我才把我抱回去。尤其是那些当地成份较高，过去给国民党干过事的人，爱给我糖果，喜欢问这问那，问的都是大人的事情，我都能说上。也有人故意考我，可都难不住我，许多都是他们也不知道的事情。他们一验证，我更加神了。知道的人多了，就开始传，全县的人都知道我是神童。开始在本村本公社传，最后传到外县去了。所以，我前世的家人也就知道了我的事。</p>

<p><strong>问：他们相信你是他们的亲人吗？</strong></p>

<p>华先生：相信。因为我说的事情都是前世家里的事情。地主家嘛，家口总比别人家大，亲戚也比别人家的多，名字关系我都能说上。由不得他们不信。我这一世的家离我前世的家也就五六十里，在一条沟里，隔了一条白龙江。又是山区，人少，所以两个村子都有亲戚相互来往。但是当时政策紧张，他们都很想见我，可不敢来找我相认。那是唯成份论的时代，他们成份高，怕给他们造成麻烦。后来又怕给我的前途造成影响。因为涉及上学、招工，考大学。我家是贫农，机会总比他们多些。我1965年转世，一岁多也就是1966、67年，正是文化大革命闹腾得最紧张的时候。我又是被枪毙的地主，谁敢来往啊。我前世的大儿子又是新社会共产党县政府的干部。我妈特别害怕我讲这些事，不让我说，可我还是不由得要说。我妈听人说，喝了黑狗、黑猫的血就不说了，我妈就到处找黑狗、黑猫的血硬让我喝。可是喝了也不管用，还是给人说。我妈就又把我吊在房粱上打，我还是说，也不管用。我妈有一个关系特别好的朋友，发洪水的时候淹死了。我妈老听我讲前世的事，也相信有鬼了，很害怕死了的这个朋友的鬼魂来找她，每天早早地就把门顶上。记得小时候有一次得重病，我妈要带我去枪毙了我的那个地方看病，我哭的怎么都不去。那是个乡镇府所在地，可我就是不去。</p>

<p><strong>问：你因为什么被枪毙呢？是哪一年？</strong></p>

<p>华先生：我是1958年被枪毙的，当时枪毙了两个人，我是以镇压反革命的名义被枪毙的。罪名主要有两条，第一，我有盒子枪，第二，我坐过轿子，压迫过贫下中农。</p>

<p><strong>问：你当时多大？</strong></p>

<p>华先生：50多岁，比我现在的年龄大一些。</p>

<p><strong>问：当时是怎么个情形？</strong></p>

<p>华先生：1958年全国大跃进，成立人民公社，阶级斗争开路，镇压反革命。我们那地方山大沟深，自然条件非常恶劣。人多地少，又全是山地，不打粮食。所以绝大多数老百姓都很贫困。也没有太大的地主，也没有太恶的人。可是也得完成上头的任务，就把我选上了。为了造声势，在枪毙的地方，召开十万人宣判大会，号称十万人参加。其实连三万人也没有。因为这个县到50年以后的现在才十来万人。不过当时在山区人就是是最多的了，人来一趟太不容易，都是翻山越岭，有的翻几架山，走上百里来开会。有的远处的人当天回不去，还要住附近村子亲戚家。不过，还是给我大儿子给了些面子，因为我大儿子是共产党的干部，当时就在县政府工作，所以没有在县上公审，把我拉到一个较大的一个乡，在那里枪毙了我。共产党也没有因我的事开除我大儿子。这一点还是很感谢共产党的。1958年以前，我们这个县叫西固县，以后才和我被枪毙的这个乡分开了，这个乡并到了另一个县。</p>

<p><strong>问：你一被枪毙，灵魂怎么走的？</strong></p>

<p>华先生：刚一枪毙，我的魂就出来了，向附近一个山梁跑去，我回身看了一下我的尸体，已经有人拿着馒头蘸我的血吃，旧社会的人认为这个办法可以治痨病，就是现在的肺结核。接着就有几个土红色的人来追我，想把我抓住，给我灌迷魂汤喝，我气愤无比，连骂带喊，沿着山梁拼命跑，当时我觉得自己死的很冤，哪里肯听，嘴里骂着，只管跑。跑了好长时间后，他们再也没追我。我为什么觉得冤，第一，我是带了枪，但是我从来没有打过一个人，没有人命案；第二，我也坐过轿子，但是我坐轿子是雇的轿夫，我给钱的，不算剥削。我没干过什么坏事，凭什么枪毙我？我想土红色的人，可能就是阴间的下层管理者，就是地狱里的鬼卒。从事灌迷魂汤、收容、登记、管理等差事，是阴间对暂时还没有超生的鬼魂分配有关差事，让他们给阴间服务。我还能记得前世，就是因为我没喝这个汤吧。不过，他们来的很快，就象是提前知道我在这里今天一定要死似的，早早地等在这里了。枪一响，他们马上就出现。我也马上就看见他们了。</p>

<p><strong>问：他们把你抓住了吗？</strong></p>

<p>华：没有。</p>

<p><strong>问：为什么？</strong></p>

<p>华：我想他们故意不抓的，因为他们笑嘻嘻的，好象没有认真地地抓。跑了一阵再没有使命地追。</p>

<p><strong>问：为什么你有这印象？</strong></p>

<p>我觉得他们是故意放了我一马。要追他们哪里能追不上呢。再说他们是阴兵还可以给你做法。比方说象电影上的，绐你吹一口气，手轻轻一煽，扔个法绳，念个咒什么的。再说他们好几个人呢。</p>

<p><strong>问：他们为什么这么做？</strong></p>

<p>华：我想有两个可能：一是他们知道我被冤枉的，同情我，不追了。二是他们故意让我清醒的，以便我在人间讲阴间的这些事情，教化百姓，让大家知道有地狱，有神有鬼。</p>

<p><strong>问：你分析的这个可能真有可能。你跑到哪里去了？</strong></p>

<p>华先生：我跑到了山上，无处栖身，后来找了一个崖上的山洞，藏了起来，藏了八年。这是转世后，根据年代算出来的。才知道在山洞里藏了八年。</p>

<p><strong>问：你饿吗？有冷暖的感觉吗？</strong></p>

<p>华先生：没有饿的感觉，但是有冷热的感觉。太冷了怕冷，太热了怕热。每天出去跑，跑累了回山洞休息。</p>

<p><strong>问：都说鬼道的天是灰蒙蒙的。</strong></p>

<p>华先生：这个我不记得了，没有关注过天气。</p>

<p><strong>问：就像我们人间一样，看看天气的时间总会有啊。华先生：可也就像人间一样，总不会老记着哪天天气怎么样吧！</strong></p>

<p><strong>问：您苦吗？都说鬼道的众生很苦？</strong></p>

<p>华先生：是啊！很苦啊！就是觉得自己死得冤。</p>

<p><strong>问：您都去过哪里呀？</strong></p>

<p>华先生：枪毙后，我向山上跑去，跑过几个山梁后，我感觉懵懵懂懂的，努力向前跑，就是过不去，原来这里有一个庙，到这儿就过不去了，只要一到庙那，就有一层雾腾腾的黑障拦住了。我就迷迷糊糊的，跑不过去，就回来。</p>

<p><strong>问：是不是从黑障往回跑就清醒了？</strong></p>

<p>华先生：是的。凡是有神庙的地方都过不去，我只能在那一坨地方行动，别的地方都去不了。土地庙也过不去。每一位神、每一个土地庙都管辖一片地方，你在这个神、这个土地管辖的地方，别的地方就去不了。即就是没有建神庙，就是随便在一个石头上、山包上插一个木牌位或者象征性地写一张纸牌位，都是管用的，你就过不去。从这里我也就知道了，再小的土地神也能管最厉害的鬼。</p>

<p><strong>陈老师：这个就说明立牌位很管用。</strong></p>

<p><strong>问：是啊。神、土地爷不照顾你吗？没叫你进庙里去？</strong></p>

<p>华先生：哪里有，神是不会主动把鬼招来照顾的。</p>

<p><strong>问：做鬼做了八年，怎么没去投胎啊？</strong></p>

<p>华先生：别的地方也去不了，不能去投胎。再一个，我是因为地主身份被枪毙的，所以我下决定发狠心再投胎一定要找一个特别穷的人家投。今后无论政策再紧张，也就不会再有被枪毙的危险了。1958年死后一直没投胎，就是一定要找一个穷人家投生。所以我就在这一片的山村里找合适的人。</p>

<p><strong>问：一直在找？</strong></p>

<p>华先生：一直在找。可都不合适。不是太富，就是残疾人，或者父母年龄太大。</p>

<p><strong>问：你见过阎王爷吗？</strong></p>

<p>华先生：没有，当时我骂骂咧咧地跑了，他们沒怎么再追，地府里也就没去。</p>

<p><strong>问：做鬼的时候见过其他鬼吗？有朋友吗？</strong></p>

<p>华先生：就像我们人间一样，人来人往的，不认识也不会去打招呼的，对吧？</p>

<p><strong>问：想过在世的亲人吗？</strong></p>

<p>华先生：没有，没有这个意识，就想着自己的事情。总觉得太冤枉了。</p>

<p><strong>问：也有嗔恨心。做鬼的时候做过坏事吗？</strong></p>

<p>华先生：其实，鬼在阴间不想害人，不想无事生非，遇见人都会主动避让的。只有一次，那是一个逢集日，我在集市上转，人很多，特别拥挤，无法避让，碰到一个人身上，把他灌的一斤煤油撞落了，当时瓶子在他背筐外边挂着的，路太窄，避不过，就碰落在地上摔碎了。就这一次，再没有过。在阴间时，我见到过一个老婆子死了后，她求阴间把她收下，阎王爷不要，下话都不要，阎王爷把她打发回去了。我转世后，我娘说咱们这儿有一个叫佛保娘的老婆子因为生活太苦实在活不下去了就上吊死了，可停尸停了七天家人打算入敛埋葬时又活过来了。这件事方圆村子里的人都知道，我娘一说名字我就知道我在阴间见过的就是她。我转世后有一次还和佛保娘说起我在阴间见过她，“佛保娘”说我在阴间看到的老婆子就是她。她重回人间后又活了二十多年，八十年代中期才去世。</p>

<p><strong>问：你当时在世的亲人给你烧过纸钱吗？收到没有？</strong></p>

<p>华先生：没有收到过。我死后埋在老家，不在我枪毙的地方，我过不去。魂没有跟着尸体回去。</p>

<p><strong>问：转世后，回去看过你的坟吗？</strong></p>

<p>华先生：没去过。</p>

<p><strong>问：你恨枪毙你的那些人吗？</strong></p>

<p>华先生：当然很生气。在当鬼时我到处游荡。一次游到安化公社的院子里，看到“四个兜”的公社干部在食堂吃饭，我就很气愤他们。一个干部抽烟，我就把他的烟打掉，另一个干部正端着碗吃饭，我就把他的饭碗给打到地上。</p>

<p><strong>生死书注：《佛说灌顶召五方龙王摄疫毒神咒上品经》节选：</strong>佛告阿难维耶离国中。所以遭此疫毒病者。是其国人多杀群生。无有慈心以杀猎为业。是诸獐鹿麋尘禽兽熊罴之属。有智慧者作是誓愿。愿我来世堕鬼神中。愿为鬼殃衔火烧人。有犯触我者若杀若缚。强取我者我当放火。烧其山野及所居村舍。于我有怨悉令被害。令诸众生不得藏匿。是故阿难当化导一切令其慈仁。勿杀群生普慈一切。受持禁戒行于十善。若能如此可得至道。</p>

<p><strong>问：他们知道是你干的吗？</strong></p>

<p>华先生：当然不知道，他们就觉得自己把烟没拿好，把饭碗没端好。</p>

<p><strong>高老师：所以，有时候人觉得哪里不对劲不知不觉干错了一件事，出了岔子，其实都是看不见的鬼魂在治我们呢。这些坏事你干的多吗？</strong></p>

<p>华先生：我的确是好鬼，八年里就干过前面说的这三件坏事，而且砸煤油瓶不是故意的，是避不过了。</p>

<p><strong>问：华先生，你怎么找到现在的母亲投胎的？</strong></p>

<p>华先生：我妈去本村的水泉来提水，我在我妈眼皮上打了一下，就附在我妈身上了。母亲家很穷，房屋破旧，穿着破烂，过着缺衣少食的生活，一家五六口人，度日如年。这个家庭原来富裕，后来衰败了，父亲长期有病，日子越过越穷。</p>

<p><strong>高老师：投胎是你自己决定的吗？</strong></p>

<p>华先生：是的。</p>

<p><strong>高老师：你附身附在什么地方？</strong></p>

<p>华先生：我妈的眼睛上。</p>

<p><strong>高老师：眼睛上也可以附身啊？</strong></p>

<p>华先生：是的。因为我打了母亲眼皮一下，以后我给我妈说了，我妈一点也不生我的气，她说，怪不得她的眼皮发三个月的炎。</p>

<p><strong>高老师：你家几个孩子，成了几个？</strong></p>

<p>华先生：我妈生了10个孩子，我是最小的一个，大姐75岁，有个哥哥63岁，现在健在的不多。中间有好几个兄长，因生活艰难困苦，在六十年代初，有饿死的，有得病死的，还有意外出事的。父亲在我很小时就去世了，我母亲她是1919年出生的。生我时已快50岁了，2002年去世的。活了83年。寿活的还是好着呢。</p>

<p><strong>问：你前世的亲人来看过你没有？</strong></p>

<p>华先生：文革结束了是一九七六年，第二年我的小老婆来看过我一次，我妈一看她的年龄比她都大，心里就非常不爱。她说了些很难听的话，没让她见，把她气走了。从此再没来过。说，看你这岁数，比我都大，能当他奶奶了。他才断了奶没几天，就算是你丈夫，是又能怎么样？不是又能怎样？见一见面能怎么样，无非再让大家陪着哭一哭。事情都过去快20年了，你又不能退回到当小媳妇的时候。这都是命啊，谁也没办法。他也没办法给你当男人去。他才11岁，他现在已是我的儿子了，你又不能把她领走，领走也没用，再说我也舍不得。他上学去了，学校不在我们村，中午不回来。你不见比见好，还是趁天早回去吧。咱这地方又没有班车，还要赶几十里路呢。就没让进门。她还带了些馍馍、杏子，我妈硬是没收。她哭着走了，从此以后再没来</p>

<p><strong>高老师：你还有小老婆啊？有几个老婆啊？大老婆呢？</strong></p>

<p>华先生：几个老婆不记得了，对大老婆没印象。我1973年上小学，过时间不长我二儿子带他的女儿来看我。他的女儿叫张有惠，有工作笔者想，若他真记不起来了，可见只有嗔恨心念念不忘。怪不得净空法师老教导大家，不能和任何人结冤。如今许多熄妇不孝敬公婆，矛盾很大，婆婆活着的时候把儿媳无可奈何，可死后儿媳会有好日子过吗？</p>

<p><strong>问：她现在在哪里工作啊？</strong></p>

<p>华先生：在我们县上保健站工作。</p>

<p><strong>问：她现在多大了，我们能去拜访一下吗？</strong></p>

<p>华先生：快60岁了，年纪也大了，比我现在年纪大几岁，不用去了。她对这个事情认可就行了，你们也不必见面了，见面还是讲这些过程。我们现在常常走动。我家里有什么大事时，她常带着她的丈夫和孩子来帮忙。她的爱人也在县上工作，是县医院医生，与我也很熟。我们过年过节常常聚会。他们都把我叫爷爷。我的大儿子，他们早就想来看我，但是政策紧张，都不敢来。以后都来过。张有惠跟她爸第一次来看我的时候，他们还给了我两块钱，当时我11岁了。前世老家在林区，木材多，二儿子还给我做了个木马勺，说让我上初中住校以后自己做饭用。当时我这一世的家生活困难的很，我二儿子主动说愿意供我上初中高中大学，再困难也要供。这本来是好意，是孝顺的表现。可我不知好呆，认为这是看不起我。给他们发脾气了。我告诉他们：“当初枪毙老子的时候，老子都没害怕，现在还要你供生活！死都没怕，生活上的困难不用你们管！”其实我说的是非常蛮横的大话，似乎我的死是他们造成的似的。二儿子、孙女听了这些不讲理的大话也没反驳，只默默流眼泪。长大以后我一直后悔当初我对他们的态度，说了这混帐话。后来两个儿子相继过世，我越法觉得对不起他们。</p>

<p><strong>高老师有点揶揄地问：你很有志气啊！你学习好吗？</strong></p>

<p>华先生：我的学习一直很好。</p>

<p><strong>问：您见过前世的熟人、老朋友吗？</strong></p>

<p>华先生：1978年秋，上初中开学报到那天，见到姜余福老师。他是初中班报到的负责人，他看到我签的姓名，二话没说，就把其他学生打发回去了，说今天不报到了，明天再来报到，把学生全打发走了。他把我留下，等其他学生都走完了，告诉我说我是他的老朋友，把我领到离学校不远的他家里聊天去了。当时他是个小地主，和我是一个乡的，给我交税。他说他以后在国民党天水高级步校学习毕业后，回到西固县，在国民党的县政府工作，以前和我常打交道，和我是老朋友。他说，其实我做地主的时候是一个很善良的人，是一个很好的人。他一解放就当了教师。文化大革命期间受到批斗，差点丢了公职。在解放前夕，他和部分人员以地下党的名义起义，文化大革命期间有人贴大字报说我们起义是假的，受到批斗，差点丢了公职。他此时已五十多岁，和我这才初中报到的小孩子我们聊了很多，他对我前世的事情记的比我还清楚，许多事情我许多都忘了。他那时虽然五十多岁，我才十二岁，可我们完全象两个同龄人一样聊的非常尽兴。结合我们完全忘了时间，我大哥见天黑了还没回家，急得跑了十多里地赶到学校找我，在晚上十点多，打问到我在姜余福老师家，直到见到我才放心了。</p>

<p>姜老师在八十年代初，组织上正式确认了他们的起义性质后落实政策时，就从学校调到到县人大任专职委员晋升为副县级干部，工作几年后按离休对待。十几年前已去世了。想起这我两世人生的一幕幕，常常让我唏嘘不已，不知是该笑该哭。</p>

<p>上初中的时候，学习科学社会主义常识，教材里写道：要树立马克思主义和无产阶级科学的世界观，胡说什么人沒有来世等等，当时，我看到后，无法向别人解释和理喻，就在此处备注了：“不懂就算了。别胡说八道。”</p>

<p>我初中在枪毙了我的那个地方念书，当年有个民兵连长外号叫蔫疙瘩，因额颅上有一肉痣，穿一身黑色中山装，枪毙我的时候，他维持秩序，是当时的积极分子，我认出他了。就非常恨他。还有，我转世的村有个年龄较大的女人都称地主老婆子，不知叫啥名，大家都这么叫，原来她家以前是当地的地主，她的丈夫是比较有名的地主，常与我叙说前世他们和我的交往，她有两个儿子，尤才、尤农。尤才有特长，会打篮球，60年代曾代表甘肃队在上海打球时，找了一个上海姑娘，以后调到兰州工作定居。现退休在兰州。我上小学时，已经八岁了，因为当时村公办小学有一位兰州下放来的老师，穿一身黑中山装，戴一副黑框眼镜，我莫名的害怕，直到这个老师调走，我才上学。</p>

<p><strong>问：您现在什么职位，做过那些工作？</strong></p>

<p>华先生：我大学一毕业就分到我们县上。因为我学过会计和审计，人事部门一看，县政府正需要财会专门人材，就把我直接留到县政府了，一般情况下，大学生回到县上肯定先到乡上工作。一留下就离不开了，直到大前年，才提拔到乡镇当过二年乡长。去年从乡长上调回县上后，现在在编制局当局长。</p>

<p><strong>陈老师：您信佛吗？</strong></p>

<p>华先生：我对神感兴趣，当然也信佛，因为有特殊的经历。我从不回避这一点。因为我被神管过八年。从这件事我就知道了各地有各地的神，在阴间神的级别层次跟阳间相似，官职有大有小，管理的范围也有大有小。坚信世界上有神有鬼有佛，我自己都当过八年的鬼，哪里能不信呢！</p>

<p><strong>问：你从什么时候开始不太说这些事了？</strong></p>

<p>华先生：上小学，学知识了，就不怎么说了。也知道有政策，说是唯心主义，就不说了。若私下也有人问，我也说。不问不自己说。我想提醒大家应该研究一下梦，梦就是一种信息记忆，跟讲前世一样，是一种信息的储存罢了，都属于生命科学研究的对象和范畴，像我说来世就是对前世信息的回忆而已，这是很客观的。作为一个自然人，为什么每个人每天都在做梦，无论古今中外，概莫能外，有些人醒来后，还能复述梦里发生的情况，有些人醒来后，知道做了梦，但记不清楚是什么，有些人被梦境惊醒，有些梦是以往发生过的事情，有些梦根本就风马牛不相及。对这一客观实在，至今不但没有人研究和解释明白，同时对说梦的人，也没有一个人带着阶级立场和政治色彩来指责，更没有人说是胡言乱语，因为持有阶级立场和政治色彩的指责者本人，也在天天做梦，他自己也搞不清楚，人的梦，究竟是从哪儿来的？是从天上掉下来的么？还是人的头脑当中所固有的？还是在社会实践和生产生活中得来的？所以，我认为，对没有研究和探究清楚的问题，不要轻易下结论，更不能以阶级立场、政治色彩、意识形态的不同来主观臆断，而应该以踏实科学的态度认真探究，如果以阶级立场、政治色彩、意识形态等主观意愿的划分来对待和研究客观现象和问题，本身就已深陷迷津，将永远得不到你所期望的结果。因为梦是一种自然现象，从来没有因为你是原始社会、奴隶社会、封建社会、资本主义社会、社会主义社会的形态和阶级立场及意识形态的不同，或者因为你受教育水平、知识结构、官职大小、从事工作、性别年龄等等的不同，让你做梦或不做梦，应该做什么梦。善良而睿智的人们，请你多一份踏实和认真，多一份科学的态度和努力，如果能将梦研究透了，我的这个事也就能解释了。</p>

<p><strong>问：您今世有几个孩子？</strong></p>

<p>华先生：一个孩子。</p>

<p><strong>问：现在在做什么？</strong></p>

<p>华先生：兰州理工大学毕业，去年回到县上，最近已考上公务员了。已经工作了。高处长，我的事差不多就这些了。</p>

<p><strong>高老师：谢谢你！非常感谢你接受我们的采访。</strong></p>

<p>采访到这里就结束了，时间对于我们灯红酒绿的城市来说夜生活才开始，但是对这个郁郁葱葱宁静的县城来说，夜，算是已经深了。与华先生挥手道别，朋友们送我们回到宾馆。</p>

<p>华先生的经历在他所在的县城几乎人尽皆知，熟人朋友常邀他讲当年做地主时的故事。不是不信鬼道存在的人们常说的“信则有，不信则无”。不过遗憾的是，想知道想核实的读者朋友们，可能只能等到华先生退休之后再去核实了。</p>

<p>在文章即将结束的时候，编辑部衷心感谢华先生不顾工作劳顿之后接受我们的采访。他的故事，再一次向我们证明了六道轮回的真实存在。《因果》杂志创办于甘肃，这个发生在甘肃南部县城的“再生人”故事具有了特殊的意义。感恩佛菩萨的慈悲加持！阿弥陀佛！</p>

<p>衷心感谢给我们提供线索的张局长，为《因果》杂志迎来开门红。编辑部欢迎各界朋友为我们提供具有因果教育意义的事件，我们会亲自核实，登载刊发。功德无量！感恩大家！阿弥陀佛！</p>

<p>最后，祝愿《因果》杂志的读者朋友们六时吉祥！光寿无量！道业增长！直趋觉路！顺利回家！阿弥陀佛！</p>

<p>此次采访去时9个小时，来时7个小时，可谓长途跋涉，但是终到目的地，行程圆满。</p>

<p>愿以此功德，庄严佛净土。<br>
上报四重恩，下济三途苦。<br>
若有见闻者，悉发菩提心。<br>
尽此一报身，同生极乐国。</p>"""
                post = Post(
                    title=title,
                    content=content,
                    cover_image='/static/images/hua_cover.jpg',
                    author_id=admin.id,
                    is_paid=True
                )
                db.session.add(post)
                db.session.commit()
                print("Article created.")
            except Exception as e2:
                db.session.rollback()
                print(f"Init DB: seed article insert failed: {e2}")

    except Exception as e:
        print(f"Init Data Error: {e}")

# 生产环境已移除：/api/debug/reset_db、/api/debug/seed（防止误开导致清库/刷数据）
# 数据库变更请使用 Flask-Migrate (alembic)，勿用 drop_all

def _check_receive_address():
    """启动时检查：未配置 RECEIVE_ADDRESS 时打印明确错误提示"""
    addr = app.config.get('BSC', {}).get('RECEIVE_ADDRESS')
    if not addr or not str(addr).strip():
        print('=' * 60)
        print('ERROR: RECEIVE_ADDRESS is not set or empty.')
        print('  Set RECEIVE_ADDRESS in .env (or environment) to enable:')
        print('  - Post fee collection')
        print('  - Tips and payout')
        print('  Example: RECEIVE_ADDRESS=0xYourBSCWalletAddress')
        print('=' * 60)

if __name__ == '__main__':
    # 表结构变更请使用 Flask-Migrate (alembic)，勿在生产环境使用 drop_all
    with app.app_context():
        db.create_all()
        init_db_data()
        _check_receive_address()
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=int(os.environ.get('PORT', 5001)))
else:
    # When running with Gunicorn, create tables if they don't exist
    with app.app_context():
        db.create_all()
        init_db_data()
        _check_receive_address()
# Force Update 2026