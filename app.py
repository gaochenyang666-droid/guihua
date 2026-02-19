import os
import re
import json
import secrets
import bleach
import requests
import base64
import random
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, render_template
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
from web3 import Web3
from web3.middleware.geth_poa import geth_poa_middleware

app = Flask(__name__)
CORS(app)

# ImgBB Configuration
IMGBB_API_KEY = os.environ.get('IMGBB_API_KEY', 'your-imgbb-api-key')

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///guijing.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-dev-secret-key-please-change-in-prod')
if not app.config['SECRET_KEY']:
    raise ValueError("No SECRET_KEY set for Flask application")

# BSC Testnet Configuration
app.config['BSC'] = {
    'RPC_URL': os.environ.get('BSC_RPC_URL', 'https://data-seed-prebsc-1-s1.binance.org:8545/'),
    'CHAIN_ID': 97,
    'RECEIVE_ADDRESS': os.environ.get('RECEIVE_ADDRESS', '0x0000000000000000000000000000000000000000'),
    'POST_FEE': Web3.to_wei(0.001, 'ether')
}

db = SQLAlchemy(app)
w3 = Web3(Web3.HTTPProvider(app.config['BSC']['RPC_URL']))
w3.middleware_onion.inject(geth_poa_middleware, layer=0)

# ============== Models ==============
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    address = db.Column(db.String(42), unique=True, nullable=True, index=True)
    nonce = db.Column(db.String(32), default=lambda: secrets.token_hex(16))
    username = db.Column(db.String(50), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    nickname = db.Column(db.String(50))
    avatar = db.Column(db.String(500), default='/static/default-avatar.png')
    bio = db.Column(db.String(500), default='')
    has_nft_badge = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    
    def set_password(self, password):
        self.password_hash = generate_password_hash(password)
        
    def check_password(self, password):
        return check_password_hash(self.password_hash, password)
    
    def to_dict(self):
        return {
            'id': self.id,
            'type': 'web3' if self.address else 'web2',
            'address': self.address,
            'username': self.username,
            'nickname': self.nickname or self.username or (self.address[:6] + '...' if self.address else 'Unknown'),
            'avatar': self.avatar,
            'has_nft_badge': self.has_nft_badge,
            'is_admin': self.is_admin,
            'posts_count': self.posts.count()
        }

class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    cover_image = db.Column(db.String(500), nullable=True)
    images = db.Column(db.Text) # JSON list
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    view_count = db.Column(db.Integer, default=0)
    tx_hash = db.Column(db.String(66), unique=True, nullable=True)
    ipfs_cid = db.Column(db.String(100), nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    
    # Admin controls
    is_hidden = db.Column(db.Boolean, default=False)
    allow_comments = db.Column(db.Boolean, default=True)

    # Repost logic
    is_repost = db.Column(db.Boolean, default=False)
    original_post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    repost_comment = db.Column(db.Text, nullable=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    likes = db.relationship('Like', backref='post', lazy='dynamic')
    original_post = db.relationship('Post', remote_side=[id], backref='reposts')
    
    def to_dict(self, current_user_id=None):
        images_list = json.loads(self.images) if self.images else []
        is_liked = False
        is_bookmarked = False
        if current_user_id:
            is_liked = Like.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            is_bookmarked = Bookmark.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            
        original_post_data = None
        if self.original_post:
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
            'cover_image': self.cover_image,
            'images': images_list,
            'author': self.author.to_dict(),
            'view_count': self.view_count,
            'likes_count': self.likes.count(),
            'comments_count': self.comments.count(),
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'tx_hash': self.tx_hash,
            'ipfs_cid': self.ipfs_cid,
            'created_at': self.created_at.isoformat(),
            'is_repost': self.is_repost,
            'original_post_id': self.original_post_id,
            'original_post': original_post_data,
            'repost_comment': self.repost_comment,
            'is_hidden': self.is_hidden,
            'allow_comments': self.allow_comments
        }

class Comment(db.Model):
    __tablename__ = 'comments'
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    author = db.relationship('User', backref='comments')
    
    def to_dict(self):
        return {
            'id': self.id,
            'content': self.content,
            'author': self.author.to_dict(),
            'created_at': self.created_at.isoformat()
        }

class Like(db.Model):
    __tablename__ = 'likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))

class Bookmark(db.Model):
    __tablename__ = 'bookmarks'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'))

# ============== Helpers ==============
def get_random_avatar():
    emojis = ['👻', '💀', '👽', '👾', '🤖', '🎃', '🧛', '🧟', '🧞', '🧝', '🧙', '🧚', '🧜', '👼', '👿', '👺', '👹', '🤡', '💩', '🦄']
    return random.choice(emojis)

def upload_to_imgbb(file):
    try:
        # Convert file to base64
        img_b64 = base64.b64encode(file.read()).decode('utf-8')
        # According to docs: don't add expiration for permanent storage
        payload = {
            "key": IMGBB_API_KEY,
            "image": img_b64
        }
        response = requests.post("https://api.imgbb.com/1/upload", data=payload)
        if response.status_code == 200:
            return response.json()['data']['url'] # Get image URL
        return None
    except Exception as e:
        print(f"ImgBB Error: {e}")
        return None

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            token = request.headers['Authorization'].split(" ")[1]
        if not token:
            return jsonify({'error': 'Token is missing'}), 401
        try:
            data = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = User.query.get(data['user_id'])
        except:
            return jsonify({'error': 'Token is invalid'}), 401
        return f(*args, **kwargs)
    return decorated

# ============== Routes ==============

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/studio')
def studio():
    return render_template('studio.html')

# --- Auth ---

@app.route('/api/auth/nonce', methods=['GET'])
def get_nonce():
    address = request.args.get('address')
    if not address: return jsonify({'error': 'Missing address'}), 400
    user = User.query.filter_by(address=address).first()
    if not user:
        # Create Web3 user if not exists
        user = User(address=address, nickname=f"User_{address[:6]}", avatar=get_random_avatar())
        db.session.add(user)
        db.session.commit()
    return jsonify({'nonce': user.nonce})

@app.route('/api/auth/verify', methods=['POST'])
def verify_signature():
    data = request.get_json()
    address = data.get('address')
    signature = data.get('signature')
    message = data.get('message')
    
    # In production, verify signature here using web3
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
    
    user = User.query.filter_by(address=address).first()
    if not user: return jsonify({'error': 'User not found'}), 404
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({'token': token, 'user': user.to_dict()})

@app.route('/api/auth/web2/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    
    if User.query.filter_by(username=username).first():
        return jsonify({'error': 'Username already exists'}), 400
        
    user = User(username=username, nickname=username, avatar=get_random_avatar())
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=7)
    }, app.config['SECRET_KEY'], algorithm='HS256')
    
    return jsonify({'token': token, 'user': user.to_dict()}), 201

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

