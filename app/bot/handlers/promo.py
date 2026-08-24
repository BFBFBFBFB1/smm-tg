from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu_kb
from app.bot.states import PromoMenuFSM
from app.db.models import DiscountType, User
from app.services.promos import (
    PromoError,
    get_promo_by_code,
    is_balance_promo,
    normalize_code,
    redeem_balance_promo,
    validate_promo_for_user,
)

router = Router(name="promo")


@router.message(F.text == "🎟 Промокод")
async def promo_menu_start(message: Message, state: FSMContext, db_user: User) -> None:
    await state.set_state(PromoMenuFSM.entering)
    pending = db_user.pending_promo_code
    extra = ""
    if pending:
        extra = (
            f"\nСейчас сохранён для заказа: <code>{pending}</code>\n"
            "Отправьте новый код, чтобы заменить, или <code>удалить</code>."
        )
    await message.answer(
        "Введите промокод.\n"
        "• Код на баланс — начисление сразу\n"
        "• Код на скидку — применится к следующему заказу"
        f"{extra}\n\n/cancel — отмена",
        reply_markup=main_menu_kb(),
    )


@router.message(PromoMenuFSM.entering, Command("cancel"))
async def promo_menu_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Отменено.", reply_markup=main_menu_kb())


@router.message(PromoMenuFSM.entering)
async def promo_menu_apply(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    raw = (message.text or "").strip()
    if raw.lower() in {"удалить", "удали", "сброс", "clear"}:
        db_user.pending_promo_code = None
        await session.flush()
        await state.clear()
        await message.answer("Сохранённый промокод удалён.", reply_markup=main_menu_kb())
        return

    code = normalize_code(raw)
    promo = await get_promo_by_code(session, code)
    if not promo:
        await message.answer("Промокод не найден. Попробуйте ещё раз или /cancel")
        return

    if is_balance_promo(promo):
        try:
            promo, amount = await redeem_balance_promo(session, db_user, code)
        except PromoError as exc:
            await message.answer(f"{exc.message}\nПопробуйте другой код или /cancel")
            return
        await state.clear()
        await message.answer(
            f"Промокод <code>{promo.code}</code> активирован!\n"
            f"На баланс зачислено: <b>+${amount:.2f}</b>\n"
            f"Текущий баланс: <b>${Decimal(db_user.balance):.2f}</b>",
            reply_markup=main_menu_kb(),
        )
        return

    # Order discount promo — save for next order
    try:
        await validate_promo_for_user(
            session,
            promo,
            db_user,
            amount=Decimal("999999.00"),
        )
    except PromoError as exc:
        if "Минимальная сумма" not in exc.message:
            await message.answer(f"{exc.message}\nПопробуйте другой код или /cancel")
            return

    db_user.pending_promo_code = promo.code
    await session.flush()
    await state.clear()

    disc = (
        f"{promo.discount_value}%"
        if promo.discount_type == DiscountType.PERCENT
        else f"${promo.discount_value}"
    )
    await message.answer(
        f"Промокод <code>{promo.code}</code> сохранён ({disc} скидка).\n"
        "Применится при следующем заказе.",
        reply_markup=main_menu_kb(),
    )
