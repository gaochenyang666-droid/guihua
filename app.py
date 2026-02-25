import os
import re
import json
import traceback
import hashlib
import secrets
import threading
import bleach
import base64
import random
import time
from datetime import datetime, timedelta
from functools import wraps
from dotenv import load_dotenv
from flask import Flask, request, jsonify, g, render_template
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from web3 import Web3
try:
    from web3.middleware.geth_poa import geth_poa_middleware
except ImportError:
    from web3.middleware import geth_poa_middleware  # web3 v6
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

# SECRET_KEY 仅从环境变量读取，禁止写入本地文件（云环境 Ephemeral 盘会导致重启后 JWT 全部失效）
app.config['SECRET_KEY'] = (os.environ.get('SECRET_KEY') or '').strip()
if not app.config['SECRET_KEY']:
    raise ValueError("SECRET_KEY 未设置。请在环境变量中配置 SECRET_KEY 后启动应用。")

# BSC Mainnet Configuration（发帖费收 USDT BEP-20，打赏仍为 BNB）
BSC_RPC_LIST = [
    os.environ.get('BSC_RPC_URL', 'https://bsc-dataseed.binance.org/'),
    'https://bsc-dataseed1.defibit.io/',
    'https://bsc-dataseed1.ninicoin.io/',
    'https://bsc.publicnode.com'
]

# JWT 过期时间（小时）；上线后可按需改为 24
JWT_EXPIRY_HOURS = 24
# 支付校验：要求交易已被至少 N 个区块确认，防链重组假充值。BSC 约 3 秒/块，2 约 6 秒
TX_CONFIRMATIONS_NEEDED = 2
# 打赏平台抽成比例（7% 平台建设费，93% 给作者）
TIP_PLATFORM_FEE_PERCENT = 7
# 发帖费：1 人民币等值 USDT（取价失败时用 POST_FEE_USDT 兜底，单位 USDT）
POST_FEE_CNY = float(os.environ.get('POST_FEE_CNY', '1').strip() or '1')
POST_FEE_USDT_FALLBACK = float(os.environ.get('POST_FEE_USDT', '0.14').strip() or '0.14')
# BSC 主网 USDT 合约（Binance-Peg BSC-USD），18 位小数
USDT_CONTRACT_BSC = (os.environ.get('USDT_CONTRACT_ADDRESS') or '0x55d398326f99059fF775485246999027B3197955').strip()
USDT_DECIMALS = 18
app.config['BSC'] = {
    'RPC_URL': BSC_RPC_LIST[0],
    'CHAIN_ID': 56,
    'RECEIVE_ADDRESS': os.environ.get('RECEIVE_ADDRESS'),
    'USDT_CONTRACT_ADDRESS': USDT_CONTRACT_BSC,
    'USDT_DECIMALS': USDT_DECIMALS,
    'POST_FEE_CNY': POST_FEE_CNY,
    'POST_FEE_USDT_FALLBACK': POST_FEE_USDT_FALLBACK,
}
app.config['BSC_RPC_LIST'] = BSC_RPC_LIST
app.config['TX_CONFIRMATIONS_NEEDED'] = TX_CONFIRMATIONS_NEEDED
app.config['TIP_PLATFORM_FEE_PERCENT'] = TIP_PLATFORM_FEE_PERCENT
app.config['IMGBB_API_KEY'] = IMGBB_API_KEY
app.config['ARWEAVE_GATEWAY'] = ARWEAVE_GATEWAY

from extensions import db
db.init_app(app)

# 区块链与存储逻辑已拆至 services/blockchain.py、services/storage.py
from models import (User, Post, Vote, Comment, Like, Bookmark, Notification, UsedTransaction,
    UserVote, Tip, Report, build_comment_tree, _comment_to_dict_node, get_random_avatar, ALLOWED_AVATARS)
from utils.security import (_rate_limit, _bearer_token, _get_optional_jwt_payload,
    token_required, admin_required, bleach_clean_post_content as _bleach_clean_post_content)