@app.route('/api/user/me', methods=['GET'])
@token_required
def get_me():
    return jsonify(g.current_user.to_dict())

@app.route('/api/config/fees', methods=['GET'])
def get_fees():
    return jsonify({
        'fee': app.config['BSC']['POST_FEE'],
        'chain_id': app.config['BSC']['CHAIN_ID'],
        'receive_address': app.config['BSC']['RECEIVE_ADDRESS']
    })

# --- Posts ---

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
    query = Post.query

    if sort_by == 'hot':
        # Simple hot sort
        from sqlalchemy import func
        query = query.outerjoin(Like).group_by(Post.id).order_by(func.count(Like.id).desc())
    elif sort_by == 'bookmarks':
        if current_user_id:
            query = query.join(Bookmark).filter(Bookmark.user_id == current_user_id)
        else:
            return jsonify({'posts': []})
    else: # 'new'
        query = query.order_by(Post.created_at.desc())

    # Filter hidden posts unless admin
    current_user = None
    if current_user_id:
        current_user = User.query.get(current_user_id)
        
    if not current_user or not current_user.is_admin:
        query = query.filter_by(is_hidden=False)

    posts = query.limit(50).all()
    return jsonify({'posts': [p.to_dict(current_user_id) for p in posts]})

@app.route('/api/posts', methods=['POST'])
@token_required
def create_post():
    # Only Web3 users (with address) can post
    if not g.current_user.address:
        return jsonify({'error': 'Please connect wallet to post'}), 403
    
    # Check if multipart/form-data (for image upload)
    if 'image' in request.files:
        title = request.form.get('title')
        content = request.form.get('content')
        image_file = request.files.get('image')
        tx_hash = request.form.get('tx_hash')
        
        if not image_file:
            return jsonify({'error': 'Cover image is required'}), 400
            
        # Upload to ImgBB
        cover_url = upload_to_imgbb(image_file)
        if not cover_url:
            return jsonify({'error': 'Image upload failed'}), 500
            
        data = {
            'title': title,
            'content': content,
            'cover_image': cover_url,
            'tx_hash': tx_hash,
            'images': []
        }
    else:
        # JSON fallback (if client sends JSON with URL)
        data = request.get_json()
    
    tx_hash = data.get('tx_hash')
    
    # 1. Check duplicate tx
    if Post.query.filter_by(tx_hash=tx_hash).first():
        return jsonify({'error': 'Transaction hash already used'}), 400
        
    # 2. Verify tx on chain
    try:
        if not w3.is_connected():
             return jsonify({'error': 'RPC connection failed'}), 503

        tx = w3.eth.get_transaction(tx_hash)
        receipt = w3.eth.get_transaction_receipt(tx_hash)

        if not receipt or receipt['status'] != 1:
            return jsonify({'error': 'Transaction failed or pending'}), 400
            
        if tx and tx['from'].lower() == g.current_user.address.lower():
            expected_to = app.config['BSC']['RECEIVE_ADDRESS'].lower()
            if not tx['to'] or tx['to'].lower() != expected_to:
                return jsonify({'error': 'Incorrect recipient'}), 400
        else:
            return jsonify({'error': 'Invalid transaction'}), 400
    except Exception as e:
        print(f"Tx Error: {e}")
        return jsonify({'error': 'Verification failed'}), 400
    
    # 3. XSS Clean
    clean_content = bleach.clean(data.get('content', ''), tags=['b','i','u','img','p','br','div','span'], strip=True)
    
    post = Post(
        title=data.get('title'),
        content=clean_content,
        cover_image=data.get('cover_image'),
        images=json.dumps(data.get('images', [])),
        author_id=g.current_user.id,
        tx_hash=tx_hash,
        is_paid=True
    )
    db.session.add(post)
    db.session.commit()
    
    return jsonify({'message': 'Post created', 'post': post.to_dict()}), 201

