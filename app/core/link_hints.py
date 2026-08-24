"""Link format hints per social platform."""

from __future__ import annotations

LINK_HINTS: dict[str, str] = {
    "instagram": (
        "Ссылка на пост/рилс/профиль, например:\n"
        "<code>https://www.instagram.com/p/XXXX/</code> или профиль"
    ),
    "youtube": (
        "Ссылка на видео/канал/шортс, например:\n"
        "<code>https://www.youtube.com/watch?v=XXXX</code>"
    ),
    "tiktok": (
        "Ссылка на видео или профиль TikTok, например:\n"
        "<code>https://www.tiktok.com/@user/video/123</code>"
    ),
    "telegram": (
        "Ссылка на пост или канал, например:\n"
        "<code>https://t.me/channel/123</code> или <code>https://t.me/username</code>"
    ),
    "vk": (
        "Ссылка на пост/клип/страницу VK, например:\n"
        "<code>https://vk.com/wall-123_456</code>"
    ),
    "twitter": (
        "Ссылка на пост или профиль X/Twitter, например:\n"
        "<code>https://x.com/user/status/123</code>"
    ),
    "facebook": (
        "Ссылка на пост или страницу Facebook"
    ),
    "twitch": (
        "Ссылка на канал или клип Twitch"
    ),
    "spotify": (
        "Ссылка на трек / альбом / плейлист Spotify"
    ),
    "discord": (
        "Ссылка-приглашение на сервер Discord"
    ),
    "soundcloud": (
        "Ссылка на трек или профиль SoundCloud"
    ),
    "linkedin": (
        "Ссылка на пост или профиль LinkedIn"
    ),
    "threads": (
        "Ссылка на пост Threads"
    ),
    "snapchat": (
        "Ссылка / username Snapchat"
    ),
    "pinterest": (
        "Ссылка на пин или профиль Pinterest"
    ),
    "rutube": (
        "Ссылка на видео Rutube"
    ),
    "likee": (
        "Ссылка на видео Likee"
    ),
    "reddit": (
        "Ссылка на пост Reddit"
    ),
    "kick": (
        "Ссылка на канал Kick"
    ),
    "trovo": (
        "Ссылка на канал Trovo"
    ),
    "other": (
        "Отправьте полную публичную ссылку на нужный объект"
    ),
}


def link_hint_for(platform: str | None) -> str:
    if not platform:
        return LINK_HINTS["other"]
    return LINK_HINTS.get(platform, LINK_HINTS["other"])
