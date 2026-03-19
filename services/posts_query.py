import json
import traceback

from sqlalchemy import func, text
from sqlalchemy.orm import joinedload

from extensions import db
from models import Bookmark, Comment, CommentLike, Like, Post, User, Vote


def _build_top_comments(post_ids):
    """返回 {post_id: {id, content, likes_count, author{...}}}"""
    top_map = {}
    if not post_ids:
        return top_map
    try:
        comments = Comment.query.options(joinedload(Comment.author)).filter(
            Comment.post_id.in_(post_ids)
        ).all()
        if not comments:
            return top_map
        comment_ids = [c.id for c in comments]
        like_rows = db.session.query(
            CommentLike.comment_id, func.count(CommentLike.id)
        ).filter(
            CommentLike.comment_id.in_(comment_ids)
        ).group_by(CommentLike.comment_id).all()
        like_counts = {r[0]: int(r[1] or 0) for r in like_rows}

        for c in comments:
            score = like_counts.get(c.id, 0)
            current = top_map.get(c.post_id)
            if (not current) or (score > current['_score']) or (
                score == current['_score'] and (c.created_at or 0) < (current['_created_at'] or 0)
            ):
                author = c.author.to_dict() if c.author else {'id': c.author_id, 'nickname': '匿名', 'avatar': '👻'}
                top_map[c.post_id] = {
                    '_score': score,
                    '_created_at': c.created_at,
                    'id': c.id,
                    'content': c.content or '',
                    'likes_count': score,
                    'author': {
                        'id': author.get('id'),
                        'nickname': author.get('nickname') or '匿名',
                        'avatar': author.get('avatar') or '👻'
                    }
                }
    except Exception:
        return {}
    for pid in list(top_map.keys()):
        top_map[pid].pop('_score', None)
        top_map[pid].pop('_created_at', None)
    return top_map


def apply_default_post_order(query):
    """统一帖子排序：特殊公告优先，再置顶，其次发布时间。"""
    return query.order_by(
        Post.is_special_announcement.desc(),
        Post.is_pinned.desc(),
        Post.pinned_at.desc(),
        Post.created_at.desc(),
    )