@app.route('/api/posts/<int:post_id>', methods=['GET'])
def get_post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return jsonify(post.to_dict())

@app.route('/api/posts/<int:post_id>/repost', methods=['POST'])
@token_required
def repost_post(post_id):
    data = request.get_json()
    content = data.get('content', '')
    
    original_post = Post.query.get_or_404(post_id)
    target_id = original_post.original_post_id if original_post.original_post_id else post_id
    
    clean_comment = bleach.clean(content, tags=[], strip=True)

    new_post = Post(
        title=f"转发: {original_post.title}",
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

# --- Interactions ---

@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    if not post.allow_comments and not g.current_user.is_admin:
        return jsonify({'error': 'Comments are closed for this post'}), 403

    data = request.get_json()
    content = data.get('content')
    if not content: return jsonify({'error': 'Content empty'}), 400
    
    comment = Comment(content=content, author_id=g.current_user.id, post_id=post.id)
    db.session.add(comment)
    db.session.commit()
    return jsonify({'message': 'Comment added', 'comment': comment.to_dict()}), 201

@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    like = Like.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
    if like:
        db.session.delete(like)
        msg = 'Unliked'
    else:
        db.session.add(Like(user_id=g.current_user.id, post_id=post.id))
        msg = 'Liked'
    db.session.commit()
    return jsonify({'message': msg})

@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def bookmark_post(post_id):
    post = Post.query.get_or_404(post_id)
    bm = Bookmark.query.filter_by(user_id=g.current_user.id, post_id=post.id).first()
    if bm:
        db.session.delete(bm)
        msg = 'Unbookmarked'
    else:
        db.session.add(Bookmark(user_id=g.current_user.id, post_id=post.id))
        msg = 'Bookmarked'
    db.session.commit()
    return jsonify({'message': msg})

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

# --- Admin & Debug ---

@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(post_id):
    if not g.current_user.is_admin:
        return jsonify({'error': 'Admin only'}), 403
    
    post = Post.query.get_or_404(post_id)
    # Delete related
    Comment.query.filter_by(post_id=post.id).delete()
    Like.query.filter_by(post_id=post.id).delete()
    Bookmark.query.filter_by(post_id=post.id).delete()
    
    db.session.delete(post)
    db.session.commit()
    return jsonify({'message': 'Post deleted'})

@app.route('/api/posts/<int:post_id>/hide', methods=['PUT'])
@token_required
def toggle_hide_post(post_id):
    if not g.current_user.is_admin:
        return jsonify({'error': 'Admin only'}), 403
    
    post = Post.query.get_or_404(post_id)
    post.is_hidden = not post.is_hidden
    db.session.commit()
    return jsonify({'message': 'Toggled hide status', 'is_hidden': post.is_hidden})

@app.route('/api/posts/<int:post_id>/comments', methods=['PUT'])
@token_required
def toggle_post_comments(post_id):
    if not g.current_user.is_admin:
        return jsonify({'error': 'Admin only'}), 403
    
    post = Post.query.get_or_404(post_id)
    post.allow_comments = not post.allow_comments
    db.session.commit()
    return jsonify({'message': 'Toggled comments status', 'allow_comments': post.allow_comments})

@app.route('/api/debug/seed', methods=['POST'])
def seed_db():
    if not app.config.get('DEBUG') and os.environ.get('ENABLE_RESET_DB') != 'true':
        return jsonify({'error': 'Not allowed in production'}), 403
        
    try:
        # 1. Create Admin
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(username='admin', nickname='Admin👻', is_admin=True, avatar='👮')
            admin.set_password('admin123')
            db.session.add(admin)
            
        # 2. Create Test Users
        u1 = User(username='ghost_hunter', nickname='GhostHunter', avatar='🕵️')
        u1.set_password('123456')
        db.session.add(u1)
        
        db.session.commit()
        
        # 3. Create Posts
        posts_data = [
            {
                'title': '深夜的电梯',
                'content': '昨晚加班到12点，坐电梯下楼。电梯在14楼停了，门开了却没人。我正要关门，突然听到一声“等一下”...',
                'cover_image': 'https://i.ibb.co/hK7j00q/elevator.jpg',
                'author': admin
            },
            {
                'title': '镜子里的倒影',
                'content': '据说半夜两点对着镜子削苹果，能看到未来的另一半。我试了一下，结果看到了...',
                'cover_image': 'https://i.ibb.co/Qn9500q/mirror.jpg',
                'author': u1
            },
            {
                'title': '消失的末班车',
                'content': '375路公交车的传说，大家都听说过吧？那天我也上了一辆没有司机的车...',
                'cover_image': 'https://i.ibb.co/C0d400q/bus.jpg',
                'author': admin
            }
        ]
        
        for p in posts_data:
            if not Post.query.filter_by(title=p['title']).first():
                post = Post(
                    title=p['title'],
                    content=p['content'],
                    cover_image=p['cover_image'],
                    author_id=p['author'].id,
                    is_paid=True
                )
                db.session.add(post)
                
        db.session.commit()
        return jsonify({'message': 'Seeded successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/debug/reset_db', methods=['POST'])
def reset_db():
    if not app.config.get('DEBUG') and os.environ.get('ENABLE_RESET_DB') != 'true':
        return jsonify({'error': 'Not allowed in production'}), 403
    
    try:
        db.drop_all()
        db.create_all()
        return jsonify({'message': 'Database reset successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    # Auto-create tables (SQLite only, or dev env)
    # In production with PostgreSQL, use Flask-Migrate (alembic)
    with app.app_context():
        db.create_all()
    app.run(port=5000)
else:
    # When running with Gunicorn, create tables if they don't exist
    with app.app_context():
        db.create_all()
# Force Update 2026