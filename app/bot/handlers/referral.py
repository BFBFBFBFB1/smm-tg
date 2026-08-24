from aiogram import F, Router
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu_kb
from app.db.models import User
from app.services.referrals import get_referral_stats, referral_link

router = Router(name="referral")


@router.message(F.text == "👥 Рефералы")
async def referral_info(message: Message, session: AsyncSession, db_user: User) -> None:
    stats = await get_referral_stats(session, db_user)
    me = await message.bot.get_me()
    link = referral_link(me.username or "bot", db_user.tg_id)
    percent = stats["percent"]

    text = (
        "👥 <b>Реферальная программа</b>\n\n"
        f"Приглашайте друзей и получайте <b>{percent:g}%</b> "
        "с каждой их оплаты заказа — на ваш баланс.\n\n"
        f"Ваша ссылка:\n<code>{link}</code>\n\n"
        f"Приглашено: <b>{stats['invited']}</b>\n"
        f"Начислений: <b>{stats['rewards_count']}</b>\n"
        f"Заработано: <b>${stats['earned']:.2f}</b>\n\n"
        "Отправьте ссылку друзьям. Бонус приходит автоматически после их оплаты."
    )
    await message.answer(text, reply_markup=main_menu_kb())

    # Ready-to-share message
    share = (
        "🔥 SMM-услуги: подписчики, просмотры, лайки\n"
        f"Закажи здесь: {link}"
    )
    await message.answer(
        "Сообщение для отправки друзьям:\n\n"
        f"<code>{share}</code>"
    )