def get_posts_fallback(page, per_page, current_user_id):
    """兜底：仅查 posts 表，不 join users，避免缺列导致 500。返回 (posts_data, total, pages)。"""

    def _order_sql():
        return "ORDER BY is_special_announcement DESC, is_pinned DESC, pinned_at DESC, created_at DESC"

    try:
        query = Post.query.filter_by(is_hidden=False).order_by(
            Post.is_special_announcement.desc(),
            Post.is_pinned.desc(),
            Post.pinned_at.desc(),
            Post.created_at.desc()
        )
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
                       is_special_announcement, is_pinned, pinned_at, pinned_by, is_repost, original_post_id, repost_comment, tags
                FROM posts WHERE is_hidden = false
            """ + _order_sql() + " LIMIT :lim OFFSET :off"), {'lim': per_page, 'off': off}).fetchall()
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
    author_ids = {p.author_id if hasattr(p, 'author_id') else p[3] for p in posts}
    authors_map = {}
    if author_ids:
        try:
            users = User.query.filter(User.id.in_(list(author_ids))).all()
            for u in users:
                authors_map[u.id] = u.to_dict()
        except Exception:
            authors_map = {}
    user_likes = set()
    user_bookmarks = set()
    top_comments = {}
    like_counts = {}
    comment_counts = {}
    votes_map: dict[int, list] = {}
    if current_user_id and post_ids:
        try:
            user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
            user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
        except Exception:
            pass
    if post_ids:
        top_comments = _build_top_comments(post_ids)
        try:
            like_rows = db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id).all()
            like_counts = {r[0]: int(r[1] or 0) for r in like_rows}
        except Exception:
            pass
        try:
            comment_rows = db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all()
            comment_counts = {r[0]: int(r[1] or 0) for r in comment_rows}
        except Exception:
            pass
        try:
            all_votes = Vote.query.filter(Vote.post_id.in_(post_ids)).all()
            for v in all_votes:
                votes_map.setdefault(v.post_id, []).append({'id': v.id, 'option_text': getattr(v, 'option_text', ''), 'vote_count': getattr(v, 'vote_count', 0)})
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
                tags_raw = getattr(p, 'tags', None)
                post_type = getattr(p, 'post_type', 0)
                is_repost = getattr(p, 'is_repost', False)
                original_post_id = getattr(p, 'original_post_id', None)
                repost_comment = getattr(p, 'repost_comment', None)
                is_hidden = getattr(p, 'is_hidden', False)
                is_special_announcement = getattr(p, 'is_special_announcement', False)
                is_pinned = getattr(p, 'is_pinned', False)
                pinned_at = getattr(p, 'pinned_at', None)
                allow_comments = getattr(p, 'allow_comments', True)
                region = getattr(p, 'region', '其他')
                is_on_chain = getattr(p, 'is_on_chain', False)
                pinned_by = getattr(p, 'pinned_by', None)
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
                is_hidden = r[14] if len(r) > 14 else False
                allow_comments = r[15] if len(r) > 15 else True
                is_special_announcement = r[16] if len(r) > 16 else False
                is_pinned = r[17] if len(r) > 17 else False
                pinned_at = r[18] if len(r) > 18 else None
                pinned_by = r[19] if len(r) > 19 else None
                region = r[11] if len(r) > 11 else '其他'
                is_on_chain = r[12] if len(r) > 12 else False
                is_repost = r[20] if len(r) > 20 else False
                original_post_id = r[21] if len(r) > 21 else None
                repost_comment = r[22] if len(r) > 22 else None
                tags_raw = r[23] if len(r) > 23 else None

            images_list = []
            if images_raw:
                try:
                    images_list = json.loads(images_raw) if isinstance(images_raw, str) else (images_raw or [])
                except (TypeError, ValueError):
                    pass
            tags_list = []
            if tags_raw:
                try:
                    tags_list = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                except (TypeError, ValueError):
                    pass
            if not isinstance(tags_list, list):
                tags_list = []
            is_permanent = bool(tx_hash or ipfs_cid or is_on_chain or post_type == 1)
            p_likes_count = like_counts.get(pid, 0)
            p_comments_count = comment_counts.get(pid, 0)
            votes_list = votes_map.get(pid, [])

            if cover_image and str(cover_image).strip() == '/static/images/hua_cover.jpg':
                cover_image = None
            posts_data.append({
                'id': pid,
                'title': title,
                'content': content,
                'cover_image': cover_image,
                'images': images_list,
                'tags': tags_list,
                'author': authors_map.get(author_id, {'id': author_id, 'nickname': '用户', 'avatar': '👻', 'honor_title': '新魂'}),
                'view_count': view_count,
                'likes_count': p_likes_count,
                'comments_count': p_comments_count,
                'top_comment': top_comments.get(pid),
                'votes': votes_list,
                'is_liked': pid in user_likes,
                'is_bookmarked': pid in user_bookmarks,
                'tx_hash': tx_hash,
                'ipfs_cid': ipfs_cid,
                'post_type': post_type,
                'is_permanent': is_permanent,
                'created_at': created_at,
                'is_repost': is_repost,
                'original_post_id': original_post_id,
                'original_post': None,
                'repost_comment': repost_comment,
                'is_hidden': is_hidden,
                'is_special_announcement': is_special_announcement,
                'is_pinned': is_pinned,
                'pinned_at': pinned_at.isoformat() if hasattr(pinned_at, 'isoformat') and pinned_at else None,
                'pinned_by': pinned_by,
                'allow_comments': allow_comments,
                'region': region,
                'is_on_chain': is_on_chain,
            })
        except Exception as e:
            print(f"[get_posts fallback] skip row: {e}")
    return posts_data, total, pages


def build_posts_payload(sort_by, page, per_page, region, current_user_id):
    """帖子列表：内容来自 DB（Post.content），不请求 Arweave，无 content_arweave_id。"""
    try:
        query = Post.query.options(joinedload(Post.author))
        if sort_by == 'bookmarks':
            if current_user_id:
                query = query.join(Bookmark, Post.id == Bookmark.post_id).filter(
                    Bookmark.user_id == current_user_id
                ).filter(Post.is_hidden == False)
                query = apply_default_post_order(query)
            else:
                return {'posts': [], 'total': 0, 'pages': 0, 'current_page': page}, 200
        else:
            query = apply_default_post_order(query)
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
        top_comments = {}
        if post_ids:
            if current_user_id:
                user_likes = {l.post_id for l in Like.query.filter(Like.user_id == current_user_id, Like.post_id.in_(post_ids)).all()}
                user_bookmarks = {b.post_id for b in Bookmark.query.filter(Bookmark.user_id == current_user_id, Bookmark.post_id.in_(post_ids)).all()}
            like_rows = db.session.query(Like.post_id, func.count(Like.id)).filter(Like.post_id.in_(post_ids)).group_by(Like.post_id).all()
            like_counts = {r[0]: r[1] for r in like_rows}
            comment_rows = db.session.query(Comment.post_id, func.count(Comment.id)).filter(Comment.post_id.in_(post_ids)).group_by(Comment.post_id).all()
            comment_counts = {r[0]: r[1] for r in comment_rows}
            top_comments = _build_top_comments(post_ids)
        posts_data = []
        for p in posts:
            try:
                p_dict = p.to_dict(
                    current_user_id,
                    likes_count=like_counts.get(p.id, 0),
                    comments_count=comment_counts.get(p.id, 0),
                    is_liked=p.id in user_likes,
                    is_bookmarked=p.id in user_bookmarks,
                )
                p_dict['top_comment'] = top_comments.get(p.id)
                posts_data.append(p_dict)
            except Exception as e:
                print(f"[get_posts] skip post id={getattr(p, 'id', None)}: {e}")
        return {'posts': posts_data, 'total': pagination.total, 'pages': pagination.pages, 'current_page': page}, 200
    except Exception as e:
        traceback.print_exc()
        print(f"[get_posts] ERROR (using fallback): {e}")
        if sort_by == 'bookmarks':
            return {'posts': [], 'total': 0, 'pages': 0, 'current_page': page}, 200
        try:
            posts_data, total, pages = get_posts_fallback(page, per_page, current_user_id)
            return {'posts': posts_data, 'total': total, 'pages': pages, 'current_page': page}, 200
        except Exception as e2:
            traceback.print_exc()
            print(f"[get_posts] fallback also failed: {e2}")
            return {'error': 'Failed to load posts', 'posts': [], 'total': 0, 'pages': 0, 'current_page': page}, 500
