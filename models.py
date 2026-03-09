# 数据模型层：所有 SQLAlchemy 模型与评论树构建，便于迁移与维护
from datetime import datetime
import json
import secrets
import random
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    address = db.Column(db.String(42), unique=True, nullable=True, index=True)
    nonce = db.Column(db.String(32), default=lambda: secrets.token_hex(16))
    nonce_created_at = db.Column(db.DateTime, default=datetime.utcnow)
    username = db.Column(db.String(50), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=True)
    nickname = db.Column(db.String(50))
    avatar = db.Column(db.String(500), default='👻')
    bio = db.Column(db.String(500), default='')
    has_nft_badge = db.Column(db.Boolean, default=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    wallet_address = db.Column(db.String(42), nullable=True)
    withdrawable_balance = db.Column(db.String(50), default='0')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='author', lazy='dynamic', foreign_keys='Post.author_id')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        if not self.password_hash:
            return False
        if password is None:
            return False
        if isinstance(password, str) and not password.strip():
            return False
        try:
            return check_password_hash(self.password_hash, str(password))
        except (TypeError, ValueError):
            return False

    def refresh_nonce(self):
        self.nonce = secrets.token_hex(16)
        self.nonce_created_at = datetime.utcnow()

    def to_dict(self):
        return {
            'id': self.id,
            'type': 'web3' if self.address else 'web2',
            'address': self.address,
            'wallet_address': getattr(self, 'wallet_address', None) or self.address,
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
    images = db.Column(db.Text)
    author_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    view_count = db.Column(db.Integer, default=0)
    tx_hash = db.Column(db.String(66), unique=True, nullable=True)
    ipfs_cid = db.Column(db.String(100), nullable=True)
    nft_token_id = db.Column(db.BigInteger, nullable=True, index=True)
    nft_tx_hash = db.Column(db.String(66), nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    region = db.Column(db.String(20), default='其他')
    is_on_chain = db.Column(db.Boolean, default=False)
    post_type = db.Column(db.Integer, default=0, index=True)
    is_hidden = db.Column(db.Boolean, default=False, index=True)
    is_pinned = db.Column(db.Boolean, default=False, index=True)
    pinned_at = db.Column(db.DateTime, nullable=True, index=True)
    pinned_by = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    allow_comments = db.Column(db.Boolean, default=True)
    is_repost = db.Column(db.Boolean, default=False)
    original_post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    repost_comment = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    comments = db.relationship('Comment', backref='post', lazy='dynamic')
    likes = db.relationship('Like', backref='post', lazy='dynamic')
    votes = db.relationship('Vote', backref='post', lazy='dynamic')
    original_post = db.relationship('Post', remote_side=[id], backref='reposts')

    def to_dict(self, current_user_id=None, likes_count=None, comments_count=None):
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

        lc = likes_count if likes_count is not None else self.likes.count()
        cc = comments_count if comments_count is not None else self.comments.count()
        cover_image = self.cover_image
        if cover_image and str(cover_image).strip() == '/static/images/hua_cover.jpg':
            cover_image = None  # 该占位图已移除，不再返回避免 404
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'cover_image': cover_image,
            'images': images_list,
            'author': self.author.to_dict() if self.author else {'id': self.author_id, 'nickname': '已注销', 'username': None, 'avatar': '👻'},
            'view_count': self.view_count,
            'likes_count': lc,
            'comments_count': cc,
            'votes': [v.to_dict() for v in self.votes],
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'tx_hash': self.tx_hash,
            'ipfs_cid': self.ipfs_cid,
            'post_type': self.post_type,
            'created_at': self.created_at.isoformat(),
            'is_repost': self.is_repost,
            'original_post_id': self.original_post_id,
            'original_post': original_post_data,
            'repost_comment': self.repost_comment,
            'is_hidden': self.is_hidden,
            'is_pinned': self.is_pinned,
            'pinned_at': self.pinned_at.isoformat() if self.pinned_at else None,
            'pinned_by': self.pinned_by,
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
        return {'id': self.id, 'option_text': self.option_text, 'vote_count': self.vote_count}


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


def _comment_to_dict_node(c):
    author_data = c.author.to_dict() if c.author else {'id': c.author_id, 'nickname': '已注销', 'avatar': '👻'}
    return {
        'id': c.id,
        'content': c.content,
        'author': author_data,
        'created_at': c.created_at.isoformat(),
        'parent_id': c.parent_id,
        'replies': []
    }


def build_comment_tree(comments):
    by_parent = {}
    for c in comments:
        pid = c.parent_id
        if pid not in by_parent:
            by_parent[pid] = []
        by_parent[pid].append(c)

    def fill_replies(nodes):
        for n in nodes:
            d = _comment_to_dict_node(n)
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
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    sender_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'), nullable=True)
    type = db.Column(db.String(20))
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
    amount = db.Column(db.String(50))
    token_symbol = db.Column(db.String(10), default='USDT')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    sender = db.relationship('User', foreign_keys=[from_user_id])
    recipient = db.relationship('User', foreign_keys=[to_user_id])
    post = db.relationship('Post')


class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    reported_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')
    admin_notes = db.Column(db.String(500), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reporter = db.relationship('User', foreign_keys=[reporter_id])
    reported_user = db.relationship('User', foreign_keys=[reported_user_id])
    post = db.relationship('Post')

    def to_dict(self):
        return {
            'id': self.id,
            'reporter_id': self.reporter_id,
            'reported_user_id': self.reported_user_id,
            'post_id': self.post_id,
            'reason': self.reason,
            'status': self.status,
            'admin_notes': self.admin_notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reporter_nickname': self.reporter.nickname if self.reporter else None,
            'reported_nickname': self.reported_user.nickname if self.reported_user else None,
            'post_title': self.post.title[:50] if self.post and self.post.title else None,
        }


ALLOWED_AVATARS = ['👻', '💀', '👽', '👾', '🤖', '🎃', '🧛', '🧟', '🧞', '🧝', '🧙', '🧚', '🧜', '👼', '👿', '👺', '👹', '🤡', '💩', '🦄']


def get_random_avatar():
    return random.choice(ALLOWED_AVATARS)
