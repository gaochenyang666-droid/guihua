def build_admin_stats(user_model, post_model, fee_usdt_raw, decimals, redis_status=None):
    total_users = user_model.query.count()
    web3_users = user_model.query.filter(user_model.address != None).count()
    web2_users = total_users - web3_users

    total_posts = post_model.query.count()
    web3_posts = post_model.query.filter(post_model.post_type == 1).count()
    web2_posts = total_posts - web3_posts

    fee_usdt = round(fee_usdt_raw / (10 ** decimals), 4)
    total_revenue_raw = web3_posts * fee_usdt_raw
    total_revenue_usdt = total_revenue_raw / (10 ** decimals)

    payload = {
        'users': {
            'total': total_users,
            'web3': web3_users,
            'web2': web2_users,
            'retention_rate': 'N/A',
        },
        'posts': {
            'total': total_posts,
            'web3': web3_posts,
            'web2': web2_posts,
        },
        'revenue': {
            'total_usdt': round(total_revenue_usdt, 2),
            'fee_per_post_usdt': fee_usdt,
        },
    }
    if redis_status is not None:
        payload['redis'] = redis_status
    return payload
