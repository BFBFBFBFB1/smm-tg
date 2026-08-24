from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import (
    admin_back_kb,
    admin_panel_kb,
    admin_promo_type_kb,
    admin_promos_kb,
    broadcast_confirm_kb,
)
from app.bot.states import AdminFSM, BroadcastFSM
from app.core.config import get_settings
from app.db.models import Order, OrderStatus, Payment, PaymentStatus, PromoCode, User
from app.panel import PanelClient
from app.panel.sync import sync_services_from_panel
from app.services.promos import PromoError, create_promo, format_promo, list_promos
from app.services.users import credit_balance, debit_balance, get_user_by_tg_id

router = Router(name="admin")


def _is_admin(user_id: int) -> bool:
    return user_id in get_settings().admin_ids


def _admin_home_text() -> str:
    return (
        "<b>Админ-панель</b>\n\n"
        "Выберите раздел или команды:\n"
        "<code>/give @user 1.50</code> — выдать баланс\n"
        "<code>/take @user 0.50</code> — снять баланс\n"
        "<code>/promo_off CODE</code> — выключить промокод"
    )


@router.message(Command("admin"))
async def admin_help(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    await state.clear()
    await message.answer(_admin_home_text(), reply_markup=admin_panel_kb())


@router.callback_query(F.data == "adm:home")
async def adm_home(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(_admin_home_text(), reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:stats")
@router.message(Command("stats"))
async def admin_stats(
    event: Message | CallbackQuery,
    session: AsyncSession,
) -> None:
    user_id = event.from_user.id
    if not _is_admin(user_id):
        return

    users = await session.scalar(select(func.count()).select_from(User))
    banned = await session.scalar(
        select(func.count()).select_from(User).where(User.is_banned.is_(True))
    )
    orders = await session.scalar(select(func.count()).select_from(Order))
    paid_orders = await session.scalar(
        select(func.count())
        .select_from(Order)
        .where(Order.status.not_in([OrderStatus.AWAITING_PAYMENT, OrderStatus.FAILED]))
    )
    revenue = await session.scalar(
        select(func.coalesce(func.sum(Order.sale_price), 0)).where(
            Order.status.in_(
                [
                    OrderStatus.PENDING,
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.COMPLETED,
                    OrderStatus.PARTIAL,
                ]
            )
        )
    )
    profit = await session.scalar(
        select(func.coalesce(func.sum(Order.profit), 0)).where(Order.profit.is_not(None))
    )
    payments = await session.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.status == PaymentStatus.PAID
        )
    )
    promos = await session.scalar(
        select(func.count()).select_from(PromoCode).where(PromoCode.is_active.is_(True))
    )

    text = (
        "<b>Статистика</b>\n\n"
        f"👥 Пользователи: <b>{users}</b> (бан: {banned})\n"
        f"📦 Заказы: <b>{orders}</b> (оплаченных: {paid_orders})\n"
        f"💵 Оборот: <b>${Decimal(revenue or 0):.2f}</b>\n"
        f"📈 Прибыль: <b>${Decimal(profit or 0):.2f}</b>\n"
        f"💳 Платежи: <b>${Decimal(payments or 0):.2f}</b>\n"
        f"🎟 Активных промо: <b>{promos}</b>"
    )

    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=admin_back_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=admin_back_kb())


@router.callback_query(F.data == "adm:panel_bal")
@router.message(Command("panel_balance"))
async def admin_panel_balance(event: Message | CallbackQuery) -> None:
    if not _is_admin(event.from_user.id):
        return
    async with PanelClient() as client:
        balance = await client.get_balance()
    text = f"Баланс поставщика: <b>${balance}</b>"
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, reply_markup=admin_back_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=admin_back_kb())


