import html
import os
import re
import unicodedata
from datetime import timezone


SITE_NAME = '诡话'
SITE_TITLE = '诡话 - 灵异故事与都市传说社区'
DEFAULT_DESCRIPTION = '诡话是一个收录灵异故事、真实诡事、都市传说、恐怖故事与民间怪谈的内容社区。'
DEFAULT_OG_IMAGE = '/static/logo.svg'

try:
    from pypinyin import lazy_pinyin  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    lazy_pinyin = None


def get_site_base_url(request=None):
    base = (os.environ.get('SITE_URL') or os.environ.get('PUBLIC_BASE_URL') or '').strip()
    if base:
        return base.rstrip('/')
    if request is not None:
        return (request.url_root or 'https://guihua.fun').rstrip('/')
    return 'https://guihua.fun'


def build_absolute_url(path, request=None):
    path_value = '/' + str(path or '').lstrip('/')
    return get_site_base_url(request) + path_value


def strip_html(value):
    text = re.sub(r'<[^>]+>', ' ', str(value or ''))
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def trim_text(value, max_chars):
    text = str(value or '').strip()
    if len(text) <= max_chars:
        return text
    return text[: max(1, int(max_chars))].rstrip() + '…'


def build_excerpt(content, min_chars=90, max_chars=140):
    text = strip_html(content)
    if not text:
        return ''
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    if len(cut) < min_chars:
        return cut.rstrip() + '…'
    return cut.rstrip() + '…'


def build_meta_description(raw_text, min_chars=70, max_chars=120):
    text = strip_html(raw_text)
    if not text:
        text = DEFAULT_DESCRIPTION
    if len(text) < min_chars:
        text = trim_text((text + ' ' + DEFAULT_DESCRIPTION).strip(), max_chars)
    return trim_text(text, max_chars)


def _slug_base(text):
    raw = str(text or '').strip()
    if not raw:
        return 'story'
    if lazy_pinyin:
        try:
            raw = ' '.join(lazy_pinyin(raw))
        except Exception:
            raw = str(text or '').strip()
    normalized = unicodedata.normalize('NFKD', raw)
    ascii_text = normalized.encode('ascii', 'ignore').decode('ascii')
    cleaned = re.sub(r'[^a-zA-Z0-9]+', '-', ascii_text).strip('-').lower()
    if cleaned:
        return re.sub(r'-{2,}', '-', cleaned)
    fallback = re.sub(r'[\W_]+', '-', str(text or '')).strip('-').lower()
    fallback = re.sub(r'-{2,}', '-', fallback)
    return fallback or 'story'


def build_unique_post_slug(db_session, post_model, title, current_post_id=None, suffix_seed=None):
    base = _slug_base(title)
    suffix = str(suffix_seed or current_post_id or '').strip()
    candidate = base
    counter = 2

    while True:
        query = db_session.query(post_model).filter(post_model.slug == candidate)
        if current_post_id is not None:
            query = query.filter(post_model.id != current_post_id)
        exists = db_session.query(query.exists()).scalar()
        if not exists:
            return candidate
        if suffix:
            candidate = f'{base}-{suffix}'
            suffix = ''
        else:
            candidate = f'{base}-{counter}'
            counter += 1


def ensure_post_seo_fields(db_session, post, post_model, *, refresh_excerpt=False):
    changed = False
    if refresh_excerpt or not getattr(post, 'excerpt', None):
        excerpt = build_excerpt(getattr(post, 'content', ''))
        if excerpt != getattr(post, 'excerpt', None):
            post.excerpt = excerpt
            changed = True
    if not getattr(post, 'slug', None):
        post.slug = build_unique_post_slug(
            db_session,
            post_model,
            getattr(post, 'title', None),
            current_post_id=getattr(post, 'id', None),
            suffix_seed=getattr(post, 'id', None),
        )
        changed = True
    return changed


def story_path(post):
    slug = (getattr(post, 'slug', None) or '').strip()
    if slug:
        return f'/story/{slug}'
    return f"/post/{int(getattr(post, 'id', 0) or 0)}"


def derive_category(post):
    region = str(getattr(post, 'region', '') or '').strip()
    if region and region != '其他':
        return {'name': f'{region}诡事', 'slug': _slug_base(region)}
    return {'name': '灵异故事', 'slug': 'lingyi'}


def build_seo_meta(*, title, description=None, canonical=None, og_type='website', image=None,
                   robots='index,follow', json_ld=None, twitter_card='summary_large_image'):
    final_title = trim_text(title or SITE_TITLE, 80)
    final_description = build_meta_description(description or DEFAULT_DESCRIPTION)
    final_image = image or DEFAULT_OG_IMAGE
    payload = {
        'title': final_title,
        'description': final_description,
        'canonical': canonical,
        'og_title': final_title,
        'og_description': final_description,
        'og_type': og_type,
        'og_image': final_image,
        'twitter_card': twitter_card,
        'robots': robots,
        'json_ld': json_ld or [],
    }
    return payload


def build_breadcrumb_json_ld(items, request=None):
    item_list = []
    for idx, item in enumerate(items or [], start=1):
        if not item.get('name') or not item.get('url'):
            continue
        item_list.append({
            '@type': 'ListItem',
            'position': idx,
            'name': item['name'],
            'item': build_absolute_url(item['url'], request),
        })
    return {
        '@context': 'https://schema.org',
        '@type': 'BreadcrumbList',
        'itemListElement': item_list,
    }


def build_article_json_ld(post, author_name, canonical_url, request=None, image=None):
    published_at = getattr(post, 'created_at', None)
    updated_at = getattr(post, 'updated_at', None) or published_at
    if published_at and not published_at.tzinfo:
        published_at = published_at.replace(tzinfo=timezone.utc)
    if updated_at and not updated_at.tzinfo:
        updated_at = updated_at.replace(tzinfo=timezone.utc)
    return {
        '@context': 'https://schema.org',
        '@type': 'BlogPosting',
        'headline': getattr(post, 'seo_title', None) or getattr(post, 'title', ''),
        'description': build_meta_description(getattr(post, 'seo_description', None) or getattr(post, 'excerpt', None) or getattr(post, 'content', '')),
        'datePublished': published_at.isoformat() if published_at else None,
        'dateModified': updated_at.isoformat() if updated_at else None,
        'author': {
            '@type': 'Person',
            'name': author_name,
        },
        'mainEntityOfPage': canonical_url,
        'image': build_absolute_url(image or DEFAULT_OG_IMAGE, request),
        'articleBody': strip_html(getattr(post, 'content', '')),
        'publisher': {
            '@type': 'Organization',
            'name': SITE_NAME,
            'logo': {
                '@type': 'ImageObject',
                'url': build_absolute_url('/static/logo.svg', request),
            },
        },
    }


def build_collection_json_ld(title, description, canonical_url):
    return {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': title,
        'description': build_meta_description(description),
        'url': canonical_url,
    }


def build_website_json_ld(request=None):
    base_url = get_site_base_url(request)
    return {
        '@context': 'https://schema.org',
        '@type': 'WebSite',
        'name': SITE_NAME,
        'url': base_url,
        'potentialAction': {
            '@type': 'SearchAction',
            'target': f'{base_url}/stories?q={{search_term_string}}',
            'query-input': 'required name=search_term_string',
        },
    }
