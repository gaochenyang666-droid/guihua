#!/usr/bin/env python3
"""轻量前端 smoke：检查首页脚本链路、帖子 API 与若干页面壳。"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request

# 可选：GUIHUA_SKIP_SSL_VERIFY=1 时跳过 SSL 校验（仅本地跑 suite 用）
try:
    from _ssl_skip import maybe_disable_ssl_verify
except ImportError:
    def maybe_disable_ssl_verify():
        pass


REQUIRED_HOME_SNIPPETS = [
    "/static/modal-interact.js",
    "/static/share.js",
    "/static/auth.js",
    "/static/feed.js",
    "/static/home-shell.js",
    "/static/home-notices.js",
    "/static/utility-panels.js",
    "/static/admin.js",
    "/static/index.js",
    "postGrid",
]


def fetch_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "guihua-smoke/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        return resp.read().decode("utf-8", errors="replace")


def fetch_json(url: str) -> dict:
    return json.loads(fetch_text(url))


def assert_contains(text: str, needle: str, label: str) -> None:
    if needle not in text:
        raise AssertionError(f"{label}: missing `{needle}`")


def main() -> int:
    maybe_disable_ssl_verify()
    base = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:5012").rstrip("/")
    try:
        home = fetch_text(base + "/")
        for snippet in REQUIRED_HOME_SNIPPETS:
            assert_contains(home, snippet, "homepage")

        posts = fetch_json(base + "/api/posts?page=1&sort=new")
        post_list = posts.get("posts") or []
        print(f"posts_count={len(post_list)}")

        public_usernames = []
        for post in post_list:
            username = str((((post or {}).get("author") or {}).get("username")) or "").strip()
            if username and username not in public_usernames:
                public_usernames.append(username)

        if post_list:
            first_id = post_list[0].get("id")
            if first_id is not None:
                detail = fetch_text(base + f"/post/{urllib.parse.quote(str(first_id))}")
                assert_contains(detail, "seo-story-article", "post detail")
                assert_contains(detail, "<article", "post detail")
                print(f"detail_ok={first_id}")

        notices = fetch_text(base + "/notices?type=activity")
        assert_contains(notices, "/static/notices.js", "notices page")
        assert_contains(notices, "list-page-shell", "notices page")
        print("notices_ok=1")

        notifications = fetch_text(base + "/notifications")
        assert_contains(notifications, "/static/notifications.js", "notifications page")
        assert_contains(notifications, "list-page-shell", "notifications page")
        print("notifications_ok=1")

        profile_ok = False
        for username in public_usernames:
            profile_url = base + f"/profile?user={urllib.parse.quote(username)}"
            profile_page = fetch_text(profile_url)
            if "/static/profile.js" in profile_page and "profileArea" in profile_page:
                profile_ok = True
                break
        if not profile_ok:
            if public_usernames:
                raise AssertionError("profile page: missing `/static/profile.js`")
            print("profile_skipped=1")
        else:
            print("profile_ok=1")

        studio_page = fetch_text(base + "/studio")
        assert_contains(studio_page, "studioView", "studio page")
        assert_contains(studio_page, "step1", "studio page")
        print("studio_ok=1")

        print("smoke_ok=1")
        return 0
    except (AssertionError, urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError) as exc:
        print(f"smoke_error={exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