@router.callback_query(F.data == "adm:sync")
@router.message(Command("sync"))
async def admin_sync(event: Message | CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(event.from_user.id):
        return
    msg = event.message if isinstance(event, CallbackQuery) else event
    if isinstance(event, CallbackQuery):
        await event.message.edit_text("Синхронизация...")
        await event.answer()
    else:
        await event.answer("Синхронизация...")
    stats = await sync_services_from_panel(session)
    await msg.answer(f"Готово: {stats}", reply_markup=admin_back_kb())


# --- Promos ---


@router.callback_query(F.data == "adm:promos")
async def adm_promos(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text(
        "<b>Промокоды</b>\nСоздайте или посмотрите список.",
        reply_markup=admin_promos_kb(),
    )
    await callback.answer()


@router.callback_query(F.data == "adm:promo_list")
async def adm_promo_list(callback: CallbackQuery, session: AsyncSession) -> None:
    if not _is_admin(callback.from_user.id):
        return
    promos = await list_promos(session)
    if not promos:
        text = "Промокодов пока нет."
    else:
        text = "<b>Промокоды</b>\n\n" + "\n".join(format_promo(p) for p in promos[:30])
    await callback.message.edit_text(text, reply_markup=admin_promos_kb())
    await callback.answer()


@router.callback_query(F.data == "adm:promo_create")
async def adm_promo_create(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.promo_code)
    await callback.message.edit_text(
        "Введите код промокода (например <code>SALE10</code>):\n/cancel — отмена"
    )
    await callback.answer()


@router.message(AdminFSM.promo_code)
async def adm_promo_code_input(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    code = (message.text or "").strip().upper()
    if not code or code.startswith("/"):
        await message.answer("Введите код без /")
        return
    await state.update_data(promo_code=code)
    await state.set_state(AdminFSM.promo_type)
    await message.answer("Тип промокода:", reply_markup=admin_promo_type_kb())


@router.callback_query(AdminFSM.promo_type, F.data.startswith("adm:promo_type:"))
async def adm_promo_type(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    dtype = callback.data.split(":")[-1]
    await state.update_data(promo_type=dtype)
    await state.set_state(AdminFSM.promo_value)
    if dtype == "percent":
        hint = "Введите процент (например 10):"
    elif dtype == "balance":
        hint = "Сколько $ начислить на баланс (например 1.00):"
    else:
        hint = "Введите сумму скидки в $ (например 0.50):"
    await callback.message.edit_text(hint)
    await callback.answer()


@router.message(AdminFSM.promo_value)
async def adm_promo_value(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").replace(",", ".").strip()
    try:
        value = Decimal(raw)
    except Exception:
        await message.answer("Число, например 10 или 0.5")
        return
    await state.update_data(promo_value=str(value))
    await state.set_state(AdminFSM.promo_max_uses)
    await message.answer(
        "Макс. использований всего (число) или <code>0</code> = без лимита:"
    )


@router.message(AdminFSM.promo_max_uses)
async def adm_promo_max_uses(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not _is_admin(message.from_user.id):
        return
    raw = (message.text or "").strip()
    if not raw.isdigit():
        await message.answer("Введите целое число (0 = без лимита)")
        return
    max_uses = int(raw)
    data = await state.get_data()
    try:
        promo = await create_promo(
            session,
            code=data["promo_code"],
            discount_type=data["promo_type"],
            discount_value=Decimal(data["promo_value"]),
            max_uses=None if max_uses == 0 else max_uses,
        )
    except PromoError as exc:
        await message.answer(f"Ошибка: {exc.message}")
        await state.clear()
        return

    await state.clear()
    await message.answer(
        f"Создан промокод:\n{format_promo(promo)}",
        reply_markup=admin_promos_kb(),
    )


@router.message(Command("promo_off"))
async def promo_off(message: Message, session: AsyncSession) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Пример: /promo_off SALE10")
        return
    code = parts[1].strip().upper()
    promo = (
        await session.execute(select(PromoCode).where(PromoCode.code == code))
    ).scalar_one_or_none()
    if not promo:
        await message.answer("Не найден")
        return
    promo.is_active = False
    await session.flush()
    await message.answer(f"Выключен: {format_promo(promo)}")


# --- Give balance ---


@router.callback_query(F.data == "adm:give")
async def adm_give_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.give_balance_user)
    await callback.message.edit_text(
        "Кому выдать баланс?\n"
        "Отправьте @username или tg_id\n"
        "Или команда: <code>/give @user 1.50</code>\n"
        "/cancel — отмена"
    )
    await callback.answer()


@router.message(Command("give"))
async def give_cmd(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Пример: /give @username 1.50")
        return
    user = await _resolve_user(session, parts[1])
    if not user:
        await message.answer("Пользователь не найден (должен хотя бы раз написать боту)")
        return
    try:
        amount = Decimal(parts[2].replace(",", "."))
    except Exception:
        await message.answer("Сумма числом, например 1.50")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть > 0")
        return
    before = Decimal(user.balance)
    await credit_balance(session, user, amount)
    await state.clear()
    await message.answer(
        f"Баланс @{user.username or '—'} (<code>{user.tg_id}</code>): "
        f"${before:.2f} → <b>${Decimal(user.balance):.2f}</b>"
    )
    try:
        await message.bot.send_message(
            user.tg_id,
            f"Вам начислен баланс: <b>+${amount:.2f}</b>\n"
            f"Текущий баланс: <b>${Decimal(user.balance):.2f}</b>",
        )
    except Exception as exc:
        logger.debug("Notify give_balance failed: {}", exc)


@router.message(AdminFSM.give_balance_user)
async def adm_give_user(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    user = await _resolve_user(session, message.text or "")
    if not user:
        await message.answer("Не найден. @username или tg_id:")
        return
    await state.update_data(give_user_id=user.id)
    await state.set_state(AdminFSM.give_balance_amount)
    await message.answer(
        f"Юзер: @{user.username or '—'} · баланс ${Decimal(user.balance):.2f}\n"
        "Сумма пополнения в $:"
    )


@router.message(AdminFSM.give_balance_amount)
async def adm_give_amount(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        amount = Decimal((message.text or "").replace(",", ".").strip())
    except Exception:
        await message.answer("Число, например 0.20")
        return
    if amount <= 0:
        await message.answer("Сумма > 0")
        return
    data = await state.get_data()
    user = await session.get(User, data["give_user_id"])
    if not user:
        await state.clear()
        await message.answer("Юзер пропал")
        return
    before = Decimal(user.balance)
    await credit_balance(session, user, amount)
    await state.clear()
    await message.answer(
        f"Готово: @{user.username or '—'} ${before:.2f} → <b>${Decimal(user.balance):.2f}</b>",
        reply_markup=admin_back_kb(),
    )
    try:
        await message.bot.send_message(
            user.tg_id,
            f"Вам начислен баланс: <b>+${amount:.2f}</b>\n"
            f"Текущий баланс: <b>${Decimal(user.balance):.2f}</b>",
        )
    except Exception as exc:
        logger.debug("Notify give_balance failed: {}", exc)


# --- Take balance ---


@router.callback_query(F.data == "adm:take")
async def adm_take_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.take_balance_user)
    await callback.message.edit_text(
        "У кого снять баланс?\n"
        "Отправьте @username или tg_id\n"
        "Или команда: <code>/take @user 0.50</code>\n"
        "/cancel — отмена"
    )
    await callback.answer()


@router.message(Command("take"))
async def take_cmd(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 3:
        await message.answer("Пример: /take @username 0.50")
        return
    user = await _resolve_user(session, parts[1])
    if not user:
        await message.answer("Пользователь не найден (должен хотя бы раз написать боту)")
        return
    try:
        amount = Decimal(parts[2].replace(",", "."))
    except Exception:
        await message.answer("Сумма числом, например 0.50")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть > 0")
        return
    before = Decimal(user.balance)
    ok = await debit_balance(session, user, amount)
    if not ok:
        await message.answer(
            f"Недостаточно средств. Баланс @{user.username or '—'}: "
            f"<b>${before:.2f}</b>"
        )
        return
    await state.clear()
    await message.answer(
        f"Списано с @{user.username or '—'} (<code>{user.tg_id}</code>): "
        f"${before:.2f} → <b>${Decimal(user.balance):.2f}</b> (−${amount:.2f})"
    )
    try:
        await message.bot.send_message(
            user.tg_id,
            f"С вашего баланса списано: <b>−${amount:.2f}</b>\n"
            f"Текущий баланс: <b>${Decimal(user.balance):.2f}</b>",
        )
    except Exception as exc:
        logger.debug("Notify take_balance failed: {}", exc)


@router.message(AdminFSM.take_balance_user)
async def adm_take_user(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    user = await _resolve_user(session, message.text or "")
    if not user:
        await message.answer("Не найден. @username или tg_id:")
        return
    await state.update_data(take_user_id=user.id)
    await state.set_state(AdminFSM.take_balance_amount)
    await message.answer(
        f"Юзер: @{user.username or '—'} · баланс ${Decimal(user.balance):.2f}\n"
        "Сумма списания в $:"
    )


@router.message(AdminFSM.take_balance_amount)
async def adm_take_amount(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    if not _is_admin(message.from_user.id):
        return
    try:
        amount = Decimal((message.text or "").replace(",", ".").strip())
    except Exception:
        await message.answer("Число, например 0.20")
        return
    if amount <= 0:
        await message.answer("Сумма > 0")
        return
    data = await state.get_data()
    user = await session.get(User, data["take_user_id"])
    if not user:
        await state.clear()
        await message.answer("Юзер пропал")
        return
    before = Decimal(user.balance)
    ok = await debit_balance(session, user, amount)
    if not ok:
        await message.answer(
            f"Недостаточно средств. Баланс: <b>${before:.2f}</b>\n"
            "Введите меньшую сумму или /cancel"
        )
        return
    await state.clear()
    await message.answer(
        f"Списано: @{user.username or '—'} ${before:.2f} → "
        f"<b>${Decimal(user.balance):.2f}</b> (−${amount:.2f})",
        reply_markup=admin_back_kb(),
    )
    try:
        await message.bot.send_message(
            user.tg_id,
            f"С вашего баланса списано: <b>−${amount:.2f}</b>\n"
            f"Текущий баланс: <b>${Decimal(user.balance):.2f}</b>",
        )
    except Exception as exc:
        logger.debug("Notify take_balance failed: {}", exc)


# --- Find / ban ---


@router.callback_query(F.data == "adm:find")
async def adm_find_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.find_user)
    await callback.message.edit_text("Отправьте @username или tg_id\n/cancel — отмена")
    await callback.answer()


@router.message(AdminFSM.find_user)
async def adm_find_user(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    user = await _resolve_user(session, message.text or "")
    if not user:
        await message.answer("Не найден")
        return
    orders = await session.scalar(
        select(func.count()).select_from(Order).where(Order.user_id == user.id)
    )
    await state.clear()
    await message.answer(
        f"<b>Пользователь</b>\n"
        f"ID: <code>{user.id}</code>\n"
        f"TG: <code>{user.tg_id}</code> @{user.username or '—'}\n"
        f"Имя: {user.first_name or '—'}\n"
        f"Баланс: <b>${Decimal(user.balance):.2f}</b>\n"
        f"Заказов: {orders}\n"
        f"Бан: {'да' if user.is_banned else 'нет'}\n"
        f"Реф. заработано: ${Decimal(user.referral_earned or 0):.2f}",
        reply_markup=admin_back_kb(),
    )


@router.callback_query(F.data == "adm:ban")
async def adm_ban_start(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.set_state(AdminFSM.ban_user)
    await callback.message.edit_text(
        "Отправьте @username / tg_id — переключит бан/разбан\n/cancel — отмена"
    )
    await callback.answer()


@router.message(AdminFSM.ban_user)
async def adm_ban_user(message: Message, session: AsyncSession, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    user = await _resolve_user(session, message.text or "")
    if not user:
        await message.answer("Не найден")
        return
    user.is_banned = not user.is_banned
    await session.flush()
    await state.clear()
    status = "забанен" if user.is_banned else "разбанен"
    await message.answer(
        f"@{user.username or '—'} (<code>{user.tg_id}</code>) {status}",
        reply_markup=admin_back_kb(),
    )


@router.message(Command("cancel"))
async def admin_cancel(message: Message, state: FSMContext) -> None:
    if not _is_admin(message.from_user.id):
        return
    current = await state.get_state()
    if not current:
        return
    if current.startswith("AdminFSM") or current.startswith("BroadcastFSM"):
        await state.clear()
        await message.answer("Отменено.", reply_markup=admin_panel_kb())


async def _resolve_user(session: AsyncSession, raw: str) -> User | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("@"):
        text = text[1:]
    if text.isdigit():
        return await get_user_by_tg_id(session, int(text))
    result = await session.execute(
        select(User).where(func.lower(User.username) == text.lower())
    )
    return result.scalar_one_or_none()


# --- Broadcast ---


@router.callback_query(F.data == "adm:broadcast")
@router.message(Command("broadcast"))
async def broadcast_start(event: Message | CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(event.from_user.id):
        return
    await state.set_state(BroadcastFSM.waiting_text)
    text = (
        "Отправьте текст рассылки (HTML можно).\n"
        "Отписка у пользователей: /stop_mail\n"
        "/cancel — отмена."
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text)
        await event.answer()
    else:
        await event.answer(text)


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
async def broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    if not _is_admin(callback.from_user.id):
        return
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.", reply_markup=admin_panel_kb())
    await callback.answer()


@router.callback_query(F.data == "broadcast:send")
async def broadcast_send(callback: CallbackQuery, session: AsyncSession, state: FSMContext) -> None:
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

    await callback.message.answer(
        f"Готово. Успешно: <b>{ok}</b>, ошибок: <b>{fail}</b>",
        reply_markup=admin_panel_kb(),
    )
    await callback.answer()
