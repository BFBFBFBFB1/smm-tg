from decimal import Decimal

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, LabeledPrice, Message, PreCheckoutQuery
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.bot.filters.link_validator import validate_link
from app.bot.keyboards import confirm_order_kb, main_menu_kb, payment_methods_kb, quantity_kb
from app.bot.states import OrderFSM
from app.core.config import get_settings
from app.core.pricing import calculate_order_price
from app.db.models import OrderStatus, PaymentMethod, User
from app.panel import PanelAPIError
from app.payments import CryptoBotProvider, YooKassaProvider, stars_amount_from_usd
from app.services.catalog import format_rate, get_service
from app.services.orders import create_draft_order, pay_order_from_balance
from app.services.payments import create_payment

router = Router(name="order")


@router.message(OrderFSM.entering_link)
async def process_link(message: Message, session: AsyncSession, state: FSMContext) -> None:
    data = await state.get_data()
    service = await get_service(session, data["service_id"])
    if not service:
        await state.clear()
        await message.answer("Услуга недоступна. Начните заново.", reply_markup=main_menu_kb())
        return

    raw = (message.text or "").strip()
    if raw.lower() in {"та же", "таже", "same", "та же ссылка"} and data.get("reorder_link"):
        link = data["reorder_link"]
    else:
        category_name = service.category.name if service.category else None
        ok, link = validate_link(raw, category_name)
        if not ok:
            await message.answer(link)
            return

    await state.update_data(link=link)
    await state.set_state(OrderFSM.entering_quantity)

    # If reorder — offer previous qty as default packages still shown
    await message.answer(
        f"Ссылка принята.\n\n"
        f"Выберите количество\n"
        f"(от <b>{service.min_order}</b> до <b>{service.max_order}</b>) "
        "или введите своё:",
        reply_markup=quantity_kb(service.min_order, service.max_order),
    )


async def _apply_quantity(
    *,
    message_or_callback: Message | CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    quantity: int,
) -> None:
    data = await state.get_data()
    service = await get_service(session, data["service_id"])
    if not service:
        await state.clear()
        target = (
            message_or_callback.message
            if isinstance(message_or_callback, CallbackQuery)
            else message_or_callback
        )
        await target.answer("Услуга недоступна.", reply_markup=main_menu_kb())
        return

    if quantity < service.min_order or quantity > service.max_order:
        text = f"Количество должно быть от {service.min_order} до {service.max_order}."
        if isinstance(message_or_callback, CallbackQuery):
            await message_or_callback.answer(text, show_alert=True)
        else:
            await message_or_callback.answer(text)
        return

    total = calculate_order_price(Decimal(service.resale_rate), quantity)
    await state.update_data(quantity=quantity, sale_price=str(total))
    await state.set_state(OrderFSM.confirming)
    text = (
        "<b>Подтверждение заказа</b>\n\n"
        f"Услуга: {service.name}\n"
        f"Ссылка: {data['link']}\n"
        f"Количество: <b>{quantity}</b>\n"
        f"Цена за 1000: {format_rate(service.resale_rate)}\n"
        f"Итого: <b>${total:.2f}</b>"
    )
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(text, reply_markup=confirm_order_kb())
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(text, reply_markup=confirm_order_kb())


