# 数据模型层：所有 SQLAlchemy 模型与评论树构建，便于迁移与维护
from datetime import datetime
import json
import secrets
import random
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db


LEVEL_BASE_EXP = 20
LEVEL_EXP_STEP = 12
CHECKIN_BASE_EXP = 2
CHECKIN_MAX_EXP = 12


def exp_needed_for_next_level(level):
    lv = int(level or 1)
    if lv < 1:
        lv = 1
    return LEVEL_BASE_EXP + (lv - 1) * LEVEL_EXP_STEP


def calc_level_info(total_exp):
    total = int(total_exp or 0)
    if total < 0:
        total = 0
    level = 1
    spent = 0
    need = exp_needed_for_next_level(level)
    while total - spent >= need:
        spent += need
        level += 1
        need = exp_needed_for_next_level(level)
        if level >= 1000:
            break
    current_in_level = total - spent
    return {
        'level': max(1, level),
        'total_exp': total,
        'level_current_exp': max(0, current_in_level),
        'level_next_exp': max(1, need),
        'level_progress': round(max(0.0, min(1.0, current_in_level / float(need))), 4)
    }


def checkin_exp_by_streak(streak):
    s = int(streak or 1)
    if s < 1:
        s = 1
    return min(CHECKIN_MAX_EXP, CHECKIN_BASE_EXP * s)


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
    is_admin = db.Column(db.Boolean, default=False)
    is_banned = db.Column(db.Boolean, default=False)
    wallet_address = db.Column(db.String(42), nullable=True)
    withdrawable_balance = db.Column(db.String(50), default='0')
    experience_points = db.Column(db.Integer, default=0)
    checkin_streak = db.Column(db.Integer, default=0)
    last_checkin_date = db.Column(db.Date, nullable=True, index=True)
    equipped_achievement_key = db.Column(db.String(64), nullable=True)
    show_tip_thanks = db.Column(db.Boolean, default=False)
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

    def get_honor_title(self):
        """称号系统：按管理员 > 发帖数 > 注册年限 > 账号类型优先级返回单称号。"""
        now = datetime.utcnow()
        post_count = None
        try:
            post_count = int(getattr(self, '_cached_post_count'))
        except Exception:
            try:
                post_count = self.posts.count()
            except Exception:
                post_count = 0
        years = 0
        if self.created_at:
            years = max(0, int((now - self.created_at).days // 365))
        has_wallet = bool(self.address)
        has_web2 = bool(self.username)
        onboarding_completed = has_wallet and has_web2 and post_count > 0

        if self.is_admin:
            return '守夜人'
        if post_count >= 1000:
            return '千帖通灵者'
        if post_count >= 100:
            return '百帖引魂者'
        if post_count >= 10:
            return '十帖异闻录'
        if onboarding_completed:
            return '结契通灵者'
        if years >= 10:
            return '十年守秘人'
        if years >= 5:
            return '五年夜巡者'
        if years >= 1:
            return '一年见习者'
        if has_wallet and has_web2:
            return '双界行者'
        if has_wallet:
            return '链上旅人'
        return '新魂'

    def get_level_info(self):
        if self.is_admin:
            return {
                'level': 9999,
                'total_exp': int(getattr(self, 'experience_points', 0) or 0),
                'level_current_exp': 0,
                'level_next_exp': 1,
                'level_progress': 1.0,
                'level_label': '∞',
                'admin_infinite_level': True
            }
        info = calc_level_info(getattr(self, 'experience_points', 0))
        info['level_label'] = f"Lv.{info['level']}"
        info['admin_infinite_level'] = False
        return info

    def to_dict(self):
        level_info = self.get_level_info()
        return {
            'id': self.id,
            'type': 'web3' if self.address else 'web2',
            'address': self.address,
            'wallet_address': getattr(self, 'wallet_address', None) or self.address,
            'username': self.username,
            'nickname': self.nickname or self.username or (self.address[:6] + '...' if self.address else 'Unknown'),
            'avatar': self.avatar,
            'bio': self.bio,
            'is_admin': self.is_admin,
            'is_banned': self.is_banned,
            'honor_title': self.get_honor_title(),
            'experience_points': level_info['total_exp'],
            'level': level_info['level'],
            'level_label': level_info.get('level_label') or f"Lv.{level_info['level']}",
            'admin_infinite_level': bool(level_info.get('admin_infinite_level')),
            'level_current_exp': level_info['level_current_exp'],
            'level_next_exp': level_info['level_next_exp'],
            'level_progress': level_info['level_progress'],
            'checkin_streak': int(getattr(self, 'checkin_streak', 0) or 0),
            'equipped_achievement_key': getattr(self, 'equipped_achievement_key', None),
            'show_tip_thanks': bool(getattr(self, 'show_tip_thanks', False)),
        }


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    content = db.Column(db.Text)
    cover_image = db.Column(db.String(500), nullable=True)
    images = db.Column(db.Text)
    tags = db.Column(db.Text, nullable=True)
    author_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    view_count = db.Column(db.Integer, default=0)
    tx_hash = db.Column(db.String(66), unique=True, nullable=True)
    ipfs_cid = db.Column(db.String(100), nullable=True)
    is_paid = db.Column(db.Boolean, default=False)
    region = db.Column(db.String(20), default='其他')
    is_on_chain = db.Column(db.Boolean, default=False)
    post_type = db.Column(db.Integer, default=0, index=True)
    is_hidden = db.Column(db.Boolean, default=False, index=True)
    is_special_announcement = db.Column(db.Boolean, default=False, index=True)
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
        try:
            tags_list = json.loads(self.tags) if self.tags else []
        except (TypeError, ValueError):
            tags_list = []
        if not isinstance(tags_list, list):
            tags_list = []
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
        is_permanent = bool(self.tx_hash or self.ipfs_cid or self.is_on_chain or self.post_type == 1)
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'cover_image': None,  # 帖子封面系统已下线，字段仅保留兼容
            'images': images_list,
            'tags': tags_list,
            'author': self.author.to_dict() if self.author else {'id': self.author_id, 'nickname': '已注销', 'username': None, 'avatar': '👻', 'honor_title': '新魂'},
            'view_count': self.view_count,
            'likes_count': lc,
            'comments_count': cc,
            'votes': [v.to_dict() for v in self.votes],
            'is_liked': is_liked,
            'is_bookmarked': is_bookmarked,
            'tx_hash': self.tx_hash,
            'ipfs_cid': self.ipfs_cid,
            'post_type': self.post_type,
            'is_permanent': is_permanent,
            'created_at': self.created_at.isoformat(),
            'is_repost': self.is_repost,
            'original_post_id': self.original_post_id,
            'original_post': original_post_data,
            'repost_comment': self.repost_comment,
            'is_hidden': self.is_hidden,
            'is_special_announcement': self.is_special_announcement,
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

    def to_dict(self, recursive=False, likes_count=0, is_liked=False):
        author_data = self.author.to_dict() if self.author else {'id': self.author_id, 'nickname': '已注销', 'avatar': '👻'}
        data = {
            'id': self.id,
            'content': self.content,
            'author': author_data,
            'created_at': self.created_at.isoformat(),
            'parent_id': self.parent_id,
            'likes_count': int(likes_count or 0),
            'is_liked': bool(is_liked)
        }
        if recursive:
            data['replies'] = [reply.to_dict(recursive=True) for reply in self.replies.all()]
        return data


def _comment_to_dict_node(c, likes_count=0, is_liked=False):
    author_data = c.author.to_dict() if c.author else {'id': c.author_id, 'nickname': '已注销', 'avatar': '👻', 'honor_title': '新魂'}
    return {
        'id': c.id,
        'content': c.content,
        'author': author_data,
        'created_at': c.created_at.isoformat(),
        'parent_id': c.parent_id,
        'likes_count': int(likes_count or 0),
        'is_liked': bool(is_liked),
        'replies': []
    }


def build_comment_tree(comments, like_counts=None, liked_comment_ids=None):
    like_counts = like_counts or {}
    liked_comment_ids = liked_comment_ids or set()
    by_parent = {}
    for c in comments:
        pid = c.parent_id
        if pid not in by_parent:
            by_parent[pid] = []
        by_parent[pid].append(c)

    def fill_replies(nodes):
        for n in nodes:
            d = _comment_to_dict_node(
                n,
                likes_count=like_counts.get(n.id, 0),
                is_liked=(n.id in liked_comment_ids)
            )
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


class CommentLike(db.Model):
    __tablename__ = 'comment_likes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'))
    comment_id = db.Column(db.Integer, db.ForeignKey('comments.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    __table_args__ = (db.UniqueConstraint('user_id', 'comment_id', name='unique_user_comment_like'),)


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
    content = db.Column(db.String(500), nullable=True)
    link = db.Column(db.String(500), nullable=True)
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
            'content': self.content,
            'link': self.link,
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


class CheckinLog(db.Model):
    __tablename__ = 'checkin_logs'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False, index=True)
    checkin_date = db.Column(db.Date, nullable=False, index=True)
    gained_exp = db.Column(db.Integer, nullable=False, default=0)
    streak_after = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user = db.relationship('User', foreign_keys=[user_id])
    __table_args__ = (db.UniqueConstraint('user_id', 'checkin_date', name='uniq_user_checkin_date'),)


class AppSetting(db.Model):
    __tablename__ = 'app_settings'
    id = db.Column(db.Integer, primary_key=True)
    setting_key = db.Column(db.String(80), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.String(2000), nullable=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


class Report(db.Model):
    __tablename__ = 'reports'
    id = db.Column(db.Integer, primary_key=True)
    reporter_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False)
    target_type = db.Column(db.String(20), nullable=False, default='user')
    target_id = db.Column(db.BigInteger, nullable=False, default=0)
    reported_user_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=True)
    reason = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), default='pending')
    admin_note = db.Column(db.String(500), nullable=True)
    admin_notes = db.Column(db.String(500), nullable=True)
    result_notified_at = db.Column(db.DateTime, nullable=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    reporter = db.relationship('User', foreign_keys=[reporter_id])
    reported_user = db.relationship('User', foreign_keys=[reported_user_id])
    post = db.relationship('Post')

    def admin_notes_text(self):
        # 统一以 admin_notes 为主；admin_note 为历史兼容字段，迁移完成后可移除。
        return self.admin_notes if self.admin_notes is not None else self.admin_note

    def to_dict(self):
        return {
            'id': self.id,
            'reporter_id': self.reporter_id,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'reported_user_id': self.reported_user_id,
            'post_id': self.post_id,
            'reason': self.reason,
            'status': self.status,
            'admin_notes': self.admin_notes_text(),
            'result_notified_at': self.result_notified_at.isoformat() if self.result_notified_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'reporter_nickname': self.reporter.nickname if self.reporter else None,
            'reported_nickname': self.reported_user.nickname if self.reported_user else None,
            'post_title': self.post.title[:50] if self.post and self.post.title else None,
        }


class Announcement(db.Model):
    __tablename__ = 'announcements'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.String(1000), nullable=False)
    entry_type = db.Column(db.String(20), default='announcement', index=True)  # announcement|activity
    level = db.Column(db.String(20), default='info')  # info|warning|critical
    is_active = db.Column(db.Boolean, default=True, index=True)
    starts_at = db.Column(db.DateTime, nullable=True, index=True)
    expires_at = db.Column(db.DateTime, nullable=True, index=True)
    created_by = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    creator = db.relationship('User', foreign_keys=[created_by])

    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'entry_type': self.entry_type,
            'level': self.level,
            'is_active': self.is_active,
            'starts_at': self.starts_at.isoformat() if self.starts_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
            'created_by': self.created_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


