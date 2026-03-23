import json
import urllib.parse

from flask import Blueprint, render_template, request, redirect, abort
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from extensions import db
from models import Comment, CommentLike, Post, User, build_comment_tree
from utils.security import _get_optional_jwt_payload
from services.seo import (
    SITE_TITLE,
    build_absolute_url,
    build_article_json_ld,
    build_breadcrumb_json_ld,
    build_collection_json_ld,
    build_excerpt,
    build_meta_description,
    build_seo_meta,
    build_website_json_ld,
    derive_category,
    ensure_post_seo_fields,
    get_site_base_url,
    story_path,
)

pages_bp = Blueprint('pages', __name__)


HOME_INTRO = (
    '诡话是一个收录灵异故事、真实诡事、都市传说、恐怖故事与民间怪谈的内容社区。'
    '这里既有用户投稿的夜半见闻，也有整理自民间传说、校园怪谈与都市异闻的长篇故事，'
    '方便读者持续追更、检索与收藏。'
)

SMOKE_POST_FILTERS = (
    Post.title.ilike('QA 系列帖 %'),
    Post.title.ilike('QA Smoke Post %'),
    Post.content.ilike('%series smoke%'),
    Post.content.ilike('%Smoke content for admin flow.%'),
)


def _page_num():
    return max(1, request.args.get('page', 1, type=int))


def _visible_posts_query():
    return Post.query.options(joinedload(Post.author)).filter_by(is_hidden=False).filter(~or_(*SMOKE_POST_FILTERS))


def _story_list_item(post):
    return {
        'id': post.id,
        'title': post.title,
        'slug': post.slug,
        'url': story_path(post),
        'excerpt': post.excerpt or build_excerpt(post.content or ''),
        'cover_image': post.cover_image,
        'author_name': (post.author.nickname or post.author.username) if post.author else '匿名投稿',
        'created_at': post.created_at,
        'updated_at': getattr(post, 'updated_at', None) or post.created_at,
        'view_count': int(getattr(post, 'view_count', 0) or 0),
        'tags': post.to_dict().get('tags', []),
        'category': derive_category(post),
    }


def _paginate_story_query(query, per_page=12):
    pagination = query.paginate(page=_page_num(), per_page=per_page, error_out=False)
    return pagination, [_story_list_item(row) for row in pagination.items]


def _seo_story_context(post):
    category = derive_category(post)
    author_name = '匿名投稿'
    if post.author:
        author_name = post.author.nickname or post.author.username or author_name
    canonical = build_absolute_url(story_path(post), request)
    title = (post.seo_title or post.title or '').strip() + '｜诡话'
    description = post.seo_description or post.excerpt or post.content or ''
    breadcrumbs = [
        {'name': '首页', 'url': '/'},
        {'name': '故事列表', 'url': '/stories'},
        {'name': category['name'], 'url': '/stories'},
        {'name': post.title, 'url': story_path(post)},
    ]
    seo = build_seo_meta(
        title=title,
        description=description,
        canonical=canonical,
        og_type='article',
        image=build_absolute_url(post.cover_image or '/static/logo.svg', request),
        json_ld=[
            build_article_json_ld(post, author_name, canonical, request, post.cover_image or '/static/logo.svg'),
            build_breadcrumb_json_ld(breadcrumbs, request),
        ],
    )
    return seo, breadcrumbs


def _find_related_posts(post, limit=8):
    tags = post.to_dict().get('tags', [])
    related = []
    seen = {post.id}
    if tags:
        tag_filters = []
        for tag in tags[:4]:
            escaped = str(tag).replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            tag_filters.append(Post.tags.ilike(f'%"{escaped}"%', escape='\\'))
        if tag_filters:
            rows = _visible_posts_query().filter(Post.id != post.id).filter(or_(*tag_filters)).order_by(Post.created_at.desc()).limit(limit).all()
            for row in rows:
                if row.id not in seen:
                    related.append(row)
                    seen.add(row.id)
    if len(related) < limit:
        rows = _visible_posts_query().filter(Post.id != post.id, Post.region == post.region).order_by(Post.created_at.desc()).limit(limit).all()
        for row in rows:
            if row.id not in seen:
                related.append(row)
                seen.add(row.id)
                if len(related) >= limit:
                    break
    if len(related) < limit:
        rows = _visible_posts_query().filter(Post.id != post.id).order_by(Post.created_at.desc()).limit(limit).all()
        for row in rows:
            if row.id not in seen:
                related.append(row)
                if len(related) >= limit:
                    break
    return [_story_list_item(row) for row in related[:limit]]


