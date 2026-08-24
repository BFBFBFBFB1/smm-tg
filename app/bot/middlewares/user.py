from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.services.users import get_or_create_user


class UserMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        session: AsyncSession | None = data.get("session")
        tg_user = None
        if isinstance(event, Message) and event.from_user:
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery) and event.from_user:
            tg_user = event.from_user

        if session and tg_user:
            settings = get_settings()
            user = await get_or_create_user(
                session,
                tg_id=tg_user.id,
                username=tg_user.username,
                first_name=tg_user.first_name,
                language=tg_user.language_code or settings.default_language,
            )
            if user.is_banned:
                if isinstance(event, Message):
                    await event.answer("⛔ Доступ ограничен. Обратитесь в поддержку.")
                elif isinstance(event, CallbackQuery):
                    await event.answer("Доступ ограничен.", show_alert=True)
                return None
            data["db_user"] = user

        return await handler(event, data)
