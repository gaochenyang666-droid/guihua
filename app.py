# -*- coding: utf-8 -*-
"""
诡境 - 灵异事件分享平台
Flask 全栈版本 v4.0
"""

import os
import re
import json
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, send_from_directory, render_template_string
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_bcrypt import Bcrypt
import jwt
from werkzeug.utils import secure_filename

# ============== 配置 ==============
app = Flask(__name__)

# 数据库配置
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///guijing.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# 文件上传配置
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

# 初始化扩展
db = SQLAlchemy(app)
CORS(app)
bcrypt = Bcrypt(app)

# 创建上传目录
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)


# ============== 数据模型 ==============

class User(db.Model):
    """用户模型 - 包含角色管理"""
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False, index=True)
    email = db.Column(db.String(100), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(128), nullable=False)
    nickname = db.Column(db.String(50))
    avatar = db.Column(db.String(500), default='/static/default-avatar.png')
    bio = db.Column(db.String(500), default='')
    role = db.Column(db.String(20), default='user')  # user, admin, moderator
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    posts = db.relationship('Post', backref='author', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')

    @property
    def password(self):
        raise AttributeError('password is not a readable attribute')

    @password.setter
    def password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def verify_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'email': self.email,
            'nickname': self.nickname or self.username,
            'avatar': self.avatar,
            'bio': self.bio,
            'role': self.role,
            'is_active': self.is_active,
            'posts_count': self.posts.count(),
            'followers_count': Follow.query.filter_by(following_id=self.id).count(),
            'following_count': Follow.query.filter_by(follower_id=self.id).count(),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Post(db.Model):
    """帖子模型 - 包含自定义话题字段"""
    __tablename__ = 'posts'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    content = db.Column(db.Text, nullable=False)
    images = db.Column(db.Text, default='[]')  # JSON数组存储图片URL
    topics = db.Column(db.Text, default='[]')  # 自定义话题字段，JSON数组
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    is_published = db.Column(db.Boolean, default=True)
    is_pinned = db.Column(db.Boolean, default=False)
    view_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    comments = db.relationship('Comment', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    likes = db.relationship('Like', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    bookmarks = db.relationship('Bookmark', backref='post', lazy='dynamic', cascade='all, delete-orphan')
    post_tags = db.relationship('PostTag', backref='post', lazy='dynamic', cascade='all, delete-orphan')

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
    def topics_list(self):
        try:
            return json.loads(self.topics) if self.topics else []
        except:
            return []

    @topics_list.setter
    def topics_list(self, value):
        self.topics = json.dumps(value)

    @property
    def likes_count(self):
        return self.likes.count()

    @property
    def comments_count(self):
        return self.comments.count()

    @property
    def bookmarks_count(self):
        return self.bookmarks.count()

    @property
    def hot_score(self):
        """热度计算：综合考虑浏览、点赞、评论、时间衰减"""
        hours_passed = (datetime.utcnow() - self.created_at).total_seconds() / 3600
        time_decay = 1 / (1 + hours_passed / 24)  # 24小时半衰期
        return (
                    self.view_count * 0.1 + self.likes_count * 2 + self.comments_count * 3 + self.bookmarks_count * 1.5) * time_decay

    def to_dict(self, current_user_id=None):
        # 获取标签
        tags = [pt.tag.name for pt in self.post_tags.all()]

        # 检查当前用户是否点赞/收藏
        is_liked = False
        is_bookmarked = False
        if current_user_id:
            is_liked = Like.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None
            is_bookmarked = Bookmark.query.filter_by(user_id=current_user_id, post_id=self.id).first() is not None

        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'images': self.images_list,
            'topics': self.topics_list,
            'author': self.author.to_dict(),
            'tags': tags,
            'likes_count': self.likes_count,
            'comments_count': self.comments_count,
            'bookmarks_count': self.bookmarks_count,
            'view_count': self.view_count,
            'hot_score': round(self.hot_score, 2),
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'is_published': self.is_published,
            'is_pinned': self.is_pinned,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Comment(db.Model):
    """评论模型"""
    __tablename__ = 'comments'

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    parent_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 自引用关系（回复）
    replies = db.relationship('Comment', backref=db.backref('parent', remote_side=[id]), lazy='dynamic')

    @property
    def replies_count(self):
        return self.replies.count()

    def to_dict(self, current_user_id=None):
        return {
            'id': self.id,
            'content': self.content,
            'author': self.author.to_dict(),
            'post_id': self.post_id,
            'parent_id': self.parent_id,
            'replies_count': self.replies_count,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }


class Tag(db.Model):
    """标签模型"""
    __tablename__ = 'tags'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False, index=True)
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def posts_count(self):
        return PostTag.query.filter_by(tag_id=self.id).count()

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description,
            'posts_count': self.posts_count,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


class PostTag(db.Model):
    """帖子-标签关联"""
    __tablename__ = 'post_tags'

    id = db.Column(db.Integer, primary_key=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    tag_id = db.Column(db.Integer, db.ForeignKey('tags.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    tag = db.relationship('Tag', backref='post_tags')


class Like(db.Model):
    """点赞模型"""
    __tablename__ = 'likes'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_like'),)


class Bookmark(db.Model):
    """收藏模型"""
    __tablename__ = 'bookmarks'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('user_id', 'post_id', name='unique_bookmark'),)


class Follow(db.Model):
    """关注模型"""
    __tablename__ = 'follows'

    id = db.Column(db.Integer, primary_key=True)
    follower_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    following_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('follower_id', 'following_id', name='unique_follow'),)


# ============== 认证装饰器 ==============

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        # 从Header获取token
        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]

        # 从Cookie获取token
        if not token and 'token' in request.cookies:
            token = request.cookies.get('token')

        if not token:
            return jsonify({'error': 'Token is missing', 'code': 'TOKEN_MISSING'}), 401

        try:
            payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
            g.current_user = User.query.get(payload['user_id'])
            if not g.current_user:
                return jsonify({'error': 'User not found', 'code': 'USER_NOT_FOUND'}), 401
            if not g.current_user.is_active:
                return jsonify({'error': 'User is inactive', 'code': 'USER_INACTIVE'}), 403
        except jwt.ExpiredSignatureError:
            return jsonify({'error': 'Token has expired', 'code': 'TOKEN_EXPIRED'}), 401
        except jwt.InvalidTokenError:
            return jsonify({'error': 'Invalid token', 'code': 'TOKEN_INVALID'}), 401

        return f(*args, **kwargs)

    return decorated


def admin_required(f):
    @wraps(f)
    @token_required
    def decorated(*args, **kwargs):
        if g.current_user.role != 'admin':
            return jsonify({'error': 'Admin access required', 'code': 'ADMIN_REQUIRED'}), 403
        return f(*args, **kwargs)

    return decorated


def optional_token(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None

        if 'Authorization' in request.headers:
            auth_header = request.headers['Authorization']
            if auth_header.startswith('Bearer '):
                token = auth_header[7:]

        if not token and 'token' in request.cookies:
            token = request.cookies.get('token')

        g.current_user = None
        if token:
            try:
                payload = jwt.decode(token, app.config['SECRET_KEY'], algorithms=['HS256'])
                g.current_user = User.query.get(payload['user_id'])
            except:
                pass

        return f(*args, **kwargs)

    return decorated


# ============== 工具函数 ==============

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def sanitize_input(text, max_length=None):
    """XSS防护：清理用户输入"""
    if not text:
        return text
    # 移除危险HTML标签
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<iframe[^>]*>.*?</iframe>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'javascript:', '', text, flags=re.IGNORECASE)
    text = re.sub(r'on\w+\s*=', '', text, flags=re.IGNORECASE)
    if max_length:
        text = text[:max_length]
    return text.strip()


def validate_image_url(url):
    """验证图片URL安全性"""
    if not url:
        return False
    # 只允许http/https/data协议
    if not re.match(r'^(https?://|data:image/)', url):
        return False
    return True


# ============== 前端页面路由 ==============

INDEX_HTML = '''
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>诡境 - 灵异事件分享平台</title>
    <style>
        /* ============== 基础重置 ============== */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        :root {
            --bg-primary: #0a0a0f;
            --bg-secondary: #12121a;
            --bg-card: #1a1a25;
            --text-primary: #e5e5e5;
            --text-secondary: #8b8b9e;
            --accent-purple: #7c3aed;
            --accent-purple-dark: #5b21b6;
            --accent-green: #10b981;
            --accent-red: #ef4444;
            --border-color: #2d2d3d;
            --shadow-glow: 0 0 20px rgba(124, 58, 237, 0.3);
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            line-height: 1.6;
        }

        /* ============== 鬼火动画 ============== */
        @keyframes ghostFire {
            0%, 100% { opacity: 0.4; transform: translateY(0) scale(1); }
            50% { opacity: 0.8; transform: translateY(-10px) scale(1.1); }
        }

        @keyframes floatUp {
            0% { transform: translateY(100vh) scale(0); opacity: 0; }
            50% { opacity: 1; }
            100% { transform: translateY(-100vh) scale(1); opacity: 0; }
        }

        .ghost-fire {
            position: fixed;
            width: 4px;
            height: 4px;
            background: var(--accent-green);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--accent-green), 0 0 20px var(--accent-green);
            animation: floatUp 8s infinite ease-in-out;
            pointer-events: none;
            z-index: 1;
        }

        /* ============== 顶部导航 ============== */
        .navbar {
            position: sticky;
            top: 0;
            background: rgba(10, 10, 15, 0.95);
            backdrop-filter: blur(10px);
            border-bottom: 1px solid var(--border-color);
            padding: 0.75rem 1.5rem;
            z-index: 100;
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 1rem;
        }

        .logo {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            font-size: 1.5rem;
            font-weight: 700;
            color: var(--accent-purple);
            text-decoration: none;
        }

        .logo-icon {
            font-size: 1.8rem;
            animation: ghostFire 2s infinite;
        }

        .search-box {
            flex: 1;
            max-width: 500px;
            position: relative;
        }

        .search-box input {
            width: 100%;
            padding: 0.6rem 1rem 0.6rem 2.5rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            color: var(--text-primary);
            font-size: 0.9rem;
            transition: all 0.3s;
        }

        .search-box input:focus {
            outline: none;
            border-color: var(--accent-purple);
            box-shadow: 0 0 0 2px rgba(124, 58, 237, 0.2);
        }

        .search-box::before {
            content: "🔍";
            position: absolute;
            left: 0.8rem;
            top: 50%;
            transform: translateY(-50%);
            font-size: 0.9rem;
        }

        .nav-actions {
            display: flex;
            align-items: center;
            gap: 0.75rem;
        }

        .btn {
            padding: 0.5rem 1rem;
            border-radius: 20px;
            font-size: 0.85rem;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.3s;
            border: none;
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            gap: 0.3rem;
        }

        .btn-ghost {
            background: transparent;
            color: var(--text-secondary);
            border: 1px solid var(--border-color);
        }

        .btn-ghost:hover {
            color: var(--text-primary);
            border-color: var(--accent-purple);
        }

        .btn-primary {
            background: var(--accent-purple);
            color: white;
        }

        .btn-primary:hover {
            background: var(--accent-purple-dark);
            box-shadow: var(--shadow-glow);
        }

        .btn-danger {
            background: var(--accent-red);
            color: white;
        }

        .user-avatar {
            width: 36px;
            height: 36px;
            border-radius: 50%;
            object-fit: cover;
            border: 2px solid var(--accent-purple);
            cursor: pointer;
        }

        /* ============== 主容器 ============== */
        .main-container {
            max-width: 1400px;
            margin: 0 auto;
            padding: 1.5rem;
            display: grid;
            grid-template-columns: 240px 1fr 280px;
            gap: 1.5rem;
            position: relative;
            z-index: 2;
        }

        @media (max-width: 1200px) {
            .main-container {
                grid-template-columns: 200px 1fr;
            }
            .right-sidebar {
                display: none;
            }
        }

        @media (max-width: 900px) {
            .main-container {
                grid-template-columns: 1fr;
            }
            .left-sidebar {
                display: none;
            }
        }

        /* ============== 侧边栏 ============== */
        .sidebar {
            position: sticky;
            top: 80px;
            height: fit-content;
        }

        .sidebar-card {
            background: var(--bg-card);
            border-radius: 12px;
            padding: 1rem;
            margin-bottom: 1rem;
            border: 1px solid var(--border-color);
        }

        .sidebar-title {
            font-size: 0.9rem;
            font-weight: 600;
            color: var(--text-secondary);
            margin-bottom: 0.75rem;
            padding-bottom: 0.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .nav-menu {
            list-style: none;
        }

        .nav-item {
            padding: 0.6rem 0.8rem;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 0.6rem;
            color: var(--text-secondary);
            font-size: 0.9rem;
        }

        .nav-item:hover {
            background: var(--bg-secondary);
            color: var(--text-primary);
        }

        .nav-item.active {
            background: rgba(124, 58, 237, 0.15);
            color: var(--accent-purple);
        }

        .tag-list {
            display: flex;
            flex-wrap: wrap;
            gap: 0.5rem;
        }

        .tag-item {
            padding: 0.3rem 0.6rem;
            background: var(--bg-secondary);
            border-radius: 12px;
            font-size: 0.8rem;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
        }

        .tag-item:hover {
            background: var(--accent-purple);
            color: white;
        }

        /* ============== 瀑布流布局 ============== */
        .masonry-grid {
            column-count: 2;
            column-gap: 1rem;
        }

        @media (min-width: 768px) {
            .masonry-grid {
                column-count: 3;
            }
        }

        @media (min-width: 1200px) {
            .masonry-grid {
                column-count: 4;
            }
        }

        .post-card {
            break-inside: avoid;
            margin-bottom: 1rem;
            background: var(--bg-card);
            border-radius: 12px;
            overflow: hidden;
            border: 1px solid var(--border-color);
            transition: all 0.3s;
            cursor: pointer;
        }

        .post-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 30px rgba(124, 58, 237, 0.15);
            border-color: var(--accent-purple);
        }

        .post-image {
            width: 100%;
            display: block;
            transition: transform 0.3s;
        }

        .post-card:hover .post-image {
            transform: scale(1.02);
        }

        .post-content {
            padding: 0.8rem;
        }

        .post-title {
            font-size: 0.95rem;
            font-weight: 600;
            color: var(--text-primary);
            margin-bottom: 0.5rem;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }

        .post-excerpt {
            font-size: 0.8rem;
            color: var(--text-secondary);
            display: -webkit-box;
            -webkit-line-clamp: 3;
            -webkit-box-orient: vertical;
            overflow: hidden;
            margin-bottom: 0.6rem;
        }

        .post-meta {
            display: flex;
            align-items: center;
            justify-content: space-between;
            font-size: 0.75rem;
            color: var(--text-secondary);
        }

        .post-author {
            display: flex;
            align-items: center;
            gap: 0.4rem;
        }

        .post-author img {
            width: 20px;
            height: 20px;
            border-radius: 50%;
        }

        .post-stats {
            display: flex;
            gap: 0.8rem;
        }

        .stat-item {
            display: flex;
            align-items: center;
            gap: 0.2rem;
        }

        .stat-item.liked {
            color: var(--accent-red);
        }

        .stat-item.bookmarked {
            color: var(--accent-green);
        }

        .topic-tag {
            display: inline-block;
            padding: 0.2rem 0.5rem;
            background: rgba(124, 58, 237, 0.2);
            color: var(--accent-purple);
            border-radius: 10px;
            font-size: 0.7rem;
            margin-right: 0.3rem;
            margin-bottom: 0.3rem;
        }

        /* ============== 模态框 ============== */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0, 0, 0, 0.8);
            display: none;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            padding: 1rem;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal {
            background: var(--bg-card);
            border-radius: 16px;
            max-width: 480px;
            width: 100%;
            max-height: 90vh;
            overflow-y: auto;
            border: 1px solid var(--border-color);
        }

        .modal-header {
            padding: 1.2rem 1.5rem;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .modal-title {
            font-size: 1.1rem;
            font-weight: 600;
        }

        .modal-close {
            background: none;
            border: none;
            font-size: 1.5rem;
            color: var(--text-secondary);
            cursor: pointer;
            line-height: 1;
        }

        .modal-body {
            padding: 1.5rem;
        }

        .form-group {
            margin-bottom: 1rem;
        }

        .form-label {
            display: block;
            font-size: 0.85rem;
            color: var(--text-secondary);
            margin-bottom: 0.4rem;
        }

        .form-input {
            width: 100%;
            padding: 0.7rem 1rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            color: var(--text-primary);
            font-size: 0.9rem;
            transition: all 0.3s;
        }

        .form-input:focus {
            outline: none;
            border-color: var(--accent-purple);
        }

        .form-textarea {
            min-height: 100px;
            resize: vertical;
        }

        /* ============== 帖子详情模态框 ============== */
        .post-detail-modal .modal {
            max-width: 800px;
        }

        .post-detail-header {
            padding: 1.5rem;
            border-bottom: 1px solid var(--border-color);
        }

        .post-detail-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 0.8rem;
        }

        .post-detail-meta {
            display: flex;
            align-items: center;
            gap: 1rem;
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .post-detail-author {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .post-detail-author img {
            width: 32px;
            height: 32px;
            border-radius: 50%;
        }

        .post-detail-content {
            padding: 1.5rem;
        }

        .post-detail-content img {
            max-width: 100%;
            border-radius: 8px;
            margin-bottom: 1rem;
        }

        .post-detail-text {
            white-space: pre-wrap;
            line-height: 1.8;
        }

        .post-detail-actions {
            display: flex;
            gap: 1rem;
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border-color);
            border-bottom: 1px solid var(--border-color);
        }

        .action-btn {
            display: flex;
            align-items: center;
            gap: 0.4rem;
            padding: 0.5rem 1rem;
            background: var(--bg-secondary);
            border: none;
            border-radius: 20px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
        }

        .action-btn:hover {
            color: var(--text-primary);
        }

        .action-btn.active.like {
            background: rgba(239, 68, 68, 0.2);
            color: var(--accent-red);
        }

        .action-btn.active.bookmark {
            background: rgba(16, 185, 129, 0.2);
            color: var(--accent-green);
        }

        /* ============== 评论区域 ============== */
        .comments-section {
            padding: 1.5rem;
            max-height: 300px;
            overflow-y: auto;
        }

        .comment-item {
            display: flex;
            gap: 0.8rem;
            margin-bottom: 1rem;
        }

        .comment-item img {
            width: 28px;
            height: 28px;
            border-radius: 50%;
            flex-shrink: 0;
        }

        .comment-content {
            flex: 1;
        }

        .comment-author {
            font-size: 0.85rem;
            font-weight: 500;
            margin-bottom: 0.2rem;
        }

        .comment-text {
            font-size: 0.85rem;
            color: var(--text-secondary);
        }

        .comment-time {
            font-size: 0.75rem;
            color: var(--text-secondary);
            margin-top: 0.3rem;
        }

        .comment-input {
            display: flex;
            gap: 0.5rem;
            padding: 1rem 1.5rem;
            border-top: 1px solid var(--border-color);
        }

        .comment-input input {
            flex: 1;
            padding: 0.6rem 1rem;
            background: var(--bg-secondary);
            border: 1px solid var(--border-color);
            border-radius: 20px;
            color: var(--text-primary);
            font-size: 0.85rem;
        }

        .comment-input input:focus {
            outline: none;
            border-color: var(--accent-purple);
        }

        /* ============== 加载动画 ============== */
        .loading {
            text-align: center;
            padding: 2rem;
            color: var(--text-secondary);
        }

        .loading-spinner {
            width: 40px;
            height: 40px;
            border: 3px solid var(--border-color);
            border-top-color: var(--accent-purple);
            border-radius: 50%;
            animation: spin 1s linear infinite;
            margin: 0 auto 1rem;
        }

        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* ============== Toast提示 ============== */
        .toast-container {
            position: fixed;
            top: 80px;
            right: 20px;
            z-index: 2000;
        }

        .toast {
            background: var(--bg-card);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 0.8rem 1.2rem;
            margin-bottom: 0.5rem;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3);
            animation: slideIn 0.3s ease;
        }

        .toast.success {
            border-color: var(--accent-green);
        }

        .toast.error {
            border-color: var(--accent-red);
        }

        @keyframes slideIn {
            from {
                transform: translateX(100%);
                opacity: 0;
            }
            to {
                transform: translateX(0);
                opacity: 1;
            }
        }
    </style>
</head>
<body>
    <!-- 鬼火背景 -->
    <div id="ghostFires"></div>

    <!-- 顶部导航 -->
    <nav class="navbar">
        <a href="/" class="logo">
            <span class="logo-icon">👻</span>
            <span>诡境</span>
        </a>

        <div class="search-box">
            <input type="text" id="searchInput" placeholder="搜索灵异事件..." />
        </div>

        <div class="nav-actions">
            <button class="btn btn-primary" id="createPostBtn">📝 投稿</button>
            <div id="authArea">
                <button class="btn btn-ghost" id="loginBtn">🚪 入境</button>
                <button class="btn btn-primary" id="registerBtn">📜 签约</button>
            </div>
            <div id="userArea" style="display: none;">
                <img id="userAvatar" class="user-avatar" src="" alt="avatar" />
                <button class="btn btn-ghost" id="logoutBtn">离开</button>
            </div>
        </div>
    </nav>

    <!-- 主容器 -->
    <div class="main-container">
        <!-- 左侧边栏 -->
        <aside class="sidebar left-sidebar">
            <div class="sidebar-card">
                <div class="sidebar-title">导航</div>
                <ul class="nav-menu">
                    <li class="nav-item active" data-sort="hot">🔥 热门</li>
                    <li class="nav-item" data-sort="new">✨ 最新</li>
                    <li class="nav-item" data-sort="following">👥 关注</li>
                    <li class="nav-item" data-bookmarks="true">⭐ 收藏</li>
                </ul>
            </div>

            <div class="sidebar-card">
                <div class="sidebar-title">话题</div>
                <div class="tag-list" id="topicList"></div>
            </div>
        </aside>

        <!-- 主内容区 -->
        <main class="content-area">
            <div class="masonry-grid" id="postGrid"></div>
            <div class="loading" id="loading" style="display: none;">
                <div class="loading-spinner"></div>
                <p>正在召唤灵体...</p>
            </div>
        </main>

        <!-- 右侧边栏 -->
        <aside class="sidebar right-sidebar">
            <div class="sidebar-card">
                <div class="sidebar-title">🔥 热门标签</div>
                <div class="tag-list" id="hotTags"></div>
            </div>

            <div class="sidebar-card">
                <div class="sidebar-title">👑 活跃用户</div>
                <div id="activeUsers"></div>
            </div>
        </aside>
    </div>

    <!-- 登录模态框 -->
    <div class="modal-overlay" id="loginModal">
        <div class="modal">
            <div class="modal-header">
                <h3 class="modal-title">🚪 入境</h3>
                <button class="modal-close" onclick="closeModal('loginModal')">&times;</button>
            </div>
            <div class="modal-body">
                <form id="loginForm">
                    <div class="form-group">
                        <label class="form-label">用户名</label>
                        <input type="text" class="form-input" id="loginUsername" required />
                    </div>
                    <div class="form-group">
                        <label class="form-label">密码</label>
                        <input type="password" class="form-input" id="loginPassword" required />
                    </div>
                    <button type="submit" class="btn btn-primary" style="width: 100%;">入境</button>
                </form>
            </div>
        </div>
    </div>

    <!-- 注册模态框 -->
    <div class="modal-overlay" id="registerModal">
        <div class="modal">
            <div class="modal-header">
                <h3 class="modal-title">📜 签约</h3>
                <button class="modal-close" onclick="closeModal('registerModal')">&times;</button>
            </div>
            <div class="modal-body">
                <form id="registerForm">
                    <div class="form-group">
                        <label class="form-label">用户名</label>
                        <input type="text" class="form-input" id="regUsername" required />
                    </div>
                    <div class="form-group">
                        <label class="form-label">邮箱</label>
                        <input type="email" class="form-input" id="regEmail" required />
                    </div>
                    <div class="form-group">
                        <label class="form-label">密码</label>
                        <input type="password" class="form-input" id="regPassword" required />
                    </div>
                    <div class="form-group">
                        <label class="form-label">昵称</label>
                        <input type="text" class="form-input" id="regNickname" />
                    </div>
                    <button type="submit" class="btn btn-primary" style="width: 100%;">签约</button>
                </form>
            </div>
        </div>
    </div>

    <!-- 发帖模态框 -->
    <div class="modal-overlay" id="createPostModal">
        <div class="modal">
            <div class="modal-header">
                <h3 class="modal-title">📝 投稿灵异事件</h3>
                <button class="modal-close" onclick="closeModal('createPostModal')">&times;</button>
            </div>
            <div class="modal-body">
                <form id="createPostForm">
                    <div class="form-group">
                        <label class="form-label">标题</label>
                        <input type="text" class="form-input" id="postTitle" required maxlength="200" />
                    </div>
                    <div class="form-group">
                        <label class="form-label">内容</label>
                        <textarea class="form-input form-textarea" id="postContent" required></textarea>
                    </div>
                    <div class="form-group">
                        <label class="form-label">图片链接（每行一个）</label>
                        <textarea class="form-input form-textarea" id="postImages" placeholder="https://example.com/image1.jpg"></textarea>
                    </div>
                    <div class="form-group">
                        <label class="form-label">话题标签（逗号分隔）</label>
                        <input type="text" class="form-input" id="postTopics" placeholder="校园怪谈,真实经历" />
                    </div>
                    <div class="form-group">
                        <label class="form-label">分类标签</label>
                        <input type="text" class="form-input" id="postTags" placeholder="灵异,恐怖" />
                    </div>
                    <button type="submit" class="btn btn-primary" style="width: 100%;">发布</button>
                </form>
            </div>
        </div>
    </div>

    <!-- 帖子详情模态框 -->
    <div class="modal-overlay post-detail-modal" id="postDetailModal">
        <div class="modal">
            <div class="modal-header">
                <h3 class="modal-title">📖 灵异详情</h3>
                <button class="modal-close" onclick="closeModal('postDetailModal')">&times;</button>
            </div>
            <div id="postDetailContent"></div>
        </div>
    </div>

    <!-- Toast容器 -->
    <div class="toast-container" id="toastContainer"></div>

    <script>
        // ============== 全局状态 ==============
        const API_BASE = '/api';
        let currentUser = null;
        let currentSort = 'hot';
        let currentTag = null;
        let currentPage = 1;
        let isLoading = false;
        let hasMore = true;

        // ============== 初始化 ==============
        document.addEventListener('DOMContentLoaded', () => {
            initGhostFires();
            checkAuth();
            loadPosts();
            loadTags();
            initEventListeners();
            initInfiniteScroll();
        });

        // 鬼火动画
        function initGhostFires() {
            const container = document.getElementById('ghostFires');
            for (let i = 0; i < 15; i++) {
                const fire = document.createElement('div');
                fire.className = 'ghost-fire';
                fire.style.left = Math.random() * 100 + '%';
                fire.style.animationDelay = Math.random() * 8 + 's';
                fire.style.animationDuration = (6 + Math.random() * 4) + 's';
                container.appendChild(fire);
            }
        }

        // ============== 认证相关 ==============
        async function checkAuth() {
            const token = localStorage.getItem('token');
            if (!token) return;

            try {
                const res = await fetch(`${API_BASE}/auth/me`, {
                    headers: { 'Authorization': `Bearer ${token}` }
                });
                if (res.ok) {
                    const data = await res.json();
                    currentUser = data.user;
                    updateAuthUI();
                } else {
                    localStorage.removeItem('token');
                }
            } catch (e) {
                console.error('Auth check failed:', e);
            }
        }

        function updateAuthUI() {
            const authArea = document.getElementById('authArea');
            const userArea = document.getElementById('userArea');

            if (currentUser) {
                authArea.style.display = 'none';
                userArea.style.display = 'flex';
                userArea.style.alignItems = 'center';
                userArea.style.gap = '0.5rem';
                document.getElementById('userAvatar').src = currentUser.avatar || '/static/default-avatar.png';
            } else {
                authArea.style.display = 'flex';
                userArea.style.display = 'none';
            }
        }

        // ============== 帖子加载 ==============
        async function loadPosts(append = false) {
            if (isLoading || (!append && !hasMore)) return;

            isLoading = true;
            document.getElementById('loading').style.display = 'block';

            try {
                let url = `${API_BASE}/posts?page=${currentPage}&per_page=20&sort=${currentSort}`;
                if (currentTag) url += `&tag=${encodeURIComponent(currentTag)}`;

                const token = localStorage.getItem('token');
                const headers = {};
                if (token) headers['Authorization'] = `Bearer ${token}`;

                const res = await fetch(url, { headers });
                const data = await res.json();

                const posts = data.posts || data.items || [];

                if (append) {
                    appendPosts(posts);
                } else {
                    renderPosts(posts);
                }

                hasMore = posts.length === 20;
                currentPage++;
            } catch (e) {
                console.error('Load posts failed:', e);
                showToast('加载失败，请稍后重试', 'error');
            } finally {
                isLoading = false;
                document.getElementById('loading').style.display = 'none';
            }
        }

        function renderPosts(posts) {
            const grid = document.getElementById('postGrid');
            grid.innerHTML = posts.map(p => createPostCard(p)).join('');
        }

        function appendPosts(posts) {
            const grid = document.getElementById('postGrid');
            grid.innerHTML += posts.map(p => createPostCard(p)).join('');
        }

        function createPostCard(post) {
            const imageHtml = post.images && post.images.length > 0 
                ? `<img class="post-image" src="${escapeHtml(post.images[0])}" alt="" loading="lazy" onerror="this.style.display='none'"/>` 
                : '';

            const topicsHtml = post.topics && post.topics.length > 0
                ? post.topics.slice(0, 3).map(t => `<span class="topic-tag">#${escapeHtml(t)}</span>`).join('')
                : '';

            const likeClass = post.is_liked ? 'liked' : '';
            const bookmarkClass = post.is_bookmarked ? 'bookmarked' : '';

            return `
                <article class="post-card" onclick="openPostDetail(${post.id})">
                    ${imageHtml}
                    <div class="post-content">
                        <div style="margin-bottom: 0.4rem;">${topicsHtml}</div>
                        <h3 class="post-title">${escapeHtml(post.title)}</h3>
                        <p class="post-excerpt">${escapeHtml(post.content.substring(0, 150))}</p>
                        <div class="post-meta">
                            <div class="post-author">
                                <img src="${post.author.avatar || '/static/default-avatar.png'}" alt="" />
                                <span>${escapeHtml(post.author.nickname || post.author.username)}</span>
                            </div>
                            <div class="post-stats">
                                <span class="stat-item ${likeClass}">😰 ${post.likes_count || 0}</span>
                                <span class="stat-item">💬 ${post.comments_count || 0}</span>
                            </div>
                        </div>
                    </div>
                </article>
            `;
        }

        // ============== 帖子详情 ==============
        async function openPostDetail(postId) {
            const modal = document.getElementById('postDetailModal');
            const content = document.getElementById('postDetailContent');

            content.innerHTML = '<div class="loading"><div class="loading-spinner"></div></div>';
            modal.classList.add('active');

            try {
                const token = localStorage.getItem('token');
                const headers = {};
                if (token) headers['Authorization'] = `Bearer ${token}`;

                const res = await fetch(`${API_BASE}/posts/${postId}`, { headers });
                const post = await res.json();

                // 增加浏览量
                fetch(`${API_BASE}/posts/${postId}/view`, { method: 'POST' });

                renderPostDetail(post);
            } catch (e) {
                content.innerHTML = '<p style="padding: 2rem; text-align: center;">加载失败</p>';
            }
        }

        function renderPostDetail(post) {
            const content = document.getElementById('postDetailContent');
            const imagesHtml = post.images && post.images.length > 0
                ? post.images.map(img => `<img src="${escapeHtml(img)}" alt="" style="max-width: 100%; border-radius: 8px; margin-bottom: 0.5rem;"/>`).join('')
                : '';

            const likeClass = post.is_liked ? 'active like' : '';
            const bookmarkClass = post.is_bookmarked ? 'active bookmark' : '';

            content.innerHTML = `
                <div class="post-detail-header">
                    <h2 class="post-detail-title">${escapeHtml(post.title)}</h2>
                    <div class="post-detail-meta">
                        <div class="post-detail-author">
                            <img src="${post.author.avatar || '/static/default-avatar.png'}" alt="" />
                            <span>${escapeHtml(post.author.nickname || post.author.username)}</span>
                        </div>
                        <span>${formatTime(post.created_at)}</span>
                        <span>👁 ${post.view_count || 0} 浏览</span>
                    </div>
                </div>
                <div class="post-detail-content">
                    ${imagesHtml}
                    <p class="post-detail-text">${escapeHtml(post.content)}</p>
                </div>
                <div class="post-detail-actions">
                    <button class="action-btn ${likeClass}" onclick="toggleLike(${post.id})">
                        😰 恐惧 (${post.likes_count || 0})
                    </button>
                    <button class="action-btn ${bookmarkClass}" onclick="toggleBookmark(${post.id})">
                        ⭐ 诡异录 (${post.bookmarks_count || 0})
                    </button>
                    <button class="action-btn" onclick="sharePost(${post.id})">
                        📤 分享
                    </button>
                </div>
                <div class="comments-section" id="commentsSection">
                    <p style="color: var(--text-secondary);">暂无评论</p>
                </div>
                <div class="comment-input">
                    <input type="text" id="commentInput" placeholder="写下你的看法..." />
                    <button class="btn btn-primary" onclick="submitComment(${post.id})">发送</button>
                </div>
            `;

            loadComments(post.id);
        }

        // ============== 点赞/收藏 ==============
        async function toggleLike(postId) {
            if (!currentUser) {
                showToast('请先登录', 'error');
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/posts/${postId}/like`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                });
                const data = await res.json();

                if (res.ok) {
                    showToast(data.liked ? '已标记恐惧' : '取消恐惧', 'success');
                    // 刷新详情
                    openPostDetail(postId);
                }
            } catch (e) {
                showToast('操作失败', 'error');
            }
        }

        async function toggleBookmark(postId) {
            if (!currentUser) {
                showToast('请先登录', 'error');
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/posts/${postId}/bookmark`, {
                    method: 'POST',
                    headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
                });
                const data = await res.json();

                if (res.ok) {
                    showToast(data.bookmarked ? '已加入诡异录' : '已从诡异录移除', 'success');
                    openPostDetail(postId);
                }
            } catch (e) {
                showToast('操作失败', 'error');
            }
        }

        // ============== 评论 ==============
        async function loadComments(postId) {
            try {
                const res = await fetch(`${API_BASE}/posts/${postId}/comments`);
                const data = await res.json();
                const comments = data.comments || data.items || [];

                const section = document.getElementById('commentsSection');
                if (comments.length === 0) {
                    section.innerHTML = '<p style="color: var(--text-secondary);">暂无评论，快来抢沙发~</p>';
                    return;
                }

                section.innerHTML = comments.map(c => `
                    <div class="comment-item">
                        <img src="${c.author.avatar || '/static/default-avatar.png'}" alt="" />
                        <div class="comment-content">
                            <div class="comment-author">${escapeHtml(c.author.nickname || c.author.username)}</div>
                            <div class="comment-text">${escapeHtml(c.content)}</div>
                            <div class="comment-time">${formatTime(c.created_at)}</div>
                        </div>
                    </div>
                `).join('');
            } catch (e) {
                console.error('Load comments failed:', e);
            }
        }

        async function submitComment(postId) {
            if (!currentUser) {
                showToast('请先登录', 'error');
                return;
            }

            const input = document.getElementById('commentInput');
            const content = input.value.trim();
            if (!content) {
                showToast('请输入评论内容', 'error');
                return;
            }

            try {
                const res = await fetch(`${API_BASE}/posts/${postId}/comments`, {
                    method: 'POST',
                    headers: {
                        'Authorization': `Bearer ${localStorage.getItem('token')}`,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ content })
                });

                if (res.ok) {
                    input.value = '';
                    showToast('评论成功', 'success');
                    loadComments(postId);
                }
            } catch (e) {
                showToast('评论失败', 'error');
            }
        }

        // ============== 标签加载 ==============
        async function loadTags() {
            try {
                const res = await fetch(`${API_BASE}/tags`);
                const data = await res.json();
                const tags = data.tags || data.items || [];

                const hotTags = document.getElementById('hotTags');
                const topicList = document.getElementById('topicList');

                const tagsHtml = tags.slice(0, 15).map(t => 
                    `<span class="tag-item" onclick="filterByTag('${escapeHtml(t.name)}')">${escapeHtml(t.name)}</span>`
                ).join('');

                hotTags.innerHTML = tagsHtml;
                topicList.innerHTML = tagsHtml;
            } catch (e) {
                console.error('Load tags failed:', e);
            }
        }

        function filterByTag(tag) {
            currentTag = tag;
            currentPage = 1;
            hasMore = true;
            loadPosts();
        }

        // ============== 事件监听 ==============
        function initEventListeners() {
            // 登录
            document.getElementById('loginBtn').addEventListener('click', () => {
                document.getElementById('loginModal').classList.add('active');
            });

            document.getElementById('loginForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('loginUsername').value;
                const password = document.getElementById('loginPassword').value;

                try {
                    const res = await fetch(`${API_BASE}/auth/login`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, password })
                    });
                    const data = await res.json();

                    if (res.ok) {
                        localStorage.setItem('token', data.token);
                        currentUser = data.user;
                        updateAuthUI();
                        closeModal('loginModal');
                        showToast('入境成功', 'success');
                        loadPosts();
                    } else {
                        showToast(data.error || '登录失败', 'error');
                    }
                } catch (e) {
                    showToast('网络错误', 'error');
                }
            });

            // 注册
            document.getElementById('registerBtn').addEventListener('click', () => {
                document.getElementById('registerModal').classList.add('active');
            });

            document.getElementById('registerForm').addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('regUsername').value;
                const email = document.getElementById('regEmail').value;
                const password = document.getElementById('regPassword').value;
                const nickname = document.getElementById('regNickname').value;

                try {
                    const res = await fetch(`${API_BASE}/auth/register`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ username, email, password, nickname })
                    });
                    const data = await res.json();

                    if (res.ok) {
                        localStorage.setItem('token', data.token);
                        currentUser = data.user;
                        updateAuthUI();
                        closeModal('registerModal');
                        showToast('签约成功，欢迎来到诡境', 'success');
                    } else {
                        showToast(data.error || '注册失败', 'error');
                    }
                } catch (e) {
                    showToast('网络错误', 'error');
                }
            });

            // 发帖
            document.getElementById('createPostBtn').addEventListener('click', () => {
                if (!currentUser) {
                    showToast('请先登录', 'error');
                    return;
                }
                document.getElementById('createPostModal').classList.add('active');
            });

            document.getElementById('createPostForm').addEventListener('submit', async (e) => {
                e.preventDefault();

                const title = document.getElementById('postTitle').value;
                const content = document.getElementById('postContent').value;
                const imagesText = document.getElementById('postImages').value;
                const topicsText = document.getElementById('postTopics').value;
                const tagsText = document.getElementById('postTags').value;

                const images = imagesText.split('\\n').filter(s => s.trim());
                const topics = topicsText.split(',').map(s => s.trim()).filter(s => s);
                const tags = tagsText.split(',').map(s => s.trim()).filter(s => s);

                try {
                    const res = await fetch(`${API_BASE}/posts`, {
                        method: 'POST',
                        headers: {
                            'Authorization': `Bearer ${localStorage.getItem('token')}`,
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify({ title, content, images, topics, tags })
                    });
                    const data = await res.json();

                    if (res.ok) {
                        closeModal('createPostModal');
                        showToast('投稿成功', 'success');
                        currentPage = 1;
                        loadPosts();
                    } else {
                        showToast(data.error || '发布失败', 'error');
                    }
                } catch (e) {
                    showToast('网络错误', 'error');
                }
            });

            // 退出
            document.getElementById('logoutBtn').addEventListener('click', () => {
                localStorage.removeItem('token');
                currentUser = null;
                updateAuthUI();
                showToast('已离开诡境', 'success');
                loadPosts();
            });

            // 搜索
            document.getElementById('searchInput').addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const query = e.target.value.trim();
                    if (query) {
                        searchPosts(query);
                    }
                }
            });

            // 导航菜单
            document.querySelectorAll('.nav-item').forEach(item => {
                item.addEventListener('click', function() {
                    document.querySelectorAll('.nav-item').forEach(i => i.classList.remove('active'));
                    this.classList.add('active');

                    if (this.dataset.sort) {
                        currentSort = this.dataset.sort;
                        currentTag = null;
                    } else if (this.dataset.bookmarks) {
                        currentSort = 'bookmarks';
                        currentTag = null;
                    }

                    currentPage = 1;
                    hasMore = true;
                    loadPosts();
                });
            });

            // 点击模态框背景关闭
            document.querySelectorAll('.modal-overlay').forEach(overlay => {
                overlay.addEventListener('click', (e) => {
                    if (e.target === overlay) {
                        overlay.classList.remove('active');
                    }
                });
            });
        }

        // 无限滚动
        function initInfiniteScroll() {
            window.addEventListener('scroll', () => {
                if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 500) {
                    if (hasMore && !isLoading) {
                        loadPosts(true);
                    }
                }
            });
        }

        // 搜索
        async function searchPosts(query) {
            try {
                const res = await fetch(`${API_BASE}/search?q=${encodeURIComponent(query)}`);
                const data = await res.json();
                const posts = data.posts || data.items || [];
                renderPosts(posts);
                hasMore = false;
            } catch (e) {
                showToast('搜索失败', 'error');
            }
        }

        // ============== 工具函数 ==============
        function closeModal(id) {
            document.getElementById(id).classList.remove('active');
        }

        function showToast(message, type = 'info') {
            const container = document.getElementById('toastContainer');
            const toast = document.createElement('div');
            toast.className = `toast ${type}`;
            toast.textContent = message;
            container.appendChild(toast);

            setTimeout(() => toast.remove(), 3000);
        }

        function escapeHtml(text) {
            if (!text) return '';
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function formatTime(dateStr) {
            if (!dateStr) return '';
            const date = new Date(dateStr);
            const now = new Date();
            const diff = (now - date) / 1000;

            if (diff < 60) return '刚刚';
            if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
            if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
            if (diff < 604800) return Math.floor(diff / 86400) + '天前';

            return date.toLocaleDateString('zh-CN');
        }

        function sharePost(postId) {
            const url = window.location.origin + '/post/' + postId;
            navigator.clipboard.writeText(url).then(() => {
                showToast('链接已复制', 'success');
            });
        }
    </script>
</body>
</html>
'''


# ============== API路由 ==============

# ---------- 认证 ----------
@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()

    username = sanitize_input(data.get('username', ''), 50)
    email = sanitize_input(data.get('email', ''), 100)
    password = data.get('password', '')
    nickname = sanitize_input(data.get('nickname', ''), 50)

    # 验证
    if not username or len(username) < 3:
        return jsonify({'error': '用户名至少3个字符'}), 400
    if not email or '@' not in email:
        return jsonify({'error': '请输入有效邮箱'}), 400
    if not password or len(password) < 6:
        return jsonify({'error': '密码至少6个字符'}), 400

    # 检查重复
    if User.query.filter_by(username=username).first():
        return jsonify({'error': '用户名已存在'}), 400
    if User.query.filter_by(email=email).first():
        return jsonify({'error': '邮箱已被注册'}), 400

    # 创建用户
    user = User(
        username=username,
        email=email,
        nickname=nickname or username,
        role='user'
    )
    user.password = password

    db.session.add(user)
    db.session.commit()

    # 生成token
    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=30)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    return jsonify({
        'message': '注册成功',
        'user': user.to_dict(),
        'token': token
    }), 201


@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()

    username = sanitize_input(data.get('username', ''), 50)
    password = data.get('password', '')

    user = User.query.filter(
        (User.username == username) | (User.email == username)
    ).first()

    if not user or not user.verify_password(password):
        return jsonify({'error': '用户名或密码错误'}), 401

    if not user.is_active:
        return jsonify({'error': '账号已被禁用'}), 403

    token = jwt.encode({
        'user_id': user.id,
        'exp': datetime.utcnow() + timedelta(days=30)
    }, app.config['SECRET_KEY'], algorithm='HS256')

    response = jsonify({
        'message': '登录成功',
        'user': user.to_dict(),
        'token': token
    })
    response.set_cookie('token', token, max_age=30 * 24 * 3600, httponly=True, samesite='Lax')

    return response


@app.route('/api/auth/logout', methods=['POST'])
def logout():
    response = jsonify({'message': '退出成功'})
    response.delete_cookie('token')
    return response


@app.route('/api/auth/me', methods=['GET'])
@token_required
def get_current_user():
    return jsonify({'user': g.current_user.to_dict()})


# ---------- 帖子 ----------
@app.route('/api/posts', methods=['GET'])
@optional_token
def get_posts():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)
    sort = request.args.get('sort', 'hot')
    tag = request.args.get('tag')
    topic = request.args.get('topic')

    query = Post.query.filter_by(is_published=True)

    # 标签筛选
    if tag:
        tag_obj = Tag.query.filter_by(name=tag).first()
        if tag_obj:
            post_ids = [pt.post_id for pt in PostTag.query.filter_by(tag_id=tag_obj.id).all()]
            query = query.filter(Post.id.in_(post_ids))

    # 话题筛选
    if topic:
        query = query.filter(Post.topics.contains(f'"{topic}"'))

    # 排序
    if sort == 'new':
        query = query.order_by(Post.created_at.desc())
    elif sort == 'hot':
        # 热度排序需要在Python中计算
        posts = query.all()
        posts.sort(key=lambda p: p.hot_score, reverse=True)
        posts = posts[(page - 1) * per_page: page * per_page]
        current_user_id = g.current_user.id if g.current_user else None
        return jsonify({
            'posts': [p.to_dict(current_user_id) for p in posts],
            'page': page,
            'per_page': per_page
        })
    elif sort == 'bookmarks':
        if not g.current_user:
            return jsonify({'error': '请先登录'}), 401
        bookmark_post_ids = [b.post_id for b in Bookmark.query.filter_by(user_id=g.current_user.id).all()]
        query = query.filter(Post.id.in_(bookmark_post_ids))
        query = query.order_by(Post.created_at.desc())
    else:
        query = query.order_by(Post.created_at.desc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    current_user_id = g.current_user.id if g.current_user else None

    return jsonify({
        'posts': [p.to_dict(current_user_id) for p in pagination.items],
        'page': page,
        'per_page': per_page,
        'total': pagination.total,
        'has_next': pagination.has_next
    })


@app.route('/api/posts/<int:post_id>', methods=['GET'])
@optional_token
def get_post(post_id):
    post = Post.query.get_or_404(post_id)
    current_user_id = g.current_user.id if g.current_user else None
    return jsonify(post.to_dict(current_user_id))


@app.route('/api/posts', methods=['POST'])
@token_required
def create_post():
    data = request.get_json()

    title = sanitize_input(data.get('title', ''), 200)
    content = sanitize_input(data.get('content', ''), 10000)
    images = data.get('images', [])
    topics = data.get('topics', [])
    tags = data.get('tags', [])

    if not title:
        return jsonify({'error': '标题不能为空'}), 400
    if not content:
        return jsonify({'error': '内容不能为空'}), 400

    # 验证图片URL
    valid_images = [img for img in images if validate_image_url(img)][:9]  # 最多9张图

    post = Post(
        title=title,
        content=content,
        author_id=g.current_user.id
    )
    post.images_list = valid_images
    post.topics_list = [sanitize_input(t, 50) for t in topics[:5]]  # 最多5个话题

    db.session.add(post)
    db.session.flush()  # 获取post.id

    # 处理标签
    for tag_name in tags[:5]:  # 最多5个标签
        tag_name = sanitize_input(tag_name, 50).lower()
        if not tag_name:
            continue
        tag = Tag.query.filter_by(name=tag_name).first()
        if not tag:
            tag = Tag(name=tag_name)
            db.session.add(tag)
            db.session.flush()
        post_tag = PostTag(post_id=post.id, tag_id=tag.id)
        db.session.add(post_tag)

    db.session.commit()

    return jsonify(post.to_dict(g.current_user.id)), 201


@app.route('/api/posts/<int:post_id>', methods=['PUT'])
@token_required
def update_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author_id != g.current_user.id and g.current_user.role != 'admin':
        return jsonify({'error': '无权限修改'}), 403

    data = request.get_json()

    if 'title' in data:
        post.title = sanitize_input(data['title'], 200)
    if 'content' in data:
        post.content = sanitize_input(data['content'], 10000)
    if 'images' in data:
        post.images_list = [img for img in data['images'] if validate_image_url(img)][:9]
    if 'topics' in data:
        post.topics_list = [sanitize_input(t, 50) for t in data['topics'][:5]]
    if 'tags' in data:
        # 删除旧标签关联
        PostTag.query.filter_by(post_id=post.id).delete()
        # 添加新标签
        for tag_name in data['tags'][:5]:
            tag_name = sanitize_input(tag_name, 50).lower()
            if not tag_name:
                continue
            tag = Tag.query.filter_by(name=tag_name).first()
            if not tag:
                tag = Tag(name=tag_name)
                db.session.add(tag)
                db.session.flush()
            post_tag = PostTag(post_id=post.id, tag_id=tag.id)
            db.session.add(post_tag)

    db.session.commit()
    return jsonify(post.to_dict(g.current_user.id))


@app.route('/api/posts/<int:post_id>', methods=['DELETE'])
@token_required
def delete_post(post_id):
    post = Post.query.get_or_404(post_id)

    if post.author_id != g.current_user.id and g.current_user.role != 'admin':
        return jsonify({'error': '无权限删除'}), 403

    db.session.delete(post)
    db.session.commit()

    return jsonify({'message': '删除成功'})


@app.route('/api/posts/<int:post_id>/view', methods=['POST'])
def increment_view(post_id):
    post = Post.query.get_or_404(post_id)
    post.view_count += 1
    db.session.commit()
    return jsonify({'view_count': post.view_count})


# ---------- 点赞 ----------
@app.route('/api/posts/<int:post_id>/like', methods=['POST'])
@token_required
def toggle_like(post_id):
    post = Post.query.get_or_404(post_id)

    existing = Like.query.filter_by(
        user_id=g.current_user.id,
        post_id=post_id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'liked': False, 'likes_count': post.likes_count})
    else:
        like = Like(user_id=g.current_user.id, post_id=post_id)
        db.session.add(like)
        db.session.commit()
        return jsonify({'liked': True, 'likes_count': post.likes_count})


