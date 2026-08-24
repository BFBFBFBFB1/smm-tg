"""Map fine-grained panel categories to top-level social platforms."""

from __future__ import annotations

# slug -> (display_name, match keywords in category/service name)
PLATFORMS: list[tuple[str, str, tuple[str, ...]]] = [
    ("instagram", "Instagram", ("instagram", "insta")),
    ("youtube", "YouTube", ("youtube", "yt ")),
    ("tiktok", "TikTok", ("tiktok", "tik tok")),
    ("telegram", "Telegram", ("telegram", "tg ")),
    ("vk", "VK", ("vkontakte", " vk", "vk ", "вконтакте")),
    ("twitter", "Twitter / X", ("twitter", " x ", "tweet")),
    ("facebook", "Facebook", ("facebook", "fb ")),
    ("twitch", "Twitch", ("twitch",)),
    ("spotify", "Spotify", ("spotify",)),
    ("discord", "Discord", ("discord",)),
    ("soundcloud", "SoundCloud", ("soundcloud",)),
    ("linkedin", "LinkedIn", ("linkedin",)),
    ("threads", "Threads", ("threads",)),
    ("snapchat", "Snapchat", ("snapchat",)),
    ("pinterest", "Pinterest", ("pinterest",)),
    ("rutube", "Rutube", ("rutube",)),
    ("likee", "Likee", ("likee",)),
    ("reddit", "Reddit", ("reddit",)),
    ("kick", "Kick", ("kick",)),
    ("trovo", "Trovo", ("trovo",)),
]

OTHER = ("other", "Другое")


def detect_platform(category_name: str, service_name: str = "") -> tuple[str, str]:
    text = f" {category_name} {service_name} ".lower().replace("|", " ").replace("—", " ").replace("–", " ")
    for slug, title, keywords in PLATFORMS:
        for kw in keywords:
            if kw in text:
                return slug, title
    return OTHER


def platform_title(slug: str) -> str:
    for s, title, _ in PLATFORMS:
        if s == slug:
            return title
    return OTHER[1]
