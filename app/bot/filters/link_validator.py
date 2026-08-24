import re

# Platform → list of compiled regexes for link validation
LINK_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "instagram": [
        re.compile(r"^https?://(www\.)?instagram\.com/.+", re.I),
        re.compile(r"^https?://(www\.)?instagr\.am/.+", re.I),
    ],
    "youtube": [
        re.compile(r"^https?://(www\.)?(youtube\.com|youtu\.be)/.+", re.I),
    ],
    "tiktok": [
        re.compile(r"^https?://(www\.)?(tiktok\.com|vm\.tiktok\.com)/.+", re.I),
    ],
    "telegram": [
        re.compile(r"^https?://(t\.me|telegram\.me)/.+", re.I),
        re.compile(r"^@[A-Za-z0-9_]{4,}$"),
    ],
    "vk": [
        re.compile(r"^https?://(www\.)?vk\.com/.+", re.I),
        re.compile(r"^https?://(www\.)?vk\.ru/.+", re.I),
    ],
    "twitter": [
        re.compile(r"^https?://(www\.)?(twitter\.com|x\.com)/.+", re.I),
    ],
    "x": [
        re.compile(r"^https?://(www\.)?(twitter\.com|x\.com)/.+", re.I),
    ],
    "twitch": [
        re.compile(r"^https?://(www\.)?twitch\.tv/.+", re.I),
    ],
    "facebook": [
        re.compile(r"^https?://(www\.)?(facebook\.com|fb\.com|fb\.watch)/.+", re.I),
    ],
    "spotify": [
        re.compile(r"^https?://open\.spotify\.com/.+", re.I),
    ],
    "discord": [
        re.compile(r"^https?://(discord\.gg|discord\.com)/.+", re.I),
    ],
    "soundcloud": [
        re.compile(r"^https?://(www\.)?soundcloud\.com/.+", re.I),
    ],
    "linkedin": [
        re.compile(r"^https?://(www\.)?linkedin\.com/.+", re.I),
    ],
    "threads": [
        re.compile(r"^https?://(www\.)?threads\.net/.+", re.I),
    ],
    "snapchat": [
        re.compile(r"^https?://(www\.)?snapchat\.com/.+", re.I),
    ],
    "pinterest": [
        re.compile(r"^https?://(www\.)?pinterest\.[a-z.]+/.+", re.I),
    ],
}

GENERIC_URL = re.compile(r"^https?://.+\..+", re.I)


def detect_platform(category_name: str | None) -> str | None:
    if not category_name:
        return None
    lowered = category_name.lower()
    for platform in LINK_PATTERNS:
        if platform in lowered:
            return platform
    return None


def validate_link(link: str, category_name: str | None = None) -> tuple[bool, str]:
    link = link.strip()
    if not link:
        return False, "Ссылка не может быть пустой."

    platform = detect_platform(category_name)
    if platform and platform in LINK_PATTERNS:
        for pattern in LINK_PATTERNS[platform]:
            if pattern.match(link):
                return True, link
        return (
            False,
            f"Некорректная ссылка для {category_name}. "
            f"Пример: ссылка на профиль/пост {platform}.",
        )

    if GENERIC_URL.match(link):
        return True, link
    return False, "Укажите корректную ссылку, начинающуюся с http:// или https://"