# ---------- 收藏 ----------
@app.route('/api/posts/<int:post_id>/bookmark', methods=['POST'])
@token_required
def toggle_bookmark(post_id):
    post = Post.query.get_or_404(post_id)

    existing = Bookmark.query.filter_by(
        user_id=g.current_user.id,
        post_id=post_id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'bookmarked': False, 'bookmarks_count': post.bookmarks_count})
    else:
        bookmark = Bookmark(user_id=g.current_user.id, post_id=post_id)
        db.session.add(bookmark)
        db.session.commit()
        return jsonify({'bookmarked': True, 'bookmarks_count': post.bookmarks_count})


# ---------- 评论 ----------
@app.route('/api/posts/<int:post_id>/comments', methods=['GET'])
def get_comments(post_id):
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    Post.query.get_or_404(post_id)

    comments = Comment.query.filter_by(post_id=post_id, parent_id=None) \
        .order_by(Comment.created_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'comments': [c.to_dict() for c in comments.items],
        'page': page,
        'per_page': per_page,
        'total': comments.total
    })


@app.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@token_required
def create_comment(post_id):
    Post.query.get_or_404(post_id)

    data = request.get_json()
    content = sanitize_input(data.get('content', ''), 1000)
    parent_id = data.get('parent_id')

    if not content:
        return jsonify({'error': '评论内容不能为空'}), 400

    comment = Comment(
        content=content,
        post_id=post_id,
        author_id=g.current_user.id,
        parent_id=parent_id
    )

    db.session.add(comment)
    db.session.commit()

    return jsonify(comment.to_dict()), 201


