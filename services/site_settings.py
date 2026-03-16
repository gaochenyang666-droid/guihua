from typing import Dict, Tuple


def get_setting_value(app_setting_model, setting_key, default_value=''):
    row = app_setting_model.query.filter_by(setting_key=setting_key).first()
    if not row or row.setting_value is None:
        return default_value
    return str(row.setting_value).strip()


def set_setting_value(db_session, app_setting_model, setting_key, setting_value):
    row = app_setting_model.query.filter_by(setting_key=setting_key).first()
    if not row:
        row = app_setting_model(setting_key=setting_key, setting_value=setting_value)
        db_session.add(row)
    else:
        row.setting_value = setting_value
    return row


def get_group_link_urls(app_setting_model, setting_keys: Dict[str, str]) -> Dict[str, str]:
    return {
        'co_create_url': get_setting_value(app_setting_model, setting_keys['co_create'], ''),
        'core_url': get_setting_value(app_setting_model, setting_keys['core'], '')
    }


def validate_group_link_urls(co_url, core_url) -> Tuple[bool, str]:
    for val in (co_url, core_url):
        if val and not (
            val.startswith('https://t.me/')
            or val.startswith('http://t.me/')
            or val.startswith('https://telegram.me/')
        ):
            return False, '群链接仅支持 Telegram（t.me / telegram.me）'
        if len(val or '') > 1000:
            return False, '链接过长'
    return True, ''
