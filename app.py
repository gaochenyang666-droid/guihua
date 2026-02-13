import os
import random
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, session, send_from_directory
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import desc, UniqueConstraint, text
from flask_cors import CORS

app = Flask(__name__)
CORS(app)
app.secret_key = 'ULTRA_BEYOND_SAFE_2026_ALLEN'

# ================= 基础配置 =================
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'ghost_final.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ================= 静态页面路由 =================
@app.route('/')
def serve_index():
    return send_from_directory('.', 'index.html')

# ================= 数据库模型 =================

class User(db.Model):
    username = db.Column(db.String(50), primary_key=True)
    password = db.Column(db.String(100), nullable=False)
    avatar = db.Column(db.String(200))

class Post(db.Model):
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    author = db.Column(db.String(50), index=True)
    title = db.Column(db.String(200))
    content = db.Column(db.Text)
    likes_count = db.Column(db.Integer, default=0)
    comment_count = db.Column(db.Integer, default=0)
    heat = db.Column(db.Float, default=0.0, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)
    last_active_at = db.Column(db.DateTime, default=datetime.now, index=True)

class Comment(db.Model):
    id = db.Column(db.BigInteger, primary_key=True, autoincrement=True)
    post_id = db.Column(db.BigInteger, db.ForeignKey('post.id'), index=True)
    parent_id = db.Column(db.BigInteger, db.ForeignKey('comment.id'), nullable=True, index=True)
    author = db.Column(db.String(50))
    content = db.Column(db.Text)
    reply_count = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.now)

class UserAction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), db.ForeignKey('user.username'))
    post_id = db.Column(db.BigInteger, db.ForeignKey('post.id'))
    action = db.Column(db.String(10))
    __table_args__ = (UniqueConstraint('username', 'post_id', 'action', name='uq_action'),)

# ================= 核心业务逻辑 =================

def sync_post_heat(pid):
    p = Post.query.get(pid)
    if not p: return
    score = p.likes_count * 2 + p.comment_count * 5
    dt = (datetime.now() - p.last_active_at).total_seconds() / 3600
    p.heat = round(score / pow(dt + 2, 1.3), 6)
    db.session.commit()

# ================= 路由接口 =================

@app.route('/api/posts')
def get_posts():
    page = request.args.get('page', 1, type=int)
    sort_type = request.args.get('sort', 'new')
    query = Post.query
    if sort_type == 'hot':
        query = query.order_by(desc(Post.heat))
    else:
        query = query.order_by(desc(Post.created_at))
    posts = query.paginate(page=page, per_page=10, error_out=False).items
    return jsonify([{
        "id": p.id, "title": p.title, "author": p.author,
        "likes": p.likes_count, "comments": p.comment_count,
        "time": p.created_at.strftime("%m-%d %H:%M")
    } for p in posts])

@app.route('/api/action', methods=['POST'])
def toggle_action():
    u = session.get('user')
    if not u: return jsonify({"msg": "unauth"}), 401
    pid = request.json.get('post_id')
    act = 'like'
    exist = UserAction.query.filter_by(username=u, post_id=pid, action=act).first()
    if exist:
        db.session.delete(exist)
        Post.query.filter_by(id=pid).update({Post.likes_count: Post.likes_count - 1})
    else:
        try:
            new_act = UserAction(username=u, post_id=pid, action=act)
            db.session.add(new_act)
            db.session.flush()
            Post.query.filter_by(id=pid).update({
                Post.likes_count: Post.likes_count + 1,
                Post.last_active_at: datetime.now()
            })
        except:
            db.session.rollback()
            return jsonify({"msg": "already done"})
    db.session.commit()
    sync_post_heat(pid)
    return jsonify({"ok": True})

@app.route('/api/comment', methods=['POST'])
def add_comment():
    u = session.get('user')
    if not u: return jsonify({"msg": "unauth"}), 401
    data = request.json
    pid = data.get('post_id')
    parent_id = data.get('parent_id')
    new_c = Comment(post_id=pid, parent_id=parent_id, author=u, content=data.get('content'))
    db.session.add(new_c)
    Post.query.filter_by(id=pid).update({
        Post.comment_count: Post.comment_count + 1,
        Post.last_active_at: datetime.now()
    })
    if parent_id:
        Comment.query.filter_by(id=parent_id).update({Comment.reply_count: Comment.reply_count + 1})
    db.session.commit()
    sync_post_heat(pid)
    return jsonify({"id": new_c.id, "author": u})

@app.route('/api/comments/root')
def get_root_comments():
    pid = request.args.get('post_id')
    page = request.args.get('page', 1, type=int)
    items = Comment.query.filter_by(post_id=pid, parent_id=None) \
        .order_by(desc(Comment.created_at)) \
        .paginate(page=page, per_page=10).items
    return jsonify(
        [{"id": c.id, "author": c.author, "content": c.content, "reply_count": c.reply_count} for c in items])

@app.route('/api/comments/replies')
def get_replies():
    parent_id = request.args.get('parent_id')
    replies = Comment.query.filter_by(parent_id=parent_id).order_by(Comment.created_at.asc()).all()
    return jsonify([{"id": r.id, "author": r.author, "content": r.content} for r in replies])

@app.route('/api/login', methods=['POST'])
def login():
    u, p = request.json.get('u'), request.json.get('p')
    user = User.query.get(u)
    if user and user.password == p:
        session.permanent = True
        session['user'] = u
        return jsonify({"msg": "ok"})
    if not user:
        new_u = User(username=u, password=p)
        db.session.add(new_u)
        db.session.commit()
        session['user'] = u
        return jsonify({"msg": "reg_ok"})
    return jsonify({"msg": "fail"}), 401

@app.route('/api/me')
def me():
    u = session.get('user')
    if not u: return jsonify({"u": None})
    return jsonify({"u": u})

# ================= 初始化与环境适配 =================
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)