# ---------- 标签 ----------
@app.route('/api/tags', methods=['GET'])
def get_tags():
    tags = Tag.query.order_by(Tag.name).all()
    return jsonify({
        'tags': [t.to_dict() for t in tags]
    })


# ---------- 搜索 ----------
@app.route('/api/search', methods=['GET'])
@optional_token
def search():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'posts': []})

    search_term = f'%{query}%'
    posts = Post.query.filter(
        Post.is_published == True,
        db.or_(
            Post.title.ilike(search_term),
            Post.content.ilike(search_term)
        )
    ).order_by(Post.created_at.desc()).limit(50).all()

    current_user_id = g.current_user.id if g.current_user else None
    return jsonify({
        'posts': [p.to_dict(current_user_id) for p in posts],
        'query': query
    })


# ---------- 用户 ----------
@app.route('/api/users/<int:user_id>', methods=['GET'])
def get_user(user_id):
    user = User.query.get_or_404(user_id)
    return jsonify(user.to_dict())


@app.route('/api/users/<int:user_id>/posts', methods=['GET'])
@optional_token
def get_user_posts(user_id):
    User.query.get_or_404(user_id)

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 50)

    posts = Post.query.filter_by(author_id=user_id, is_published=True) \
        .order_by(Post.created_at.desc()) \
        .paginate(page=page, per_page=per_page, error_out=False)

    current_user_id = g.current_user.id if g.current_user else None

    return jsonify({
        'posts': [p.to_dict(current_user_id) for p in posts.items],
        'page': page,
        'per_page': per_page,
        'total': posts.total
    })