@router.callback_query(OrderFSM.entering_quantity, F.data.startswith("qty:"))
async def quantity_button(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    raw = callback.data.split(":", 1)[1]
    if raw == "custom":
        await callback.message.edit_text("Введите количество числом:")
        await callback.answer()
        return
    await _apply_quantity(
        message_or_callback=callback,
        session=session,
        state=state,
        quantity=int(raw),
    )


@router.message(OrderFSM.entering_quantity)
async def process_quantity(message: Message, session: AsyncSession, state: FSMContext) -> None:
    raw = (message.text or "").replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await message.answer("Введите целое число или выберите пакет кнопкой.")
        return
    await _apply_quantity(
        message_or_callback=message,
        session=session,
        state=state,
        quantity=int(raw),
    )


@router.callback_query(OrderFSM.confirming, F.data == "order:cancel")
@router.callback_query(F.data == "order:cancel")
async def cancel_order(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Заказ отменён.")
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(OrderFSM.confirming, F.data == "order:confirm")
async def confirm_order(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    service = await get_service(session, data["service_id"])
    if not service:
        await callback.answer("Услуга недоступна.", show_alert=True)
        return

    order = await create_draft_order(
        session,
        user=db_user,
        service=service,
        link=data["link"],
        quantity=int(data["quantity"]),
    )
    await state.update_data(order_id=order.id)
    await state.set_state(OrderFSM.choosing_payment)

    settings = get_settings()
    yk = YooKassaProvider()
    crypto = CryptoBotProvider()
    balance_ok = Decimal(db_user.balance) >= Decimal(order.sale_price)

    await callback.message.edit_text(
        f"Заказ <b>#{order.id}</b> на <b>${order.sale_price:.2f}</b>\n"
        f"Ваш баланс: <b>${db_user.balance:.2f}</b>\n\n"
        "Выберите способ оплаты:",
        reply_markup=payment_methods_kb(
            balance_ok=balance_ok,
            yookassa=yk.enabled,
            stars=settings.stars_enabled,
            crypto=crypto.enabled,
        ),
    )
    await callback.answer()


@router.callback_query(OrderFSM.choosing_payment, F.data == "pay:balance")
async def pay_balance(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    order_id = data.get("order_id")
    if not order_id:
        await callback.answer("Заказ не найден.", show_alert=True)
        return

    from sqlalchemy import select
    from app.db.models import Order

    result = await session.execute(select(Order).where(Order.id == order_id))
    order = result.scalar_one_or_none()
    if not order or order.status != OrderStatus.AWAITING_PAYMENT:
        await callback.answer("Заказ недоступен для оплаты.", show_alert=True)
        return

    try:
        order = await pay_order_from_balance(session, order, db_user)
    except ValueError:
        await callback.answer("Недостаточно средств на балансе.", show_alert=True)
        return
    except PanelAPIError:
        await callback.message.edit_text(
            "Временно недоступно, попробуйте позже.\n"
            "Средства возвращены на баланс."
        )
        await state.clear()
        await callback.answer()
        return

    from app.db.models import ReferralEarning
    from app.services.referrals import notify_referrer
    from sqlalchemy import select as sa_select

    earning = (
        await session.execute(
            sa_select(ReferralEarning)
            .where(ReferralEarning.order_id == order.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if earning:
        await notify_referrer(callback.bot, session, earning)

    from app.services.notify import check_and_alert_panel_balance, notify_admins_new_order

    # reload order with service for admin text
    from sqlalchemy.orm import selectinload

    order = (
        await session.execute(
            sa_select(Order).options(selectinload(Order.service)).where(Order.id == order.id)
        )
    ).scalar_one()
    await notify_admins_new_order(callback.bot, order, db_user)
    await check_and_alert_panel_balance(callback.bot)

    await state.clear()
    await callback.message.edit_text(
        f"✅ Оплачено с баланса.\n"
        f"Заказ <b>#{order.id}</b> принят в работу.\n"
        f"Статус: {order.status}"
    )
    await callback.message.answer("Главное меню:", reply_markup=main_menu_kb())
    await callback.answer()


@router.callback_query(OrderFSM.choosing_payment, F.data == "pay:yookassa")
async def pay_yookassa(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    amount = Decimal(data["sale_price"])

    provider = YooKassaProvider()
    payment = await create_payment(
        session,
        user=db_user,
        amount=amount,
        method=PaymentMethod.YOOKASSA,
        order_id=order_id,
    )
    try:
        result = provider.create_payment(
            amount=amount,
            description=f"Order #{order_id}",
            metadata={"payment_id": payment.id, "order_id": order_id, "user_id": db_user.id},
        )
    except Exception as exc:
        logger.exception("YooKassa error: {}", exc)
        await callback.answer("Ошибка ЮKassa. Попробуйте другой способ.", show_alert=True)
        return

    payment.external_id = result["id"]
    await session.flush()
    await callback.message.edit_text(
        f"Оплата ЮKassa для заказа <b>#{order_id}</b>\n"
        f"Сумма: <b>${amount:.2f}</b>\n\n"
        f"<a href=\"{result['confirmation_url']}\">Перейти к оплате</a>\n\n"
        "После оплаты заказ запустится автоматически."
    )
    await state.clear()
    await callback.answer()


@router.callback_query(OrderFSM.choosing_payment, F.data == "pay:crypto")
async def pay_crypto(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    amount = Decimal(data["sale_price"])

    provider = CryptoBotProvider()
    payment = await create_payment(
        session,
        user=db_user,
        amount=amount,
        method=PaymentMethod.CRYPTO,
        order_id=order_id,
    )
    payload = f"payment:{payment.id}"
    try:
        invoice = await provider.create_invoice(
            amount=amount,
            payload=payload,
            description=f"Order #{order_id}",
        )
    except Exception as exc:
        logger.exception("Crypto Bot error: {}", exc)
        await callback.answer("Ошибка Crypto Bot. Попробуйте позже.", show_alert=True)
        return

    payment.external_id = str(invoice.get("invoice_id") or payment.external_id)
    payment.payload = payload
    invoice_url = provider.invoice_url(invoice)
    await session.flush()
    await callback.message.edit_text(
        f"Оплата через <b>Crypto Bot</b>\n"
        f"Заказ <b>#{order_id}</b> · <b>${amount:.2f}</b>\n\n"
        f"<a href=\"{invoice_url}\">Открыть счёт в @CryptoBot</a>\n\n"
        "После оплаты заказ запустится автоматически."
    )
    await state.clear()
    await callback.answer()


@router.callback_query(OrderFSM.choosing_payment, F.data == "pay:stars")
async def pay_stars(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    data = await state.get_data()
    order_id = data["order_id"]
    amount = Decimal(data["sale_price"])
    stars = stars_amount_from_usd(amount)

    payment = await create_payment(
        session,
        user=db_user,
        amount=amount,
        method=PaymentMethod.STARS,
        order_id=order_id,
        payload=f"order:{order_id}:{payment_placeholder()}",
    )
    # Fix payload with real payment id
    payment.payload = f"order:{order_id}:{payment.id}"
    await session.flush()

    await callback.message.answer_invoice(
        title=f"Заказ #{order_id}",
        description=f"Оплата SMM-заказа на ${amount:.2f}",
        payload=payment.payload,
        currency="XTR",
        prices=[LabeledPrice(label="Order", amount=stars)],
        provider_token="",  # empty for Stars
    )
    await callback.answer()
    await state.clear()


def payment_placeholder() -> str:
    return "0"


@router.pre_checkout_query()
async def pre_checkout(query: PreCheckoutQuery) -> None:
    await query.answer(ok=True)


@router.message(F.successful_payment)
async def successful_stars_payment(
    message: Message,
    session: AsyncSession,
    db_user: User,
) -> None:
    sp = message.successful_payment
    if not sp or not sp.invoice_payload:
        return

    parts = sp.invoice_payload.split(":")
    # order:{order_id}:{payment_id}  OR  topup:{payment_id}
    from app.services.payments import get_payment_by_external_id, mark_payment_paid
    from sqlalchemy import select
    from app.db.models import Payment

    payment = None
    if parts[0] == "order" and len(parts) >= 3:
        payment_id = int(parts[2])
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()
    elif parts[0] == "topup" and len(parts) >= 2:
        payment_id = int(parts[1])
        result = await session.execute(select(Payment).where(Payment.id == payment_id))
        payment = result.scalar_one_or_none()

    if not payment:
        # fallback by payload field
        result = await session.execute(
            select(Payment).where(Payment.payload == sp.invoice_payload)
        )
        payment = result.scalar_one_or_none()

    if not payment:
        await message.answer("Платёж получен, но запись не найдена. Напишите в поддержку.")
        return

    payment.external_id = sp.telegram_payment_charge_id
    try:
        await mark_payment_paid(session, payment)
        if payment.order_id:
            from sqlalchemy.orm import selectinload
            from app.db.models import Order
            from app.services.notify import (
                check_and_alert_panel_balance,
                notify_admins_new_order,
            )

            order = (
                await session.execute(
                    select(Order)
                    .options(selectinload(Order.service))
                    .where(Order.id == payment.order_id)
                )
            ).scalar_one_or_none()
            if order and order.panel_order_id:
                await notify_admins_new_order(message.bot, order, db_user)
                await check_and_alert_panel_balance(message.bot)
        await message.answer(
            "✅ Оплата Stars прошла успешно!\nЗаказ принят в работу.",
            reply_markup=main_menu_kb(),
        )
    except PanelAPIError:
        await message.answer(
            "Оплата прошла, но сейчас не удалось запустить заказ. "
            "Средства зачислены на баланс — повторите заказ позже.",
            reply_markup=main_menu_kb(),
        )
