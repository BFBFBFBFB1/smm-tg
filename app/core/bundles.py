"""Ready-made catalog packages (bundles)."""

from __future__ import annotations

# keywords_any: match if ANY token is in service name (lowercase)
# exclude: reject if ANY token is in name
BUNDLES: list[dict] = [
    {
        "id": "tg_views_1k",
        "title": "Telegram · 1 000 просмотров",
        "platform": "telegram",
        "keywords_any": ("просмотр", "views", "view"),
        "exclude": ("истор", "story", "boost", "буст", "реакц", "голос", "репост"),
        "qty": 1000,
    },
    {
        "id": "tg_subs_100",
        "title": "Telegram · 100 участников",
        "platform": "telegram",
        "keywords_any": ("участник", "member", "subscriber", "подписчик"),
        "exclude": ("просмотр", "view", "реакц", "boost", "буст", "истор", "подписка:"),
        "qty": 100,
    },
    {
        "id": "ig_likes_1k",
        "title": "Instagram · 1 000 лайков",
        "platform": "instagram",
        "keywords_any": ("лайк", "like"),
        "exclude": ("авто-", "подпис", "follow", "просмотр", "view", "коммент", "сохране"),
        "qty": 1000,
    },
    {
        "id": "ig_followers_100",
        "title": "Instagram · 100 подписчиков",
        "platform": "instagram",
        "keywords_any": ("подписчик", "follower", "follow"),
        "exclude": ("лайк", "like", "просмотр", "view", "авто-", "коммент"),
        "qty": 100,
    },
    {
        "id": "yt_views_1k",
        "title": "YouTube · 1 000 просмотров",
        "platform": "youtube",
        "keywords_any": ("просмотр", "views", "view"),
        "exclude": ("лайк", "like", "подпис", "hour", "retention", "зрител", "live", "shorts"),
        "qty": 1000,
    },
    {
        "id": "tt_views_1k",
        "title": "TikTok · 1 000 просмотров",
        "platform": "tiktok",
        "keywords_any": ("просмотр", "views", "view"),
        "exclude": ("лайк", "like", "follow", "подпис", "live", "зрител", "share"),
        "qty": 1000,
    },
    {
        "id": "tt_likes_500",
        "title": "TikTok · 500 лайков",
        "platform": "tiktok",
        "keywords_any": ("лайк", "like"),
        "exclude": ("просмотр", "view", "follow", "подпис", "live", "comment", "коммент", "истор", "story"),
        "qty": 500,
    },
    {
        "id": "vk_likes_500",
        "title": "VK · 500 лайков",
        "platform": "vk",
        "keywords_any": ("лайк", "like"),
        "exclude": ("просмотр", "view", "подпис", "follow", "зрител", "live", "реакц"),
        "qty": 500,
    },
]


def get_bundle(bundle_id: str) -> dict | None:
    for item in BUNDLES:
        if item["id"] == bundle_id:
            return item
    return None
