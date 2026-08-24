"""In-process background loops for local_mode (no Celery)."""

from __future__ import annotations

import asyncio

from aiogram import Bot
from loguru import logger

from app.core.config import get_settings
from app.db import async_session_factory
from app.panel import PanelClient
from app.panel.sync import sync_services_from_panel
from app.services.orders import get_active_orders, update_order_from_panel

STATUS_MESSAGES = {
    "pending": "🕐 Заказ #{order_id}: ожидает обработки.",
    "in_progress": "🔄 Заказ #{order_id}: выполняется.",
    "completed": "✅ Заказ #{order_id}: выполнен!",
    "partial": "🔶 Заказ #{order_id}: выполнен частично (остаток: {remains}).",
    "canceled": "❌ Заказ #{order_id}: отменён.",
    "refunded": "💸 Заказ #{order_id}: средства возвращены.",
}


async def sync_loop(stop: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(60, settings.services_sync_interval_minutes * 60)
    # Avoid racing with startup sync
    try:
        await asyncio.wait_for(stop.wait(), timeout=120)
        return
    except asyncio.TimeoutError:
        pass
    while not stop.is_set():
        try:
            async with async_session_factory() as session:
                stats = await sync_services_from_panel(session)
                await session.commit()
                logger.info("Background sync: {}", stats)
        except Exception as exc:
            logger.exception("Background sync failed: {}", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def poll_loop(bot: Bot, stop: asyncio.Event) -> None:
    settings = get_settings()
    interval = max(15, settings.order_status_poll_seconds)
    while not stop.is_set():
        try:
            await _poll_once(bot)
        except Exception as exc:
            logger.exception("Background poll failed: {}", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def crypto_payments_loop(bot: Bot, stop: asyncio.Event) -> None:
    """Poll Crypto Bot invoices — works without public webhook URL."""
    interval = 20
    # First pass quickly after start
    while not stop.is_set():
        try:
            processed = await _poll_crypto_payments(bot)
            if processed:
                logger.info("CryptoBot payments processed: {}", processed)
        except Exception as exc:
            logger.exception("CryptoBot payment poll failed: {}", exc)
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


async def _poll_crypto_payments(bot: Bot) -> int:
    from sqlalchemy import select

    from app.db.models import Payment, PaymentMethod, PaymentStatus
    from app.payments.cryptobot import CryptoBotProvider
    from app.services.payments import mark_payment_paid

    provider = CryptoBotProvider()
    if not provider.enabled:
        return 0

    processed = 0
    async with async_session_factory() as session:
        payments = (
            await session.execute(
                select(Payment).where(
                    Payment.payment_method == PaymentMethod.CRYPTO,
                    Payment.status == PaymentStatus.PENDING,
                    Payment.external_id.is_not(None),
                )
            )
        ).scalars().all()
        if not payments:
            await session.commit()
            return 0

        invoice_ids: list[int] = []
        by_invoice: dict[int, Payment] = {}
        for payment in payments:
            try:
                invoice_id = int(str(payment.external_id))
            except (TypeError, ValueError):
                continue
            invoice_ids.append(invoice_id)
            by_invoice[invoice_id] = payment

        if not invoice_ids:
            await session.commit()
            return 0

        invoices = await provider.get_invoices(invoice_ids=invoice_ids)
        for invoice in invoices:
            if invoice.get("status") != "paid":
                continue
            try:
                invoice_id = int(invoice["invoice_id"])
            except (KeyError, TypeError, ValueError):
                continue
            payment = by_invoice.get(invoice_id)
            if not payment or payment.status == PaymentStatus.PAID:
                continue

            await mark_payment_paid(session, payment)
            processed += 1

            # Notify user
            from app.db.models import Order, ReferralEarning, User
            from app.services.referrals import notify_referrer

            user = (
                await session.execute(select(User).where(User.id == payment.user_id))
            ).scalar_one_or_none()
            order = None
            if payment.order_id:
                order = (
                    await session.execute(select(Order).where(Order.id == payment.order_id))
                ).scalar_one_or_none()
                earning = (
                    await session.execute(
                        select(ReferralEarning)
                        .where(ReferralEarning.order_id == payment.order_id)
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if earning:
                    await notify_referrer(bot, session, earning)
            if user:
                if order and order.panel_order_id:
                    text = (
                        f"✅ Оплата получена.\n"
                        f"Заказ <b>#{order.id}</b> принят в работу."
                    )
                    from sqlalchemy.orm import selectinload
                    from app.services.notify import (
                        check_and_alert_panel_balance,
                        notify_admins_new_order,
                    )

                    order = (
                        await session.execute(
                            select(Order)
                            .options(selectinload(Order.service))
                            .where(Order.id == order.id)
                        )
                    ).scalar_one()
                    await notify_admins_new_order(bot, order, user)
                    await check_and_alert_panel_balance(bot)
                elif order and order.status == "failed":
                    text = (
                        f"⚠️ Оплата получена, но сейчас не удалось запустить заказ.\n"
                        f"Средства зачислены на баланс (${payment.amount})."
                    )
                else:
                    text = f"✅ Оплата ${payment.amount} получена."
                try:
                    await bot.send_message(user.tg_id, text)
                except Exception as exc:
                    logger.warning("Crypto pay notify failed: {}", exc)

        await session.commit()
    return processed


async def _poll_once(bot: Bot) -> None:
    async with async_session_factory() as session:
        orders = await get_active_orders(session)
        if not orders:
            await session.commit()
            return

        by_panel_id = {o.panel_order_id: o for o in orders if o.panel_order_id}
        panel_ids = list(by_panel_id.keys())
        updated = 0

        async with PanelClient() as client:
            for i in range(0, len(panel_ids), 100):
                chunk = panel_ids[i : i + 100]
                try:
                    if len(chunk) == 1:
                        data = {str(chunk[0]): await client.get_status(chunk[0])}
                    else:
                        data = await client.get_statuses(chunk)
                except Exception as exc:
                    logger.error("Status poll chunk failed: {}", exc)
                    continue

                for panel_id_str, panel_data in data.items():
                    if not isinstance(panel_data, dict):
                        continue
                    try:
                        panel_id = int(panel_id_str)
                    except ValueError:
                        continue
                    order = by_panel_id.get(panel_id)
                    if not order:
                        continue
                    order, changed = await update_order_from_panel(session, order, panel_data)
                    if changed:
                        updated += 1
                        msg_tpl = STATUS_MESSAGES.get(order.status)
                        if msg_tpl and order.user:
                            text = msg_tpl.format(
                                order_id=order.id,
                                remains=order.remains if order.remains is not None else "—",
                            )
                            try:
                                await bot.send_message(order.user.tg_id, text)
                            except Exception as exc:
                                logger.warning("Notify failed: {}", exc)

        await session.commit()
        if updated:
            logger.info("Polled orders, updated={}", updated)