class Series(db.Model):
    __tablename__ = 'series'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(1000), nullable=True)
    cover_image = db.Column(db.String(500), nullable=True)
    author_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False, index=True)
    is_public = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, index=True)

    author = db.relationship('User', foreign_keys=[author_id])

    def to_dict(self, include_posts=False):
        payload = {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'cover_image': self.cover_image,
            'author_id': self.author_id,
            'is_public': bool(self.is_public),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
        if include_posts:
            links = SeriesPost.query.filter_by(series_id=self.id).order_by(SeriesPost.order_index.asc(), SeriesPost.id.asc()).all()
            payload['posts'] = [row.to_dict() for row in links]
        return payload


class SeriesPost(db.Model):
    __tablename__ = 'series_posts'
    id = db.Column(db.Integer, primary_key=True)
    series_id = db.Column(db.Integer, db.ForeignKey('series.id'), nullable=False, index=True)
    post_id = db.Column(db.Integer, db.ForeignKey('posts.id'), nullable=False, index=True)
    order_index = db.Column(db.Integer, nullable=False, default=1, index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    series = db.relationship('Series', backref=db.backref('series_posts', lazy='dynamic', cascade='all, delete-orphan'))
    post = db.relationship('Post', backref=db.backref('series_links', lazy='dynamic', cascade='all, delete-orphan'))
    __table_args__ = (db.UniqueConstraint('series_id', 'post_id', name='uniq_series_post'),)

    def to_dict(self):
        p = self.post
        return {
            'id': self.id,
            'series_id': self.series_id,
            'post_id': self.post_id,
            'order_index': self.order_index,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'post': {
                'id': p.id,
                'title': p.title,
                'cover_image': p.cover_image,
                'created_at': p.created_at.isoformat() if p and p.created_at else None,
            } if p else None
        }


class AdminAuditLog(db.Model):
    __tablename__ = 'admin_audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.BigInteger, db.ForeignKey('users.id'), nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False, index=True)
    target_type = db.Column(db.String(30), nullable=True, index=True)
    target_id = db.Column(db.String(64), nullable=True, index=True)
    details = db.Column(db.String(1000), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    admin = db.relationship('User', foreign_keys=[admin_id])

    def to_dict(self):
        return {
            'id': self.id,
            'admin_id': self.admin_id,
            'action': self.action,
            'target_type': self.target_type,
            'target_id': self.target_id,
            'details': self.details,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }


ALLOWED_AVATARS = ['👻', '💀', '👽', '👾', '🤖', '🎃', '🧛', '🧟', '🧞', '🧝', '🧙', '🧚', '🧜', '👼', '👿', '👺', '👹', '🤡', '💩', '🦄']


def get_random_avatar():
    return random.choice(ALLOWED_AVATARS)
