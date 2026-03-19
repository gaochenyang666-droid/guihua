from datetime import datetime, timedelta, timezone


def china_today(now=None):
    now = now or datetime.now(timezone.utc)
    return (now + timedelta(hours=8)).date()


def get_user_level(user, calc_level_info):
    if getattr(user, 'is_admin', False):
        return 9999
    info = calc_level_info(getattr(user, 'experience_points', 0) or 0)
    return int(info.get('level', 1) or 1)


def build_group_links_for_user(user, co_url, core_url, calc_level_info):
    level = get_user_level(user, calc_level_info)
    is_admin = bool(getattr(user, 'is_admin', False))
    items = [
        {
            'key': 'co_create',
            'title': '共创群',
            'required_level': 5,
            'unlocked': is_admin or level >= 5,
            'configured': bool(co_url),
            'url': co_url if (is_admin or level >= 5) and co_url else None
        },
        {
            'key': 'core',
            'title': '核心群',
            'required_level': 10,
            'unlocked': is_admin or level >= 10,
            'configured': bool(core_url),
            'url': core_url if (is_admin or level >= 10) and core_url else None
        }
    ]
    return {
        'level': level,
        'level_label': '∞' if is_admin else f'Lv.{max(1, level)}',
        'admin_infinite_level': is_admin,
        'groups': items
    }


def build_legacy_achievements(user, definitions, post_count, is_admin=False, now=None):
    now = now or datetime.now(timezone.utc)
    years = 0
    if getattr(user, 'created_at', None):
        years = max(0, int((now - user.created_at).days // 365))
    has_wallet = bool(getattr(user, 'address', None))
    has_web2 = bool(getattr(user, 'username', None))
    onboarding_completed = has_wallet and has_web2 and post_count > 0
    unlocked_map = {
        'legacy_new_soul': True,
        'legacy_chain_traveler': is_admin or has_wallet,
        'legacy_wallet_bound': is_admin or has_wallet,
        'legacy_dual_identity': is_admin or (has_wallet and has_web2),
        'legacy_contract_psychic': is_admin or onboarding_completed,
        'legacy_first_post': is_admin or post_count >= 1,
        'legacy_post_10': is_admin or post_count >= 10,
        'legacy_post_100': is_admin or post_count >= 100,
        'legacy_post_1000': is_admin or post_count >= 1000,
        'legacy_year_1': is_admin or years >= 1,
        'legacy_year_5': is_admin or years >= 5,
        'legacy_year_10': is_admin or years >= 10,
        'legacy_admin_guardian': is_admin,
    }
    items = []
    for definition in definitions:
        items.append({
            'key': definition['key'],
            'title': definition['title'],
            'description': definition['description'],
            'min_level': 1,
            'wearable': bool(definition.get('wearable')),
            'legacy': True,
            'unlocked': bool(unlocked_map.get(definition['key'], False)),
            'equipped': False
        })
    return items


def build_achievements_for_user(user, base_definitions, legacy_definitions, post_count, calc_level_info):
    level = get_user_level(user, calc_level_info)
    is_admin = bool(getattr(user, 'is_admin', False))
    equipped_key = (getattr(user, 'equipped_achievement_key', None) or '').strip() or None
    can_equip = is_admin or level >= 3
    items = []
    for definition in base_definitions:
        min_level = int(definition.get('min_level', 1))
        unlocked = is_admin or level >= min_level
        items.append({
            'key': definition['key'],
            'title': definition['title'],
            'description': definition['description'],
            'min_level': min_level,
            'wearable': bool(definition.get('wearable')),
            'legacy': False,
            'group_key': definition.get('group_key'),
            'unlocked': unlocked,
            'equipped': bool(unlocked and equipped_key == definition['key'] and can_equip and definition.get('wearable'))
        })
    legacy_items = build_legacy_achievements(user, legacy_definitions, post_count, is_admin=is_admin)
    for item in legacy_items:
        if item.get('wearable') and can_equip and equipped_key == item['key'] and item['unlocked']:
            item['equipped'] = True
    items.extend(legacy_items)
    return {
        'level': level,
        'level_label': '∞' if is_admin else f'Lv.{max(1, level)}',
        'can_equip': can_equip,
        'equipped_key': equipped_key,
        'achievements': items
    }


def build_checkin_status(user, calc_level_info, checkin_exp_by_streak, bonus_days, bonus_exp, today=None):
    today = today or china_today()
    last_date = getattr(user, 'last_checkin_date', None)
    is_admin = bool(getattr(user, 'is_admin', False))
    already_checked = bool(last_date and last_date == today) or is_admin
    if is_admin:
        level_info = {
            'level': 9999,
            'total_exp': int(getattr(user, 'experience_points', 0) or 0),
            'level_current_exp': 0,
            'level_next_exp': 1,
            'level_progress': 1.0
        }
    else:
        level_info = calc_level_info(getattr(user, 'experience_points', 0) or 0)
    streak = int(getattr(user, 'checkin_streak', 0) or 0)
    if is_admin:
        base_reward = 0
        bonus_reward = 0
    else:
        base_reward = checkin_exp_by_streak(max(1, streak + 1))
        bonus_reward = bonus_exp if ((streak + 1) % bonus_days == 0) else 0
    return {
        'today': today.isoformat(),
        'admin_exempt': is_admin,
        'already_checked': already_checked,
        'last_checkin_date': last_date.isoformat() if last_date else None,
        'streak': streak,
        'experience_points': level_info['total_exp'],
        'level': level_info['level'],
        'level_label': '∞' if is_admin else f"Lv.{level_info['level']}",
        'level_current_exp': level_info['level_current_exp'],
        'level_next_exp': level_info['level_next_exp'],
        'level_progress': level_info['level_progress'],
        'next_reward': base_reward + bonus_reward,
        'next_bonus_reward': bonus_reward,
        'rule': {
            'base': 2,
            'max': 12,
            'streak_bonus_days': bonus_days,
            'streak_bonus_exp': bonus_exp,
            'formula': f'连续签到第N天经验=MIN(12, N*2)，每连续{bonus_days}天额外+{bonus_exp}'
        }
    }
