from decimal import Decimal

from aiogram import F, Router
from aiogram.filters import Command
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
async def process_link(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
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

    bundle_qty = data.get("bundle_qty")
    if bundle_qty:
        await state.update_data(bundle_qty=None)
        await _apply_quantity(
            message_or_callback=message,
            session=session,
            state=state,
            quantity=int(bundle_qty),
            db_user=db_user,
        )
        return

    await state.set_state(OrderFSM.entering_quantity)
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
    db_user: User | None = None,
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
    promo_code = data.get("promo_code")
    promo_discount = data.get("promo_discount")

    if not promo_code and db_user and db_user.pending_promo_code:
        from app.services.promos import (
            PromoError,
            get_promo_by_code,
            validate_promo_for_user,
        )

        promo = await get_promo_by_code(session, db_user.pending_promo_code)
        if promo:
            try:
                promo_discount = str(
                    await validate_promo_for_user(session, promo, db_user, total)
                )
                promo_code = promo.code
            except PromoError:
                promo_code = None
                promo_discount = None

    await state.update_data(
        quantity=quantity,
        sale_price=str(total),
        promo_code=promo_code,
        promo_discount=promo_discount,
    )
    await state.set_state(OrderFSM.confirming)
    settings = get_settings()
    text = _confirm_text(
        service, data["link"], quantity, total, promo_code, promo_discount
    )
    kb = confirm_order_kb(
        offer_url=settings.offer_url,
        privacy_url=settings.privacy_url,
        has_promo=bool(promo_code),
    )
    if isinstance(message_or_callback, CallbackQuery):
        await message_or_callback.message.edit_text(
            text, reply_markup=kb, disable_web_page_preview=True
        )
        await message_or_callback.answer()
    else:
        await message_or_callback.answer(
            text, reply_markup=kb, disable_web_page_preview=True
        )


def _confirm_text(service, link: str, quantity: int, total: Decimal, promo_code, discount) -> str:
    settings = get_settings()
    lines = [
        "<b>Подтверждение заказа</b>\n",
        f"Услуга: {service.name}",
        f"Ссылка: {link}",
        f"Количество: <b>{quantity}</b>",
        f"Цена за 1000: {format_rate(service.resale_rate)}",
    ]
    if promo_code and discount and Decimal(discount) > 0:
        final = (Decimal(total) - Decimal(discount)).quantize(Decimal("0.01"))
        lines.append(
            f"Итого: <s>${Decimal(total):.2f}</s> → <b>${final:.2f}</b> "
            f"(промо <code>{promo_code}</code> −${Decimal(discount):.2f})"
        )
    else:
        lines.append(f"Итого: <b>${Decimal(total):.2f}</b>")
    lines.append("")
    lines.append(
        "Нажимая «Подтвердить», вы соглашаетесь с "
        f"<a href=\"{settings.offer_url}\">офертой</a> и "
        f"<a href=\"{settings.privacy_url}\">политикой конфиденциальности</a>."
    )
    return "\n".join(lines)


@router.callback_query(OrderFSM.entering_quantity, F.data.startswith("qty:"))
async def quantity_button(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
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
        db_user=db_user,
    )


@router.message(OrderFSM.entering_quantity)
async def process_quantity(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    raw = (message.text or "").replace(" ", "").replace(",", "")
    if not raw.isdigit():
        await message.answer("Введите целое число или выберите пакет кнопкой.")
        return
    await _apply_quantity(
        message_or_callback=message,
        session=session,
        state=state,
        quantity=int(raw),
        db_user=db_user,
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
    promo_code = data.get("promo_code") or db_user.pending_promo_code
    if promo_code:
        from app.services.promos import PromoError, apply_promo_to_order, normalize_code

        try:
            order, _ = await apply_promo_to_order(session, order, db_user, promo_code)
            if db_user.pending_promo_code and normalize_code(
                db_user.pending_promo_code
            ) == normalize_code(str(promo_code)):
                db_user.pending_promo_code = None
        except PromoError:
            pass

    await state.update_data(order_id=order.id, promo_code=None, promo_discount=None)
    await state.set_state(OrderFSM.choosing_payment)

    settings = get_settings()
    yk = YooKassaProvider()
    crypto = CryptoBotProvider()
    balance_ok = Decimal(db_user.balance) >= Decimal(order.sale_price)

    await callback.message.edit_text(
        _payment_text(order, db_user),
        reply_markup=payment_methods_kb(
            balance_ok=balance_ok,
            yookassa=yk.enabled,
            stars=settings.stars_enabled,
            crypto=crypto.enabled,
            has_promo=bool(order.promo_code_id),
        ),
        disable_web_page_preview=True,
    )
    await callback.answer()


def _payment_text(order, db_user: User) -> str:
    lines = [
        f"Заказ <b>#{order.id}</b>",
    ]
    if order.original_price and Decimal(order.discount_amount or 0) > 0:
        lines.append(
            f"Сумма: <s>${Decimal(order.original_price):.2f}</s> → "
            f"<b>${Decimal(order.sale_price):.2f}</b> "
            f"(−${Decimal(order.discount_amount):.2f})"
        )
    else:
        lines.append(f"Сумма: <b>${Decimal(order.sale_price):.2f}</b>")
    lines.append(f"Ваш баланс: <b>${db_user.balance:.2f}</b>")
    lines.append("")
    lines.append("Выберите способ оплаты:")
    return "\n".join(lines)


@router.callback_query(F.data == "promo:noop")
async def promo_already(callback: CallbackQuery) -> None:
    await callback.answer("Промокод уже применён", show_alert=True)


@router.callback_query(F.data == "promo:enter")
async def promo_enter(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current not in {OrderFSM.confirming.state, OrderFSM.choosing_payment.state}:
        await callback.answer()
        return
    await state.update_data(promo_return_state=current)
    await state.set_state(OrderFSM.entering_promo)
    await callback.message.edit_text(
        "Введите промокод одним сообщением.\n"
        "Отмена: /cancel"
    )
    await callback.answer()


@router.message(OrderFSM.entering_promo, Command("cancel"))
async def promo_cancel(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    await _return_after_promo(message, session, state, db_user)


@router.message(OrderFSM.entering_promo)
async def promo_apply(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    from sqlalchemy import select
    from app.db.models import Order
    from app.services.promos import (
        PromoError,
        apply_promo_to_order,
        get_promo_by_code,
        validate_promo_for_user,
    )

    data = await state.get_data()
    code = (message.text or "").strip()
    order_id = data.get("order_id")

    if order_id:
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if not order or order.status != OrderStatus.AWAITING_PAYMENT:
            await state.clear()
            await message.answer("Заказ недоступен.", reply_markup=main_menu_kb())
            return
        try:
            order, discount = await apply_promo_to_order(
                session, order, db_user, code
            )
        except PromoError as exc:
            await message.answer(f"{exc.message}\nПопробуйте другой код или /cancel")
            return
        await message.answer(f"Промокод применён: −${discount:.2f}")
        await _show_payment_message(message, order, db_user, state)
        return

    # Before order created — store in FSM
    base = Decimal(data.get("sale_price") or 0)
    promo = await get_promo_by_code(session, code)
    if not promo:
        await message.answer("Промокод не найден.\nПопробуйте другой или /cancel")
        return
    try:
        discount = await validate_promo_for_user(session, promo, db_user, base)
    except PromoError as exc:
        await message.answer(f"{exc.message}\nПопробуйте другой код или /cancel")
        return

    await state.update_data(promo_code=promo.code, promo_discount=str(discount))
    await message.answer(f"Промокод <code>{promo.code}</code> применён: −${discount:.2f}")
    await _show_confirm_message(message, session, state)


async def _show_confirm_message(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
) -> None:
    data = await state.get_data()
    service = await get_service(session, data["service_id"])
    if not service:
        await state.clear()
        await message.answer("Услуга недоступна.", reply_markup=main_menu_kb())
        return
    total = Decimal(data["sale_price"])
    settings = get_settings()
    await state.set_state(OrderFSM.confirming)
    await message.answer(
        _confirm_text(
            service,
            data["link"],
            int(data["quantity"]),
            total,
            data.get("promo_code"),
            data.get("promo_discount"),
        ),
        reply_markup=confirm_order_kb(
            offer_url=settings.offer_url,
            privacy_url=settings.privacy_url,
            has_promo=bool(data.get("promo_code")),
        ),
        disable_web_page_preview=True,
    )


async def _show_payment_message(
    message: Message,
    order,
    db_user: User,
    state: FSMContext,
) -> None:
    settings = get_settings()
    yk = YooKassaProvider()
    crypto = CryptoBotProvider()
    balance_ok = Decimal(db_user.balance) >= Decimal(order.sale_price)
    await state.set_state(OrderFSM.choosing_payment)
    await message.answer(
        _payment_text(order, db_user),
        reply_markup=payment_methods_kb(
            balance_ok=balance_ok,
            yookassa=yk.enabled,
            stars=settings.stars_enabled,
            crypto=crypto.enabled,
            has_promo=bool(order.promo_code_id),
        ),
        disable_web_page_preview=True,
    )


async def _return_after_promo(
    message: Message,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    from sqlalchemy import select
    from app.db.models import Order

    data = await state.get_data()
    order_id = data.get("order_id")
    if order_id:
        order = (
            await session.execute(select(Order).where(Order.id == order_id))
        ).scalar_one_or_none()
        if not order:
            await state.clear()
            await message.answer("Заказ не найден.", reply_markup=main_menu_kb())
            return
        await _show_payment_message(message, order, db_user, state)
        return
    await _show_confirm_message(message, session, state)


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