def _prev_next_posts(post):
    prev_post = _visible_posts_query().filter(Post.created_at < post.created_at).order_by(Post.created_at.desc()).first()
    next_post = _visible_posts_query().filter(Post.created_at > post.created_at).order_by(Post.created_at.asc()).first()
    return (
        _story_list_item(prev_post) if prev_post else None,
        _story_list_item(next_post) if next_post else None,
    )


def _build_story_comments_seed(post):
    payload = _get_optional_jwt_payload()
    current_user_id = payload.get('user_id') if payload else None
    all_comments = Comment.query.filter_by(post_id=post.id).options(joinedload(Comment.author)).order_by(Comment.created_at.asc()).all()
    comment_like_counts = {}
    liked_comment_ids = set()
    comment_ids = [c.id for c in all_comments]
    if comment_ids:
        like_rows = db.session.query(
            CommentLike.comment_id, db.func.count(CommentLike.id)
        ).filter(
            CommentLike.comment_id.in_(comment_ids)
        ).group_by(CommentLike.comment_id).all()
        comment_like_counts = {row[0]: int(row[1] or 0) for row in like_rows}
        if current_user_id:
            liked_comment_ids = {
                row.comment_id for row in CommentLike.query.filter(
                    CommentLike.user_id == current_user_id,
                    CommentLike.comment_id.in_(comment_ids)
                ).all()
            }
    return {
        'id': post.id,
        'allow_comments': bool(post.allow_comments),
        'author': post.author.to_dict() if post.author else {'id': post.author_id, 'nickname': '匿名投稿', 'avatar': '👻'},
        'comments': build_comment_tree(
            all_comments,
            like_counts=comment_like_counts,
            liked_comment_ids=liked_comment_ids,
        ),
    }


@pages_bp.route('/')
def index():
    latest_rows = _visible_posts_query().order_by(Post.created_at.desc()).limit(8).all()
    hot_rows = _visible_posts_query().order_by(Post.view_count.desc(), Post.created_at.desc()).limit(8).all()
    seo = build_seo_meta(
        title=SITE_TITLE,
        description=HOME_INTRO,
        canonical=build_absolute_url('/', request),
        json_ld=[build_website_json_ld(request)],
    )
    home_faq = [
        {
            'question': '诡话主要收录什么内容？',
            'answer': '站内主要收录灵异故事、真实诡事、都市传说、恐怖故事以及民间怪谈，也欢迎用户投稿自己的离奇见闻。',
        },
        {
            'question': '这里的故事是真实事件还是创作？',
            'answer': '站内内容既包含用户投稿的真实经历，也包含整理或创作的故事文本。每篇故事页都会保留必要免责声明，方便读者自行判断。',
        },
        {
            'question': '如何查看更多同类故事？',
            'answer': '你可以浏览故事列表页，或在故事详情页继续查看相关推荐、上一篇、下一篇与同类故事入口。',
        },
    ]
    return render_template(
        'index.html',
        seo=seo,
        seo_home_intro=HOME_INTRO,
        seo_latest_posts=[_story_list_item(row) for row in latest_rows],
        seo_hot_posts=[_story_list_item(row) for row in hot_rows],
        home_faq=home_faq,
    )


@pages_bp.route('/stories')
def stories_page():
    q = (request.args.get('q') or '').strip()
    query = _visible_posts_query()
    if q:
        escaped = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        query = query.filter(or_(
            Post.title.ilike(f'%{escaped}%', escape='\\'),
            Post.content.ilike(f'%{escaped}%', escape='\\')
        ))
    query = query.order_by(Post.created_at.desc())
    pagination, stories = _paginate_story_query(query)
    page = _page_num()
    canonical = build_absolute_url('/stories' if not q and page == 1 else f'/stories?page={page}', request)
    robots = 'index,follow'
    if q:
        canonical = build_absolute_url('/stories', request)
        robots = 'noindex,follow'
    title = '灵异故事大全｜诡话'
    if page > 1:
        title = f'灵异故事大全 第 {page} 页｜诡话'
    seo = build_seo_meta(
        title=title,
        description='浏览诡话最新收录的灵异故事、真实诡事、都市传说与民间怪谈，支持分页阅读与持续追更。',
        canonical=canonical,
        robots=robots,
        json_ld=[build_collection_json_ld(title, '诡话故事列表页', canonical)],
    )
    return render_template(
        'stories.html',
        seo=seo,
        stories=stories,
        pagination=pagination,
        page=page,
        q=q,
        query_suffix=(f"&q={urllib.parse.quote(q)}" if q else ''),
    )


