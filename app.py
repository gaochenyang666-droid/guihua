"""
诡境 - Web3 灵异事件分享平台
Flask 全栈版本 (Web3 重构版)
"""

import os
import re
import json
import secrets
import bleach
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, send_from_directory, render_template, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
import jwt
from werkzeug.utils import secure_filename
from web3 import Web3

from werkzeug.security import generate_password_hash, check_password_hash

# ============== 配置 ==============
app = Flask(__name__)

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///guijing_web3.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-secret-key-please-change-in-prod')

# BSC 配置 (测试网为例，生产环境请替换为主网 RPC)
app.config['BSC'] = {
    'RPC_URL': os.environ.get('BSC_RPC', 'https://data-seed-prebsc-1-s1.binance.org:8545'),
    'CHAIN_ID': 97,  # BSC Testnet ID (主网为 56)
    'RECEIVE_ADDRESS': os.environ.get('RECEIVE_ADDRESS', '0xYourWalletAddress'),  # 接收发帖费的地址
    'POST_FEE': Web3.to_wei(0.001, 'ether')  # 发帖费用：0.001 BNB
}

# 初始化 Web3
w3 = Web3(Web3.HTTPProvider(app.config['BSC']['RPC_URL']))

# 文件上传配置
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 初始化扩展
db = SQLAlchemy(app)
CORS(app)

# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ============== 数据模型 ==============


