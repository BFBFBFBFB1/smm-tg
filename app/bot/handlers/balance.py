from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.keyboards import main_menu_kb, topup_amounts_kb, topup_methods_kb
from app.bot.states import TopUpFSM
from app.core.config import get_settings
from app.db.models import PaymentMethod, User
from app.payments import CryptoBotProvider, YooKassaProvider, stars_amount_from_usd
from app.services.payments import create_payment

router = Router(name="balance")


@router.message(F.text == "💰 Баланс")
async def show_balance(message: Message, db_user: User, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        f"💰 Ваш баланс: <b>${db_user.balance:.2f}</b>\n\nВыберите сумму пополнения:",
        reply_markup=topup_amounts_kb(),
    )


@router.callback_query(F.data.startswith("topup_amount:"))
async def choose_topup_amount(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    raw = callback.data.split(":")[1]
    settings = get_settings()
    yk = YooKassaProvider()
    crypto = CryptoBotProvider()

    if raw == "custom":
        await state.set_state(TopUpFSM.entering_amount)
        await callback.message.edit_text("Введите сумму пополнения в USD (например 15.50):")
        await callback.answer()
        return

    amount = Decimal(raw)
    await state.update_data(topup_amount=str(amount))
    await state.set_state(TopUpFSM.choosing_method)
    await callback.message.edit_text(
        f"Пополнение на <b>${amount:.2f}</b>\nВыберите способ:",
        reply_markup=topup_methods_kb(
            yookassa=yk.enabled,
            stars=settings.stars_enabled,
            crypto=crypto.enabled,
        ),
    )
    await callback.answer()


@router.message(TopUpFSM.entering_amount)
async def custom_topup_amount(message: Message, state: FSMContext) -> None:
    raw = (message.text or "").replace(",", ".").strip()
    try:
        amount = Decimal(raw)
    except Exception:
        await message.answer("Введите число, например 10 или 25.5")
        return
    if amount < Decimal("1") or amount > Decimal("10000"):
        await message.answer("Сумма должна быть от $1 до $10000.")
        return

    settings = get_settings()
    yk = YooKassaProvider()
    crypto = CryptoBotProvider()
    await state.update_data(topup_amount=str(amount))
    await state.set_state(TopUpFSM.choosing_method)
    await message.answer(
        f"Пополнение на <b>${amount:.2f}</b>\nВыберите способ:",
        reply_markup=topup_methods_kb(
            yookassa=yk.enabled,
            stars=settings.stars_enabled,
            crypto=crypto.enabled,
        ),
    )


@router.callback_query(TopUpFSM.choosing_method, F.data == "topup:yookassa")
async def topup_yookassa(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    amount = Decimal(data["topup_amount"])
    provider = YooKassaProvider()
    payment = await create_payment(
        session, user=db_user, amount=amount, method=PaymentMethod.YOOKASSA
    )
    try:
        result = provider.create_payment(
            amount=amount,
            description=f"Balance top-up #{payment.id}",
            metadata={"payment_id": payment.id, "user_id": db_user.id, "type": "topup"},
        )
    except Exception as exc:
        logger.exception("YooKassa topup error: {}", exc)
        await callback.answer("Ошибка ЮKassa", show_alert=True)
        return

    payment.external_id = result["id"]
    await session.flush()
    await state.clear()
    await callback.message.edit_text(
        f"Пополнение ${amount:.2f}\n"
        f"<a href=\"{result['confirmation_url']}\">Оплатить через ЮKassa</a>"
    )
    await callback.answer()


@router.callback_query(TopUpFSM.choosing_method, F.data == "topup:crypto")
async def topup_crypto(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    amount = Decimal(data["topup_amount"])
    provider = CryptoBotProvider()
    payment = await create_payment(
        session, user=db_user, amount=amount, method=PaymentMethod.CRYPTO
    )
    payload = f"payment:{payment.id}"
    try:
        invoice = await provider.create_invoice(
            amount=amount,
            payload=payload,
            description=f"Top-up #{payment.id}",
        )
    except Exception as exc:
        logger.exception("Crypto Bot topup error: {}", exc)
        await callback.answer("Ошибка Crypto Bot", show_alert=True)
        return

    payment.external_id = str(invoice.get("invoice_id") or payment.external_id)
    payment.payload = payload
    url = provider.invoice_url(invoice)
    await session.flush()
    await state.clear()
    await callback.message.edit_text(
        f"Пополнение <b>${amount:.2f}</b> через Crypto Bot\n\n"
        f"<a href=\"{url}\">Открыть счёт в @CryptoBot</a>"
    )
    await callback.answer()


@router.callback_query(TopUpFSM.choosing_method, F.data == "topup:stars")
async def topup_stars(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    amount = Decimal(data["topup_amount"])
    stars = stars_amount_from_usd(amount)
    payment = await create_payment(
        session, user=db_user, amount=amount, method=PaymentMethod.STARS
    )
    payment.payload = f"topup:{payment.id}"
    await session.flush()
    await state.clear()

    await callback.message.answer_invoice(
        title="Пополнение баланса",
        description=f"Пополнение на ${amount:.2f}",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label="Top-up", amount=stars)],
        provider_token="",
    )
    await callback.answer()
    await callback.message.answer("После оплаты Stars баланс обновится автоматически.", reply_markup=main_menu_kb())