@app.route('/api/users/<int:user_id>/follow', methods=['POST'])
@token_required
def toggle_follow(user_id):
    if user_id == g.current_user.id:
        return jsonify({'error': '不能关注自己'}), 400

    user = User.query.get_or_404(user_id)

    existing = Follow.query.filter_by(
        follower_id=g.current_user.id,
        following_id=user_id
    ).first()

    if existing:
        db.session.delete(existing)
        db.session.commit()
        return jsonify({'following': False, 'followers_count': user.to_dict()['followers_count']})
    else:
        follow = Follow(follower_id=g.current_user.id, following_id=user_id)
        db.session.add(follow)
        db.session.commit()
        return jsonify({'following': True, 'followers_count': user.to_dict()['followers_count']})


# ---------- 管理员接口 ----------
@app.route('/api/admin/posts/<int:post_id>/pin', methods=['POST'])
@admin_required
def toggle_pin_post(post_id):
    post = Post.query.get_or_404(post_id)
    post.is_pinned = not post.is_pinned
    db.session.commit()
    return jsonify({'pinned': post.is_pinned})


@app.route('/api/admin/users/<int:user_id>/role', methods=['PUT'])
@admin_required
def update_user_role(user_id):
    user = User.query.get_or_404(user_id)
    data = request.get_json()
    new_role = data.get('role')

    if new_role not in ['user', 'admin', 'moderator']:
        return jsonify({'error': '无效角色'}), 400

    user.role = new_role
    db.session.commit()
    return jsonify(user.to_dict())


