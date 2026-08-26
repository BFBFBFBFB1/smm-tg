from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from loguru import logger

from app.core.config import get_settings


def make_bot() -> Bot:
    """Build Bot with optional HTTP/SOCKS proxy (needed on VPS that cannot reach Telegram)."""
    settings = get_settings()
    proxy = (settings.telegram_proxy or "").strip() or None
    session = AiohttpSession(proxy=proxy) if proxy else AiohttpSession()
    if proxy:
        logger.info("Telegram proxy enabled")
    return Bot(
        token=settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