from services.storage import (upload_to_imgbb, upload_to_arweave_native, upload_to_arweave_with_retry)
from services.blockchain import (get_working_web3, get_usdt_per_cny, get_post_fee_usdt_raw, verify_transaction)

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
    if _rate_limit('nonce', 30):
        return jsonify({'error': '请求过于频繁'}), 429
    address = request.args.get('address')
    if not address: return jsonify({'error': 'Missing address'}), 400
    
    try:
        address = Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
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
    if not data:
        return jsonify({'error': 'Invalid or empty JSON'}), 400
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')
    
    try:
        address = Web3.to_checksum_address(address)
    except (ValueError, AttributeError):
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
    # 支持两种格式：旧版 "Sign this message to login: {nonce}"，新版 "Sign this message to login to {host}: {nonce}"
    msg_stripped = (message or '').strip()
    expected_old = f"Sign this message to login: {user.nonce}"
    expected_new_prefix = "Sign this message to login to "
    expected_new_suffix = f": {user.nonce}"
    valid = (
        msg_stripped == expected_old
        or (msg_stripped.startswith(expected_new_prefix) and msg_stripped.endswith(expected_new_suffix))
    )
    if not valid:
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
        'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({'token': token, 'user': user.to_dict()})

@app.route('/api/auth/web2/register', methods=['POST'])
def register():
    if _rate_limit('register', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': '请使用 JSON 提交（Content-Type: application/json）'}), 400
        username = (data.get('username') or '').strip()
        password = (data.get('password') or '')
        if not username or not password:
            return jsonify({'error': '请填写用户名和密码'}), 400
        if len(username) > 50:
            return jsonify({'error': '用户名过长（最多50字）'}), 400
        if len(password) < 6:
            return jsonify({'error': '密码至少 6 位'}), 400
        if User.query.filter_by(username=username).first():
            return jsonify({'error': '该用户名已被注册，请换一个或直接登录'}), 400

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
            'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        
        return jsonify({'token': token, 'user': user.to_dict()}), 201
    except Exception as e:
        print(f"Register Error: {e}")
        return jsonify({'error': 'Registration failed'}), 500

@app.route('/api/auth/web2/login', methods=['POST'])
def login():
    if _rate_limit('login', 10):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid or empty JSON'}), 400
    username = (data.get('username') or '').strip()
    password = data.get('password')
    if not username:
        return jsonify({'error': '请填写用户名'}), 400
    if password is None:
        return jsonify({'error': '请填写密码'}), 400
    password = str(password).strip() if not isinstance(password, str) else password.strip()
    if not password:
        return jsonify({'error': '请填写密码'}), 400

    try:
        user = User.query.filter_by(username=username).first()
        if not user:
            return jsonify({'error': '用户名或密码错误'}), 401
        if not getattr(user, 'password_hash', None):
            return jsonify({'error': '该账号为钱包登录，请使用钱包登录'}), 401
        if not user.check_password(password):
            return jsonify({'error': '用户名或密码错误'}), 401
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(hours=JWT_EXPIRY_HOURS)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({'token': token, 'user': user.to_dict()})
    except Exception as e:
        print(f"Login Error: {e}")
        return jsonify({'error': '用户名或密码错误'}), 401

@app.route('/api/auth/web2/change-password', methods=['POST'])
def change_password_no_login():
    """找回/修改密码：凭账号和原密码即可设置新密码，无需登录。限流防撞库。"""
    if _rate_limit('change_password', 5):
        return jsonify({'error': '请求过于频繁，请稍后再试'}), 429
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
    if not data:
        return jsonify({'error': 'No data provided'}), 400
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
    if not data:
        return jsonify({'error': 'No data provided'}), 400
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
    fee_raw = get_post_fee_usdt_raw()
    decimals = app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_raw / (10 ** decimals), 4)
    return jsonify({
        'fee': str(fee_raw),
        'fee_currency': 'USDT',
        'fee_usdt': fee_usdt,
        'fee_cny': app.config['BSC']['POST_FEE_CNY'],
        'chain_id': app.config['BSC']['CHAIN_ID'],
        'receive_address': receive_address,
        'usdt_contract': app.config['BSC']['USDT_CONTRACT_ADDRESS'],
    })


@app.route('/api/config/public', methods=['GET'])
def get_public_config():
    """前端用：扫码登录等需 WalletConnect Project ID（从 https://cloud.walletconnect.com 申请）"""
    return jsonify({
        'walletconnect_project_id': os.environ.get('WALLETCONNECT_PROJECT_ID') or ''
    })

# --- Posts ---