@pages_bp.route('/story/<slug>')
def story_page(slug):
    row = _visible_posts_query().filter(Post.slug == slug).first()
    if not row:
        abort(404)
    if ensure_post_seo_fields(db.session, row, Post):
        db.session.commit()
    seo, breadcrumbs = _seo_story_context(row)
    prev_post, next_post = _prev_next_posts(row)
    return render_template(
        'story.html',
        seo=seo,
        post=row,
        post_view=_story_list_item(row),
        story_comments_seed=json.dumps(_build_story_comments_seed(row), ensure_ascii=False),
        breadcrumbs=breadcrumbs,
        related_posts=_find_related_posts(row, limit=8),
        prev_post=prev_post,
        next_post=next_post,
        category=derive_category(row),
        story_faq=[
            {
                'question': '这篇故事是真实事件还是虚构故事？',
                'answer': '诡话会同时收录真实见闻与创作型内容，建议结合正文细节、作者说明与评论讨论自行判断。',
            },
            {
                'question': '如何投稿自己的灵异故事？',
                'answer': '你可以返回首页点击创作，按提示完成发布流程；若支付或永存流程中断，系统也会保留恢复发布入口。',
            },
            {
                'question': '如何查看更多同类故事？',
                'answer': '本文底部已经提供相关推荐、上一篇和下一篇，你也可以前往故事列表页继续浏览。',
            },
        ],
    )


@pages_bp.route('/post/<int:post_id>')
def post_page(post_id):
    row = _visible_posts_query().filter(Post.id == post_id).first_or_404()
    if ensure_post_seo_fields(db.session, row, Post):
        db.session.commit()
    return redirect(story_path(row), code=301)


@pages_bp.route('/about')
def about_page():
    seo = build_seo_meta(
        title='关于诡话｜灵异故事与都市传说社区',
        description='了解诡话的内容方向、投稿方式与社区定位。诡话专注于灵异故事、真实诡事、都市传说、恐怖故事与民间怪谈。',
        canonical=build_absolute_url('/about', request),
    )
    return render_template('about.html', seo=seo)


@pages_bp.route('/studio')
def studio():
    seo = build_seo_meta(
        title='创作台｜诡话',
        description='诡话创作台用于发布灵异故事与社区内容。',
        canonical=build_absolute_url('/studio', request),
        robots='noindex,nofollow',
    )
    return render_template('studio.html', seo=seo)


@pages_bp.route('/login')
def login_page():
    seo = build_seo_meta(
        title='登录诡话｜灵异故事社区',
        description='登录诡话，继续浏览灵异故事与都市传说内容。',
        canonical=build_absolute_url('/login', request),
        robots='noindex,nofollow',
    )
    return render_template('login.html', seo=seo)


@pages_bp.route('/profile')
def profile():
    user_param = request.args.get('user')
    if not user_param:
        payload = _get_optional_jwt_payload()
        if not payload or not payload.get('user_id'):
            return redirect('/login?next=%2Fprofile')
    seo = build_seo_meta(
        title='个人主页｜诡话',
        description='诡话个人主页与用户中心。',
        canonical=build_absolute_url('/profile', request),
        robots='noindex,nofollow',
    )
    return render_template('profile.html', seo=seo)


@pages_bp.route('/series/<int:series_id>')
def series_page(series_id):
    seo = build_seo_meta(
        title='系列合集｜诡话',
        description='诡话系列内容页。',
        canonical=build_absolute_url(f'/series/{series_id}', request),
    )
    return render_template('series.html', series_id=series_id, seo=seo)


@pages_bp.route('/notices')
def notices_page():
    notice_type = (request.args.get('type') or 'announcement').strip().lower()
    if notice_type not in ('announcement', 'activity'):
        notice_type = 'announcement'
    seo = build_seo_meta(
        title='公告中心｜诡话',
        description='诡话公告与活动信息。',
        canonical=build_absolute_url('/notices', request),
        robots='noindex,nofollow',
    )
    return render_template('notice_center.html', notice_type=notice_type, seo=seo)


@pages_bp.route('/notifications')
def notifications_page():
    seo = build_seo_meta(
        title='通知中心｜诡话',
        description='诡话用户通知中心。',
        canonical=build_absolute_url('/notifications', request),
        robots='noindex,nofollow',
    )
    return render_template('notifications.html', seo=seo)