class User(db.Model):
    """用户模型 - 支持 Web3 钱包登录和 Web2 传统账号登录"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    # Web3 字段
    address = db.Column(db.String(42), unique=True, nullable=True, index=True)  # 钱包地址 (Web3 用户必填)
    nonce = db.Column(db.String(32), default=lambda: secrets.token_hex(16))  # 用于签名验证的随机数
    
    # Web2 字段
    username = db.Column(db.String(50), unique=True, nullable=True, index=True) # 用户名 (Web2 用户必填)
    password_hash = db.Column(db.String(255), nullable=True) # 密码哈希 (Web2 用户必填)
    
    # 通用字段
    nickname = db.Column(db.String(50))  # 昵称
    avatar = db.Column(db.String(500), default='/static/default-avatar.png')
    bio = db.Column(db.String(500), default='')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    has_nft_badge = db.Column(db.Boolean, default=False) # 是否已领取勋章

    # 关系
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def to_dict(self):
        # 确定用户类型
        user_type = 'web3' if self.address else 'web2'
        display_name = self.nickname or (self.address[:6] + '...' + self.address[-4:] if self.address else self.username)
        
        return {
            'id': self.id,
            'type': user_type,
            'address': self.address,
            'username': self.username,
            'nickname': display_name,
            'avatar': self.avatar,
            'bio': self.bio,
            'has_nft_badge': self.has_nft_badge,
            'posts_count': self.posts.count(),
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Post(db.Model):
    """帖子模型"""
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)  # 存储 HTML 格式内容
    images = db.Column(db.Text, default='[]')  # JSON数组存储图片URL
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    tx_hash = db.Column(db.String(66), unique=True, nullable=True)  # 关联的链上交易哈希
    ipfs_cid = db.Column(db.String(100), nullable=True) # IPFS 永存凭证
    is_paid = db.Column(db.Boolean, default=False)  # 是否已支付

    # 转发功能
    is_repost = db.Column(db.Boolean, default=False)  # 是否为转发贴
    original_post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    original_post = db.relationship('Post', remote_side=[id], backref='reposts')
    repost_comment = db.Column(db.Text, nullable=True)

    # 传统论坛功能保留
    view_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    # 关系
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='post', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def images_list(self):
        try:
            return json.loads(self.images) if self.images else []
        except:
            return []

    @images_list.setter
    def images_list(self, value):
        self.images = json.dumps(value)

    @property
    def likes_count(self):
        return self.likes.count()

    @property
    def comments_count(self):
        return self.comments.count()

    def to_dict(self, current_user_id=None):
        is_liked = False
        is_bookmarked = False
        if current_user_id:
            is_liked = Like.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            is_bookmarked = Bookmark.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None

        original_post_data = None
        if self.original_post:
            # 简单返回原帖摘要，避免无限递归
            original_post_data = {
                'id': self.original_post.id,
                'title': self.original_post.title,
                'content': self.original_post.content,
                'author': self.original_post.author.to_dict()
            }

        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'repost_comment': self.repost_comment,
            'original_post_id': self.original_post_id,
            'original_post': original_post_data,
            'images': self.images_list,
            'author': self.author.to_dict(),
            'likes_count': self.likes_count,
            'comments_count': self.comments_count,
            'view_count': self.view_count,
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'tx_hash': self.tx_hash,
            'ipfs_cid': self.ipfs_cid,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# 评论、点赞、收藏模型保持不变，作为传统 Web 功能保留
class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'content': self.content,
            'author': self.author.to_dict(),
            'post_id': self.post_id,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)


class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_bookmark'),)


# ============== 认证装饰器 ==============

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]

        if not token:
            return jsonify({'error': 'Token is missing'}), 401

        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = User.query.get(payload['user_id'])
            if not g.current_user:
                return jsonify({'error': 'User not found'}), 401
        except Exception as e:
            return jsonify({'error': 'Invalid token'}), 401

        return f(*args, **kwargs)

    return decorated


# ============== 工具函数 ==============

def upload_to_ipfs(content):
    """
    模拟上传到 IPFS (需要 Pinata API Key 或本地 IPFS 节点)
    实际开发中建议使用 ipfshttpclient 或 requests 调用 Pinata
    """
    try:
        # 这里模拟生成一个 CID
        mock_cid = f"Qm{secrets.token_hex(22)}"
        print(f"[IPFS] Uploaded content to IPFS: {mock_cid}")
        return mock_cid
    except Exception as e:
        print(f"[IPFS] Upload failed: {e}")
        return None

def mint_nft_badge(user_address):
    """
    模拟铸造 NFT 勋章 (需要拥有 Owner 权限的钱包私钥)
    实际开发中需调用合约 mint 方法
    """
    try:
        print(f"[NFT] Minting badge for {user_address}...")
        # contract = w3.eth.contract(address=NFT_CONTRACT_ADDRESS, abi=NFT_ABI)
        # tx = contract.functions.mint(user_address).buildTransaction(...)
        # signed_tx = w3.eth.account.sign_transaction(tx, private_key=ADMIN_PRIVATE_KEY)
        # w3.eth.send_raw_transaction(signed_tx.rawTransaction)
        return True
    except Exception as e:
        print(f"[NFT] Mint failed: {e}")
        return False

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ============== 前端页面路由 ==============

@app.route('/')
def index():
    return render_template('index.html')



# ============== API 路由 ==============

@app.route('/api/auth/web2/register', methods=['POST'])
def register_web2():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    if not username or not password:
        return jsonify({'error': '用户名和密码不能为空'}), 400
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已存在'}), 400
    
    user = User(username=username, nickname=username)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({'token': token, 'user': user.to_dict()}), 201

@app.route('/api/auth/web2/login', methods=['POST'])
def login_web2():
    data = request.get_json() or {}
    username = data.get('username')
    password = data.get('password')
    
    user = User.query.filter_by(username=username).first()
    
    if user and user.check_password(password):
        token = jwt.encode({
            'user_id': user.id,
            'exp': datetime.utcnow() + timedelta(days=7)
        }, app.config['SECRET_KEY'], algorithm='HS256')
        return jsonify({'token': token, 'user': user.to_dict()}), 200
    
    return jsonify({'error': '用户名或密码错误'}), 401

# ---------- Web3 认证 API ----------
@app.route('/api/auth/nonce', methods=['GET'])
def get_nonce():
    address = request.args.get('address')
    if not address:
        return jsonify({'error': '缺少地址参数'}), 400
    
    user = User.query.filter_by(address=address).first()
    if not user:
        user = User(address=address)
        db.session.add(user)
        db.session.commit()
    
    return jsonify({'nonce': user.nonce})


@app.route('/api/auth/verify', methods=['POST'])
def verify_signature():
    data = request.get_json()
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')

    if not address or not signature or not message:
        return jsonify({'error': '缺少必要参数'}), 400
    
    # 验证 nonce 是否匹配
    user = User.query.filter_by(address=address).first()
    
    # 从消息中提取 nonce
    try:
        nonce_in_msg = message.split('随机数: ')[1].strip()
    except:
        return jsonify({'error': '消息格式错误'}), 400

    if user:
        if user.nonce != nonce_in_msg:
            return jsonify({'error': '无效的随机数 (Nonce Mismatch)'}), 400
    
    # 验证签名
    try:
        from eth_account.messages import encode_defunct
        msg = encode_defunct(text=message)
        recovered_address = w3.eth.account.recover_message(msg, signature=signature)
        
        if recovered_address.lower() == address.lower():
            # 签名验证成功
            if not user:
                user = User(address=address)
                db.session.add(user)
            
            # 更新 nonce 防止重放攻击
            user.nonce = secrets.token_hex(16)
            db.session.commit()
            
            # 生成 Token
            token = jwt.encode({
                'user_id': user.id,
                'exp': datetime.utcnow() + timedelta(days=7)
            }, app.config['SECRET_KEY'], algorithm='HS256')
            
            return jsonify({'token': token, 'user': user.to_dict()}), 200
        else:
            return jsonify({'error': '签名验证失败'}), 401
    except Exception as e:
        print(f"Auth Error: {e}")
        return jsonify({'error': '验证过程出错'}), 500


# ---------- 系统配置 API ----------
@app.route('/api/config/fees', methods=['GET'])
def get_fees():
    return jsonify({
        'receive_address': app.config['BSC']['RECEIVE_ADDRESS'],
        'fee': app.config['BSC']['POST_FEE'],  # Wei 格式
        'chain_id': app.config['BSC']['CHAIN_ID']
    })


# ---------- 文件上传 API ----------
@app.route('/api/upload', methods=['POST'])
@token_required
def upload_image():
    # 仅 Web3 用户可上传
    if not g.current_user.address:
        return jsonify({'error': '仅限 Web3 用户上传'}), 403

    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # 添加随机前缀防止重名
        filename = f"{secrets.token_hex(8)}_{filename}"
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'url': f"/uploads/{filename}"}), 201
    return jsonify({'error': 'File type not allowed'}), 400


# ---------- 帖子 API ----------
@app.route('/api/posts', methods=['GET'])
def get_posts():
    # 处理可选 Token (为了获取点赞状态)
    token = None
    current_user_id = None
    if 'Authorization' in request.headers:
        auth_header = request.headers['Authorization']
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]
            try:
                payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
                current_user_id = payload['user_id']
            except:
                pass

    # 排序与过滤
    sort_by = request.args.get('sort', 'new')
    query = Post.query

    if sort_by == 'hot':
        # 按点赞数排序
        from sqlalchemy import func
        query = query.outerjoin(Like).group_by(Post.id).order_by(func.count(Like.id).desc())
    elif sort_by == 'bookmarks':
        if current_user_id:
            query = query.join(Bookmark).filter(Bookmark.user_id == current_user_id)
        else:
            # 未登录查看收藏列表返回空
            return jsonify({'posts': []})
    else: # 'new'
        query = query.order_by(Post.created_at.desc())

    posts = query.limit(20).all()
    return jsonify({'posts': [p.to_dict(current_user_id) for p in posts]})


@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    # 处理可选 Token
    token = None
    if 'Authorization' in request.headers:
        auth_header = request.headers['Authorization']
        if auth_header.startswith('Bearer '):
            token = auth_header[7:]

    if token:
        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = User.query.get(payload['user_id'])
        except:
            pass
    
    post = Post.query.get_or_404(post_id)
    post.view_count += 1
    db.session.commit()

    post_data = post.to_dict()
    
    # 增加评论列表
    post_data['comments'] = [c.to_dict() for c in post.comments]
    
    # 如果用户已登录，检查点赞/收藏状态
    if hasattr(g, 'current_user') and g.current_user:
        post_data['is_liked'] = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).count() > 0
        post_data['is_bookmarked'] = Bookmark.query.filter_by(user_id=g.current_user.id, post_id=post.id).count() > 0
    else:
        post_data['is_liked'] = False
        post_data['is_bookmarked'] = False
    
    return jsonify(post_data)


@app.route('/api/posts', methods=['POST'])
@token_required
def create_post():
    # 权限检查：必须是 Web3 用户才能发帖
    if not g.current_user.address:
        return jsonify({'error': '仅限 Web3 用户发帖'}), 403
    
    data = request.get_json() or {}
    tx_hash = data.get('tx_hash')

    # 1. 验证交易哈希是否已被使用 (防止双花/重放攻击)
    if not tx_hash:
        return jsonify({'error': '缺少交易哈希，请先支付'}), 400
    
    if Post.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': '该交易哈希已被使用'}), 400

    # 验证交易有效性 (生产环境应更严格验证金额和接收地址)
    try:
        tx = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        # 2. 验证交易状态 (确保交易已成功打包)
        if not receipt or receipt['status'] != 1:
            return jsonify({'error': '交易失败或未确认'}), 400

        # 简单验证：交易是否存在，且 from 是否为当前用户
        if tx and tx['from'].lower() == g.current_user.address.lower():
            # 验证接收地址和金额
            expected_to = app.config['BSC']['RECEIVE_ADDRESS'].lower()
            if not tx['to'] or tx['to'].lower() != expected_to:
                return jsonify({'error': '收款地址不正确'}), 400
            
            if tx['value'] < app.config['BSC']['POST_FEE']:
                return jsonify({'error': '支付金额不足'}), 400
        else:
            return jsonify({'error': '无效的交易证明'}), 400
    except Exception as e:
        print(f"Tx Check Error: {e}")
        return jsonify({'error': '交易查询失败，请稍后重试'}), 400

    content = data.get('content', '')
    
    # 3. XSS 防护：使用 bleach 清洗 HTML
    allowed_tags = ['b', 'i', 'u', 'em', 'strong', 'a', 'p', 'br', 'span', 'img', 'div', 'font']
    allowed_attrs = {
        '*': ['class'],
        'a': ['href', 'target'],
        'img': ['src', 'alt', 'width', 'height'],
        'font': ['color']
    }
    # 限制 style 仅允许安全属性，或者干脆禁用 style
    # 为了安全起见，暂时禁用 style，或仅允许极少数属性
    allowed_styles = [] 
    
    clean_content = bleach.clean(content, tags=allowed_tags, attributes=allowed_attrs, styles=allowed_styles, strip=True)

    # 上传到 IPFS 获得永存 CID
    ipfs_cid = upload_to_ipfs(json.dumps({
        'title': data.get('title'),
        'content': clean_content,
        'author': g.current_user.address,
        'timestamp': datetime.utcnow().isoformat()
    }))

    post = Post(
        title=data.get('title'),
        content=clean_content,
        images=json.dumps(data.get('images', [])),
        author_id=g.current_user.id,
        tx_hash=tx_hash,
        ipfs_cid=ipfs_cid,
        is_paid=True
    )
    db.session.add(post)
    
    # 检查是否满足 NFT 勋章条件 (例如发帖满10篇)
    # 注意：这里还没有 commit，所以当前这篇还不算在 posts.count() 里，需要手动+1
    if not g.current_user.has_nft_badge and g.current_user.posts.count() + 1 >= 10:
        if mint_nft_badge(g.current_user.address):
            g.current_user.has_nft_badge = True
            print(f"User {g.current_user.id} earned an NFT badge!")

    db.session.commit()

    return jsonify({'message': '发布成功', 'post': post.to_dict()}), 201


@app.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    data = request.get_json() or {}
    content = data.get('content', '')  # 转发附言
    
    # 查找原帖
    original_post = Post.query.get_or_404(post_id)
    
    # 如果原帖本身是转发，则转发其原始帖子
    target_id = original_post.original_post_id if original_post.original_post_id else post_id
    
    # XSS 防护 (清洗附言)
    clean_comment = bleach.clean(content, tags=[], strip=True) # 附言仅限纯文本

    new_post = Post(
        title=f"转发: {original_post.title}",
        content="", # 转发帖的内容通常为空，或用于存储快照。这里留空，展示时依赖 original_post
        repost_comment=clean_comment,
        author_id=g.current_user.id,
        is_repost=True,
        original_post_id=target_id,
        is_paid=True # 转发免费
    )
    
    db.session.add(new_post)
    db.session.commit()
    
    return jsonify(new_post.to_dict()), 201

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def add_comment(post_id):
    # 任何登录用户（Web2/Web3）均可评论
    data = request.get_json() or {}
    content = data.get('content')
    
    if not content:
        return jsonify({'error': '评论内容不能为空'}), 400
        
    post = Post.query.get_or_404(post_id)
    comment = Comment(content=content, author_id=g.current_user.id, post_id=post.id)
    db.session.add(comment)
    db.session.commit()
    
    return jsonify({'message': '评论成功', 'comment': comment.to_dict()}), 201


# ---------- 传统交互功能 API ----------
@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()

    if like:
        db.session.delete(like)
        message = '取消点赞'
    else:
        like = Like(user_id=g.current_user.id, post_id=post.id)
        db.session.add(like)
        message = '点赞成功'

    db.session.commit()
    # 重新加载 post 以获取最新的点赞数
    return jsonify({'message': message, 'likes_count': post.likes_count}), 200

@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    bookmark = Bookmark.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()

    if bookmark:
        db.session.delete(bookmark)
        message = '取消收藏'
    else:
        bookmark = Bookmark(user_id=g.current_user.id, post_id=post.id)
        db.session.add(bookmark)
        message = '收藏成功'

    db.session.commit()
    return jsonify({'message': message, 'bookmarks_count': post.bookmarks_count}), 200




@app.route('/api/user/me', methods=['GET'])
@token_required
def get_current_user():
    return jsonify(g.current_user.to_dict())

# ---------- 初始化 ----------
def init_db():
    with app.app_context():
        db.create_all()
        print(">>> Web3 Database Initialized")


if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000, debug=True)