@app.route('/api/search', methods=['GET'])
def search_posts():
    q = request.args.get('q', '').strip()
    if not q:
        return jsonify({'posts': []})
    if len(q) > 200:
        return jsonify({'error': 'Search query too long', 'posts': []}), 400
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
    
    fee_usdt_raw = get_post_fee_usdt_raw()
    decimals = app.config['BSC']['USDT_DECIMALS']
    fee_usdt = round(fee_usdt_raw / (10 ** decimals), 4)
    total_revenue_raw = web3_posts * fee_usdt_raw
    total_revenue_usdt = total_revenue_raw / (10 ** decimals)

    return jsonify({
        'users': {
            'total': total_users,
            'web3': web3_users,
            'web2': web2_users,
            'retention_rate': 'N/A'
        },
        'posts': {
            'total': total_posts,
            'web3': web3_posts,
            'web2': web2_posts
        },
        'revenue': {
            'total_usdt': round(total_revenue_usdt, 2),
            'fee_per_post_usdt': fee_usdt
        }
    })

@app.route('/api/users/<username>', methods=['GET'])
def get_user_profile(username):
    user = User.query.filter_by(username=username).first()
    if not user:
        if username.startswith('0x'):
            user = User.query.filter_by(address=username).first()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    payload = _get_optional_jwt_payload()
    current_user_id = payload.get('user_id') if payload else None

    posts = Post.query.filter_by(author_id=user.id, is_hidden=False).order_by(Post.created_at.desc()).all()
    post_ids = [p.id for p in posts]
    user_likes = set()
    user_bookmarks = set()
    like_counts = {}
    comment_counts = {}
    if post_ids:
        if current_user_id:
            user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
            user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
        like_rows = db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id).all()
        like_counts = {r[0]: r[1] for r in like_rows}
        comment_rows = db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all()
        comment_counts = {r[0]: r[1] for r in comment_rows}

    user_data = user.to_dict()
    user_data['posts_count'] = len(posts)
    posts_data = []
    for p in posts:
        p_dict = p.to_dict(
            current_user_id,
            likes_count=like_counts.get(p.id, 0),
            comments_count=comment_counts.get(p.id, 0)
        )
        p_dict['is_liked'] = p.id in user_likes
        p_dict['is_bookmarked'] = p.id in user_bookmarks
        posts_data.append(p_dict)

    return jsonify({
        'user': user_data,
        'posts': posts_data
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

def _get_posts_fallback(page, per_page, current_user_id):
    """兜底：仅查 posts 表，不 join users，避免缺列导致 500。返回 (posts_data, total, pages)。"""
    from sqlalchemy import text
    try:
        query = Post.query.filter_by(is_hidden=False).order_by(Post.created_at.desc())
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        posts = pagination.items
        total, pages = pagination.total, pagination.pages
    except Exception as e:
        print(f"[get_posts fallback] ORM query failed, using raw SQL: {e}")
        try:
            # 纯 SQL：列顺序与下方 p[0]/p[1]/... 下标一一对应；表结构变更时须同步改 SELECT 与解析逻辑
            off = (page - 1) * per_page
            rows = db.session.execute(text("""
                SELECT id, title, content, author_id, created_at, cover_image, images, view_count,
                       tx_hash, ipfs_cid, is_paid, region, is_on_chain, post_type, is_hidden, allow_comments,
                       is_repost, original_post_id, repost_comment
                FROM posts WHERE is_hidden = false ORDER BY created_at DESC LIMIT :lim OFFSET :off
            """), {'lim': per_page, 'off': off}).fetchall()
            total = db.session.execute(text("SELECT COUNT(*) FROM posts WHERE is_hidden = false")).scalar() or 0
            pages = max(1, (total + per_page - 1) // per_page)
            posts = rows
        except Exception as e2:
            print(f"[get_posts fallback] raw SQL failed: {e2}")
            try:
                rows = db.session.execute(text("""
                    SELECT id, title, content, author_id, created_at, cover_image, view_count
                    FROM posts WHERE is_hidden = false ORDER BY created_at DESC LIMIT :lim OFFSET :off
                """), {'lim': per_page, 'off': (page - 1) * per_page}).fetchall()
                total = db.session.execute(text("SELECT COUNT(*) FROM posts WHERE is_hidden = false")).scalar() or 0
                pages = max(1, (total + per_page - 1) // per_page)
                posts = rows
            except Exception as e3:
                print(f"[get_posts fallback] minimal SQL failed: {e3}")
                return [], 0, 1

    post_ids = [p.id if hasattr(p, 'id') else p[0] for p in posts]
    user_likes = set()
    user_bookmarks = set()
    if current_user_id and post_ids:
        try:
            user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
            user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
        except Exception:
            pass

    posts_data = []
    for p in posts:
        try:
            if hasattr(p, 'id'):
                pid, title, content, author_id = p.id, getattr(p, 'title', ''), getattr(p, 'content', ''), p.author_id
                created_at = p.created_at.isoformat() if getattr(p, 'created_at', None) else ''
                cover_image = getattr(p, 'cover_image', None)
                images_raw = getattr(p, 'images', None)
                view_count = getattr(p, 'view_count', 0)
                tx_hash = getattr(p, 'tx_hash', None)
                ipfs_cid = getattr(p, 'ipfs_cid', None)
                post_type = getattr(p, 'post_type', 0)
                is_repost = getattr(p, 'is_repost', False)
                original_post_id = getattr(p, 'original_post_id', None)
                repost_comment = getattr(p, 'repost_comment', None)
                is_hidden = getattr(p, 'is_hidden', False)
                allow_comments = getattr(p, 'allow_comments', True)
                region = getattr(p, 'region', '其他')
                is_on_chain = getattr(p, 'is_on_chain', False)
            else:
                r = p
                pid = r[0]
                title = r[1] or ''
                content = r[2] or ''
                author_id = r[3]
                created_at = r[4].isoformat() if r[4] else ''
                cover_image = r[5] if len(r) > 5 else None
                images_raw = r[6] if len(r) > 6 else None
                view_count = r[7] if len(r) > 7 else 0
                tx_hash = r[8] if len(r) > 8 else None
                ipfs_cid = r[9] if len(r) > 9 else None
                post_type = r[13] if len(r) > 13 else 0
                is_repost = r[16] if len(r) > 16 else False
                original_post_id = r[17] if len(r) > 17 else None
                repost_comment = r[18] if len(r) > 18 else None
                is_hidden = r[14] if len(r) > 14 else False
                allow_comments = r[15] if len(r) > 15 else True
                region = r[11] if len(r) > 11 else '其他'
                is_on_chain = r[12] if len(r) > 12 else False

            images_list = []
            if images_raw:
                try:
                    images_list = json.loads(images_raw) if isinstance(images_raw, str) else (images_raw or [])
                except (TypeError, ValueError):
                    pass
            likes_count = 0
            comments_count = 0
            votes_list = []
            try:
                likes_count = Like.query.filter_by(post_id=pid).count()
                comments_count = Comment.query.filter_by(post_id=pid).count()
                for v in Vote.query.filter_by(post_id=pid).all():
                    votes_list.append({'id': v.id, 'option_text': getattr(v, 'option_text', ''), 'vote_count': getattr(v, 'vote_count', 0)})
            except Exception:
                pass

            if cover_image and str(cover_image).strip() == '/static/images/hua_cover.jpg':
                cover_image = None
            posts_data.append({
                'id': pid,
                'title': title,
                'content': content,
                'cover_image': cover_image,
                'images': images_list,
                'author': {'id': author_id, 'nickname': '用户', 'avatar': '👻'},
                'view_count': view_count,
                'likes_count': likes_count,
                'comments_count': comments_count,
                'votes': votes_list,
                'is_liked': pid in user_likes,
                'is_bookmarked': pid in user_bookmarks,
                'tx_hash': tx_hash,
                'ipfs_cid': ipfs_cid,
                'post_type': post_type,
                'created_at': created_at,
                'is_repost': is_repost,
                'original_post_id': original_post_id,
                'original_post': None,
                'repost_comment': repost_comment,
                'is_hidden': is_hidden,
                'allow_comments': allow_comments,
                'region': region,
                'is_on_chain': is_on_chain,
            })
        except Exception as e:
            print(f"[get_posts fallback] skip row: {e}")
    return posts_data, total, pages

@app.route('/api/posts', methods=['GET'])
def get_posts():
    """帖子列表：内容来自 DB（Post.content），不请求 Arweave，无 content_arweave_id。"""
    payload = _get_optional_jwt_payload()
    current_user_id = payload.get('user_id') if payload else None

    sort_by = request.args.get('sort', 'new')
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)
    region = request.args.get('region')

    try:
        from sqlalchemy.orm import joinedload
        query = Post.query.options(joinedload(Post.author))
        if sort_by == 'bookmarks':
            if current_user_id:
                query = query.join(Bookmark, Post.id == Bookmark.post_id).filter(
                    Bookmark.user_id == current_user_id
                ).filter(Post.is_hidden == False).order_by(Post.created_at.desc())
            else:
                return jsonify({'posts': [], 'total': 0, 'pages': 0, 'current_page': page})
        else:
            query = query.order_by(Post.created_at.desc())
        if region:
            query = query.filter_by(region=region)
        current_user = User.query.get(current_user_id) if current_user_id else None
        if not current_user or not getattr(current_user, 'is_admin', False):
            if sort_by != 'bookmarks':
                query = query.filter_by(is_hidden=False)
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        posts = pagination.items
        post_ids = [p.id for p in posts]
        user_likes = set()
        user_bookmarks = set()
        like_counts = {}
        comment_counts = {}
        if post_ids:
            if current_user_id:
                user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
                user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
            like_rows = db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id).all()
            like_counts = {r[0]: r[1] for r in like_rows}
            comment_rows = db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all()
            comment_counts = {r[0]: r[1] for r in comment_rows}
        posts_data = []
        for p in posts:
            try:
                p_dict = p.to_dict(
                    current_user_id,
                    likes_count=like_counts.get(p.id, 0),
                    comments_count=comment_counts.get(p.id, 0)
                )
                p_dict['is_liked'] = p.id in user_likes
                p_dict['is_bookmarked'] = p.id in user_bookmarks
                posts_data.append(p_dict)
            except Exception as e:
                print(f"[get_posts] skip post id={getattr(p, 'id', None)}: {e}")
        return jsonify({'posts': posts_data, 'total': pagination.total, 'pages': pagination.pages, 'current_page': page})
    except Exception as e:
        traceback.print_exc()
        print(f"[get_posts] ERROR (using fallback): {e}")
        if sort_by == 'bookmarks':
            return jsonify({'posts': [], 'total': 0, 'pages': 0, 'current_page': page})
        try:
            posts_data, total, pages = _get_posts_fallback(page, per_page, current_user_id)
            return jsonify({'posts': posts_data, 'total': total, 'pages': pages, 'current_page': page})
        except Exception as e2:
            traceback.print_exc()
            print(f"[get_posts] fallback also failed: {e2}")
            return jsonify({'error': 'Failed to load posts', 'posts': [], 'total': 0, 'pages': 0, 'current_page': page}), 500

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
            cover_url, img_err = upload_to_imgbb(image_file)
            if not cover_url:
                return jsonify({'error': img_err or '封面上传失败'}), 500
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
        # JSON fallback（避免 get_json() 为 None 时 .get 报错）
        data = request.get_json() or {}
    
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
        # 管理员直接发帖：不上链、不支付，仅普通论坛帖；确保 tx_hash/ipfs_cid 为 None 避免 DB NOT NULL 报错
        tx_hash = None
        ipfs_cid = None
    else:
        # Regular User: 必须带 tx_hash，且经 verify_transaction 校验 to/from/value 与唯一性（min_amount = 1 USD 等值 BNB）
        if not tx_hash:
            return jsonify({'error': 'Transaction hash required'}), 400
        is_valid, error_msg = verify_transaction(tx_hash, g.current_user.address, min_amount=get_post_fee_usdt_raw(), payment_type='usdt')
        if not is_valid:
            return jsonify({'error': error_msg}), 400
            
        is_paid = True
        is_on_chain = True
        
        # 永存档案：支付后必须立即写入 Arweave（或 Pinata 兜底），否则不发帖；放行 img 的 src/alt/style/class 以保留正文内图片
        clean_content = _bleach_clean_post_content(data.get('content', ''))
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
        storage_id, storage_type, last_error = upload_to_arweave_with_retry(payload, retries=3)
        if not storage_id:
            print(f"[create_post] 永存档案写入失败: {last_error}")
            err_msg = '永存档案写入失败。您的支付已确认，无需再次支付，请稍后点击「重试发布」再试。'
            if last_error:
                err_msg += f' 原因: {last_error}'
            return jsonify({'error': err_msg, 'code': 'ARWEAVE_FAIL'}), 503
        ipfs_cid = storage_id

    # 防重复：保存前再次确认该交易哈希未被任何帖子使用（与 verify_transaction + unique 约束三重保险，防并发）
    if tx_hash:
        existing_post = Post.query.filter_by(tx_hash=tx_hash).first()
        if existing_post:
            return jsonify({'error': '该交易已用于其他帖子'}), 400

    # 4. Create Post（正文 HTML 允许 img 等，需放行 img 属性防 XSS）
    clean_content = _bleach_clean_post_content(data.get('content', ''))
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
        err_str = str(e).lower()
        if 'unique' in err_str and 'tx_hash' in err_str:
            return jsonify({'error': 'Transaction hash already used'}), 400
        # 管理员发帖常见：数据库 tx_hash/ipfs_cid 为 NOT NULL 时插 None 会报错
        if 'null' in err_str or 'not null' in err_str:
            print(f"Create Post DB Error (nullable?): {e}")
            traceback.print_exc()
            return jsonify({
                'error': '发帖失败：数据库字段不允许为空。请确认 posts 表的 tx_hash、ipfs_cid 列已设为允许 NULL（管理员发帖无需上链）。'
            }), 500
        print(f"Create Post DB Error: {e}")
        traceback.print_exc()
        return jsonify({'error': 'Database error'}), 500

    return jsonify({'message': 'Post created', 'post': post.to_dict()}), 201

# 浏览量防刷：同一 IP 对同一帖子 60 秒内只计一次
_view_count_key = {}
_view_count_ttl = 60

def _prune_view_count_keys(now):
    global _view_count_key
    expired = [k for k, t in _view_count_key.items() if now - t >= _view_count_ttl]
    for k in expired:
        _view_count_key.pop(k, None)

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    try:
        post = Post.query.get_or_404(post_id)
        # 浏览量 +1（同 IP 60 秒内仅计一次）
        try:
            ip = (request.remote_addr or 'unknown').strip()
            key = f"{post_id}:{ip}"
            now = time.time()
            _prune_view_count_keys(now)
            if key not in _view_count_key or now - _view_count_key[key] >= _view_count_ttl:
                _view_count_key[key] = now
                post.view_count = getattr(post, 'view_count', 0) or 0
                post.view_count += 1
                db.session.commit()
        except Exception:
            db.session.rollback()
        payload = _get_optional_jwt_payload()
        current_user_id = payload.get('user_id') if payload else None

        post_data = post.to_dict(current_user_id)
        if post_data.get('cover_image') and str(post_data['cover_image']).strip() == '/static/images/hua_cover.jpg':
            post_data['cover_image'] = None

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

@app.route('/api/posts/<int:post_id>/sync-arweave', methods=['POST'])
@token_required
def sync_post_to_arweave(post_id):
    """将已有帖子内容同步到 Arweave，生成永存档案（仅作者或管理员；帖子需有 tx_hash 且尚未有 ipfs_cid）。"""
    post = Post.query.get_or_404(post_id)
    if post.author_id != g.current_user.id and not getattr(g.current_user, 'is_admin', False):
        return jsonify({'error': '仅作者或管理员可操作'}), 403
    if not post.tx_hash:
        return jsonify({'error': '该帖子无支付凭证，无法同步到 Arweave'}), 400
    if post.ipfs_cid:
        return jsonify({'error': '该帖子已有永存档案', 'ipfs_cid': post.ipfs_cid}), 400
    author_address = (post.author.wallet_address or post.author.address or '').strip() if post.author else ''
    payload = {
        'title': post.title,
        'content': post.content or '',
        'cover_image': post.cover_image,
        'author': author_address,
        'timestamp': post.created_at.isoformat() if post.created_at else datetime.utcnow().isoformat(),
        'tx_hash': post.tx_hash,
        'region': getattr(post, 'region', '其他') or '其他',
        'platform': 'GuiHua Web3 (Arweave)'
    }
    ar_tx_id, _ = upload_to_arweave_native(payload)
    if not ar_tx_id:
        return jsonify({'error': 'Arweave 上传失败，请稍后重试'}), 503
    post.ipfs_cid = ar_tx_id
    db.session.commit()
    return jsonify({'message': '已同步到 Arweave', 'ipfs_cid': ar_tx_id, 'arweave_url': f'https://arweave.net/{ar_tx_id}'})

@app.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
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
    if not data:
        return jsonify({'error': 'No data provided'}), 400
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
    if not data:
        return jsonify({'error': 'No data provided'}), 400
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
        return jsonify({'error': '未选择文件'}), 400
    file = request.files['file']
    if not file or (getattr(file, 'filename', None) or '').strip() == '':
        return jsonify({'error': '未选择文件'}), 400
    url, err = upload_to_imgbb(file)
    if url:
        return jsonify({'url': url})
    return jsonify({'error': err or '上传失败'}), 500

# --- Admin & Debug ---

# 打赏最低 1 USDT（最小单位）
TIP_MIN_USDT_RAW = 10 ** USDT_DECIMALS

@app.route('/api/tips/verify', methods=['POST'])
@token_required
def verify_tip():
    """打赏直接转入作者钱包：验证 USDT 转至作者地址后仅记账（展示打赏记录），不经过平台、不抽成、不写入可提现余额。"""
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    tx_hash = data.get('tx_hash')
    post_id = data.get('post_id')
    if not tx_hash or not post_id:
        return jsonify({'error': 'Missing parameters'}), 400
    post = Post.query.get_or_404(post_id)
    if not post.author:
        return jsonify({'error': 'Post author not found'}), 400
    author_address = (post.author.wallet_address or post.author.address or '').strip()
    if not author_address or not Web3.is_address(author_address):
        return jsonify({'error': '作者未绑定钱包，暂无法打赏'}), 400
    is_valid, result = verify_transaction(
        tx_hash,
        g.current_user.address,
        expected_recipient=author_address,
        min_amount=TIP_MIN_USDT_RAW,
        payment_type='usdt'
    )
    if not is_valid:
        return jsonify({'error': result}), 400
    amount_full = int(result)
    if Tip.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': 'Tip already recorded'}), 400
    decimals = app.config['BSC']['USDT_DECIMALS']
    tip = Tip(
        tx_hash=tx_hash,
        from_user_id=g.current_user.id,
        to_user_id=post.author.id,
        post_id=post.id,
        amount=str(amount_full),
        payout_status='credited',
        payout_tx_hash='0xcredited'
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
    amount_usdt = amount_full / (10 ** decimals)
    return jsonify({
        'message': '打赏成功，已直接转入作者钱包',
        'tip': {
            'amount': str(amount_full),
            'tx_hash': tx_hash,
            'amount_usdt': round(amount_usdt, 2),
            'author_receives_usdt': round(amount_usdt, 2),
        }
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
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    title = data.get('title')
    content = data.get('content')
    
    if title:
        post.title = bleach.clean(title, strip=True)
    if content:
        post.content = _bleach_clean_post_content(content)
        
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

@app.route('/api/admin/posts/<int:post_id>/toggle-comments', methods=['POST'])
@token_required
@admin_required
def toggle_post_comments(post_id):
    """管理员切换帖子「允许评论」状态。与 POST .../comments（发表评论）区分开。"""
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

@app.route('/api/reports', methods=['POST'])
@token_required
def create_report():
    """用户举报帖子或用户。"""
    data = request.get_json() or {}
    post_id = data.get('post_id')
    reported_user_id = data.get('reported_user_id')
    reason = (data.get('reason') or '').strip()
    if not reason or len(reason) > 500:
        return jsonify({'error': '请填写举报原因（最多500字）'}), 400
    if not post_id and not reported_user_id:
        return jsonify({'error': '请指定举报的帖子或用户'}), 400
    if post_id:
        post = Post.query.get(post_id)
        if not post:
            return jsonify({'error': '帖子不存在'}), 404
        reported_user_id = post.author_id
    r = Report(
        reporter_id=g.current_user.id,
        reported_user_id=reported_user_id,
        post_id=post_id,
        reason=reason,
        status='pending'
    )
    db.session.add(r)
    db.session.commit()
    return jsonify({'message': '举报已提交，管理员会尽快处理', 'id': r.id}), 201

@app.route('/api/admin/reports', methods=['GET'])
@token_required
@admin_required
def list_reports():
    """管理员查看举报列表。"""
    status = request.args.get('status')
    q = Report.query.order_by(Report.created_at.desc())
    if status:
        q = q.filter_by(status=status)
    reports = q.limit(200).all()
    return jsonify([r.to_dict() for r in reports])

@app.route('/api/admin/reports/<int:report_id>', methods=['PUT'])
@token_required
@admin_required
def update_report(report_id):
    """管理员处理举报：status=resolved|dismissed, admin_notes=..."""
    r = Report.query.get_or_404(report_id)
    data = request.get_json() or {}
    if data.get('status') in ('resolved', 'dismissed'):
        r.status = data['status']
    if 'admin_notes' in data:
        r.admin_notes = (data['admin_notes'] or '')[:500]
    db.session.commit()
    return jsonify({'message': '已更新', 'report': r.to_dict()})

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
        # 管理员账号 siteadmin（密码 CHANGE_ME_ON_DEPLOY）
        admin_li = User.query.filter_by(username='siteadmin').first()
        if not admin_li:
            admin_li = User(
                username='siteadmin',
                nickname='siteadmin',
                is_admin=True,
                avatar='👤'
            )
            admin_li.set_password('CHANGE_ME_ON_DEPLOY')
            db.session.add(admin_li)
            try:
                db.session.commit()
                print("Admin siteadmin created.")
            except Exception as e:
                db.session.rollback()
                if 'unique' in str(e).lower() or 'IntegrityError' in type(e).__name__:
                    pass
                else:
                    print(f"Init Data Error (siteadmin): {e}")
        
        # 在 rollback 前保存 admin.id，避免 rollback 后访问 admin 触发 identity map 失效 (2j85)
        admin_id = getattr(admin, 'id', None) if admin else None
        if not admin_id:
            admin_id = User.query.filter(
                or_(User.username == 'AdminGao', User.is_admin == True)
            ).with_entities(User.id).scalar()
        db.session.rollback()
        title = '甘肃“再生人”华先生访问记'
        try:
            existing = Post.query.filter(Post.title.ilike('%华先生访问记%')).first()
        except Exception as e:
            print(f"Init DB: seed post check failed: {e}")
            existing = None
        if not existing and admin_id:
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
                    cover_image=None,
                    author_id=admin_id,
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

def _ensure_users_wallet_address():
    """启动时确保 users 表存在 wallet_address 列（Render 等可能为旧 schema）。仅在实际变更时打日志。"""
    from sqlalchemy import text
    if db.engine.dialect.name != 'postgresql':
        return
    try:
        r = db.session.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='wallet_address'"
        ))
        if r.scalar() is not None:
            return
        db.session.execute(text('ALTER TABLE users ADD COLUMN wallet_address VARCHAR(42)'))
        db.session.commit()
        print('[Startup] users.wallet_address added.')
    except Exception as e:
        db.session.rollback()
        if 'already exists' not in str(e).lower():
            print(f'[Startup] users.wallet_address skip: {e}')


def _ensure_users_withdrawable_balance():
    """启动时确保 users 表存在 withdrawable_balance 列。仅在实际变更时打日志。"""
    from sqlalchemy import text
    if db.engine.dialect.name != 'postgresql':
        return
    try:
        r = db.session.execute(text(
            "SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='withdrawable_balance'"
        ))
        if r.scalar() is not None:
            return
        db.session.execute(text("ALTER TABLE users ADD COLUMN withdrawable_balance VARCHAR(50) DEFAULT '0'"))
        db.session.commit()
        print('[Startup] users.withdrawable_balance added.')
    except Exception as e:
        db.session.rollback()
        if 'already exists' not in str(e).lower():
            print(f'[Startup] users.withdrawable_balance skip: {e}')

def _ensure_posts_tx_nullable():
    """启动时确保 posts.tx_hash、ipfs_cid 允许 NULL。仅在实际变更时打日志。"""
    from sqlalchemy import text
    if db.engine.dialect.name != 'postgresql':
        return
    for col in ('tx_hash', 'ipfs_cid'):
        try:
            r = db.session.execute(text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_name='posts' AND column_name=:col"
            ), {'col': col})
            row = r.fetchone()
            if not row or row[0] == 'YES':
                continue
            db.session.execute(text(f'ALTER TABLE posts ALTER COLUMN {col} DROP NOT NULL'))
            db.session.commit()
            print(f'[Startup] posts.{col} set nullable.')
        except Exception as e:
            db.session.rollback()
            if 'already' in str(e).lower() or 'does not exist' in str(e).lower():
                pass
            else:
                print(f'[Startup] posts.{col} nullable skip: {e}')

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

# 仅当设置 ALLOW_INIT_DB=true 时执行种子数据（避免每次重启都插测试文章；需造数时在 Render 临时加该环境变量）
def _should_run_init_db():
    return os.environ.get('ALLOW_INIT_DB', '').strip().lower() in ('true', '1', 'yes')

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        _ensure_users_wallet_address()
        _ensure_users_withdrawable_balance()
        _ensure_posts_tx_nullable()
        if _should_run_init_db():
            init_db_data()
        _check_receive_address()
    app.run(debug=os.environ.get('FLASK_DEBUG', 'false').lower() == 'true', port=int(os.environ.get('PORT', 5001)))
else:
    with app.app_context():
        db.create_all()
        _ensure_users_wallet_address()
        _ensure_users_withdrawable_balance()
        _ensure_posts_tx_nullable()
        if _should_run_init_db():
            init_db_data()
        _check_receive_address()