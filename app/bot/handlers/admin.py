from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import broadcast_confirm_kb
from app.bot.states import BroadcastFSM
from app.core.config import get_settings
from app.db.models import Order, User
from app.panel import PanelClient
from app.panel.sync import sync_services_from_panel

router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


@router.message(Command("admin"))
async def admin_help(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer(
        "<b>Admin</b>\n"
        "/sync — обновить каталог услуг\n"
        "/panel_balance — баланс поставщика\n"
        "/stats — статистика\n"
        "/broadcast — рассылка всем пользователям"
    )


@router.message(Command("sync"))
async def admin_sync(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    await message.answer("Синхронизация...")
    stats = await sync_services_from_panel(session)
    await message.answer(f"Готово: {stats}")


@router.message(Command("panel_balance"))
async def admin_panel_balance(message: Message) -> None:
    if not _is_admin(message.from_user.id):
        return
    async with PanelClient() as client:
        balance = await client.get_balance()
    await message.answer(f"Баланс поставщика: <b>${balance}</b>")


@router.message(Command("stats"))
async def admin_stats(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    users = await session.scalar(select(func.count()).select_from(User))
    orders = await session.scalar(select(func.count()).select_from(Order))
    profit = await session.scalar(
        select(func.coalesce(func.sum(Order.profit), 0)).where(Order.profit.is_not(None))
    )
    await message.answer(
        f"👥 Users: <b>{users}</b>\n"
        f"📦 Orders: <b>{orders}</b>\n"
        f"💵 Profit: <b>${profit}</b>"
    )


@router.message(Command("broadcast"))
async def broadcast_start(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.set_state(BroadcastFSM.waiting_text)
    await message.answer(
        "Отправьте текст рассылки (HTML можно).\n"
        "В конце автоматически добавится кнопка отписки — нет, "
        "пользователи отписываются командой /stop_mail.\n"
        "Или /cancel для отмены."
    )


@router.message(Command("cancel"))
async def broadcast_cancel_cmd(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    current = await state.get_state()
    if current and current.startswith("BroadcastFSM"):
        await state.clear()
        await message.answer("Рассылка отменена.")


@router.message(BroadcastFSM.waiting_text)
async def broadcast_text(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    text = message.html_text or message.text or ""
    if not text.strip():
        await message.answer("Пустой текст. Пришлите сообщение ещё раз.")
        return
    await state.update_data(broadcast_text=text)
    await state.set_state(BroadcastFSM.confirming)
    await message.answer(
        "Проверьте рассылку:\n\n" + text + "\n\nОтправить всем?",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "broadcast:cancel")
async def broadcast_cancel(callback, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.")
    await callback.answer()


@router.callback_query(F.data == "broadcast:send")
async def broadcast_send(callback, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    data = await state.get_data()
    text = data.get("broadcast_text")
    if not text:
        await callback.answer("Нет текста.", show_alert=True)
        return

    users = (
        await session.execute(
            select(User).where(User.is_banned.is_(False), User.broadcast_opt_out.is_(False))
        )
    ).scalars().all()

    await callback.message.edit_text(f"Отправка {len(users)} пользователям...")
    await state.clear()

    ok = fail = 0
    footer = "\n\n—\nОтписаться от рассылки: /stop_mail"
    for user in users:
        try:
            await callback.bot.send_message(user.tg_id, text + footer)
            ok += 1
        except Exception as exc:
            fail += 1
            logger.debug("Broadcast fail {}: {}", user.tg_id, exc)

    await callback.message.answer(f"Готово. Успешно: <b>{ok}</b>, ошибок: <b>{fail}</b>")
    await callback.answer()
