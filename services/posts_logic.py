import re
import bleach


MENTION_PATTERN = re.compile(r'@([A-Za-z0-9_\u4e00-\u9fff]{2,32})')


def build_post_precheck(user, data):
    title = (data.get('title') or '').strip()
    content_html = data.get('content') or ''
    issues = []
    warnings = []

    text_content = re.sub(r'<[^>]+>', '', content_html or '').strip()
    if not title:
        issues.append('标题不能为空')
    elif len(title) > 100:
        issues.append('标题不能超过 100 字')
    if not text_content:
        issues.append('正文不能为空')
    elif len(text_content) < 20:
        warnings.append('正文较短，建议补充细节提升可读性')
    image_count = len(re.findall(r'<img\b', content_html or '', flags=re.IGNORECASE))
    if image_count > 10:
        warnings.append('正文图片较多，移动端加载可能较慢')

    if not user.is_admin and not user.address:
        issues.append('请先绑定钱包地址再发布')

    return {
        'ok': len(issues) == 0,
        'issues': issues,
        'warnings': warnings,
        'stats': {
            'title_length': len(title),
            'text_length': len(text_content),
            'image_count': image_count
        }
    }


def normalize_tags(raw):
    values = []
    if isinstance(raw, str):
        values.extend(re.split(r'[,\s，、]+', raw))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                values.append(item)
    clean = []
    seen = set()
    for tag in values:
        t = bleach.clean((tag or '').strip(), tags=[], strip=True)
        t = t.lstrip('#').strip()
        if not t:
            continue
        if len(t) > 20:
            t = t[:20]
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        clean.append(t)
        if len(clean) >= 12:
            break
    return clean


def extract_mention_tokens(text_value):
    text = (text_value or '').strip()
    if not text:
        return []
    found = MENTION_PATTERN.findall(text)
    result = []
    seen = set()
    for token in found:
        name = token.strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def resolve_mentioned_users(tokens, username_lookup, nickname_lookup, exclude_user_id=None):
    users = []
    if not tokens:
        return users
    for token in tokens:
        user = username_lookup(token)
        if not user:
            user = nickname_lookup(token)
        if not user:
            continue
        if exclude_user_id and user.id == exclude_user_id:
            continue
        if any(u.id == user.id for u in users):
            continue
        users.append(user)
    return users


def series_can_view(series_obj, viewer=None):
    if not series_obj:
        return False
    if getattr(series_obj, 'is_public', False):
        return True
    if not viewer:
        return False
    if getattr(viewer, 'is_admin', False):
        return True
    return viewer.id == series_obj.author_id


def series_can_edit(series_obj, viewer):
    if not series_obj or not viewer:
        return False
    if getattr(viewer, 'is_admin', False):
        return True
    return viewer.id == series_obj.author_id