@app.route('/api/admin/users/<int:user_id>/ban', methods=['POST'])
@admin_required
def toggle_ban_user(user_id):
    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    return jsonify({'active': user.is_active})


# ---------- 文件上传 ----------
@app.route('/api/upload', methods=['POST'])
@token_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '没有文件'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '没有选择文件'}), 400

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        # 添加时间戳避免冲突
        filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        return jsonify({
            'url': f'/uploads/{filename}',
            'filename': filename
        })

    return jsonify({'error': '不支持的文件类型'}), 400


@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ---------- 静态文件服务 ----------
@app.route('/static/<path:filename>')
def serve_static(filename):
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    return send_from_directory(static_dir, filename)


# ---------- 首页路由 ----------
@app.route('/')
def serve_index():
    return render_template_string(INDEX_HTML)


@app.route('/post/<int:post_id>')
def serve_post_detail(post_id):
    return render_template_string(INDEX_HTML)


# ---------- 初始化数据库 ----------
def init_db():
    with app.app_context():
        db.create_all()

        # 创建管理员账号
        admin = User.query.filter_by(username='admin').first()
        if not admin:
            admin = User(
                username='admin',
                email='admin@guijing.com',
                nickname='诡境守护者',
                role='admin'
            )
            admin.password = 'admin123'
            db.session.add(admin)

            # 创建示例标签
            tags = ['校园怪谈', '都市传说', '灵异经历', '民间故事', '真实事件',
                    '鬼屋探险', '梦境解析', '神秘现象', '古籍记载', '网友分享']
            for tag_name in tags:
                tag = Tag(name=tag_name)
                db.session.add(tag)

            # 创建示例帖子
            sample_posts = [
                {
                    'title': '深夜宿舍的敲门声',
                    'content': '那是大二的一个雨夜，宿舍其他人都睡了，我正准备关灯。突然听到门外传来轻轻的敲门声，三下，很有规律。我以为是谁忘带钥匙了，就问了一句"谁啊"，没人应。敲门声又响了三下。我透过猫眼往外看，走廊的灯忽明忽暗，但门外什么都没有...',
                    'topics': ['校园怪谈', '真实经历'],
                    'tags': ['校园怪谈', '真实事件']
                },
                {
                    'title': '爷爷的老宅子',
                    'content': '老家有一座百年老宅，爷爷说那里住着我们祖上十几代人。小时候我总喜欢去那里玩，但每次去，爷爷都会警告我不要去后院的那口枯井边。直到有一天，我因为追一只蝴蝶，不知不觉走到了后院...',
                    'topics': ['民间故事', '古籍记载'],
                    'tags': ['民间故事', '神秘现象']
                },
                {
                    'title': '末班地铁的乘客',
                    'content': '工作到很晚，赶上了末班地铁。车厢里只有我一个人，我坐在角落玩手机。不知过了几站，突然感觉有人坐到了我对面。抬头一看，是个穿着旗袍的女人，低着头，看不清脸。奇怪的是，她的衣服看起来很新，但款式却是民国时期的...',
                    'topics': ['都市传说', '灵异经历'],
                    'tags': ['都市传说', '灵异经历']
                },
                {
                    'title': '梦境中的预言',
                    'content': '从小到大，我做过很多奇怪的梦。但最让我毛骨悚然的是，这些梦有时候会成真。上周我梦见一个陌生人在地铁里晕倒，三天后，我在同一班地铁上亲眼目睹了这一幕。更可怕的是，那个陌生人抬起头看了我一眼，说的第一句话是"你又来了"...',
                    'topics': ['梦境解析', '神秘现象'],
                    'tags': ['梦境解析', '神秘现象']
                },
                {
                    'title': '废弃医院的探险',
                    'content': '听说城郊有座废弃的精神病院，很多年前就关闭了。我和几个胆子大的朋友决定去探险。走进大门的那一刻，我就后悔了。走廊里到处都是旧病历和药瓶，墙壁上还有奇怪的抓痕。最诡异的是，我们在三楼的一个病房里发现了一本日记...',
                    'topics': ['鬼屋探险', '网友分享'],
                    'tags': ['鬼屋探险', '真实事件']
                }
            ]

            for i, post_data in enumerate(sample_posts):
                post = Post(
                    title=post_data['title'],
                    content=post_data['content'],
                    author_id=admin.id,
                    view_count=100 + i * 50
                )
                post.topics_list = post_data['topics']
                db.session.add(post)
                db.session.flush()

                for tag_name in post_data['tags']:
                    tag = Tag.query.filter_by(name=tag_name).first()
                    if tag:
                        post_tag = PostTag(post_id=post.id, tag_id=tag.id)
                        db.session.add(post_tag)

            db.session.commit()
            print("数据库初始化完成！")


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
