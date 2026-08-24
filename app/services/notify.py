from decimal import Decimal

from aiogram import Bot
from loguru import logger

from app.core.config import get_settings
from app.db.models import Order, User
from app.panel import PanelClient


async def notify_admins(bot: Bot, text: str) -> None:
    for admin_id in get_settings().admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception as exc:
            logger.warning("Admin notify failed for {}: {}", admin_id, exc)


async def notify_admins_new_order(bot: Bot, order: Order, user: User) -> None:
    svc = order.service.name if order.service else f"#{order.service_id}"
    text = (
        "💵 <b>Новая оплата</b>\n"
        f"Заказ <b>#{order.id}</b>\n"
        f"User: <code>{user.tg_id}</code> @{user.username or '—'}\n"
        f"Услуга: {svc}\n"
        f"Кол-во: {order.quantity}\n"
        f"Сумма: <b>${order.sale_price:.2f}</b>\n"
        f"Закуп: ${order.purchase_price or 0}\n"
        f"Прибыль: ${order.profit or 0}"
    )
    await notify_admins(bot, text)


async def check_and_alert_panel_balance(bot: Bot) -> Decimal | None:
    settings = get_settings()
    threshold = Decimal(str(settings.panel_balance_alert_usd))
    try:
        async with PanelClient() as client:
            balance = await client.get_balance()
    except Exception as exc:
        logger.warning("Panel balance check failed: {}", exc)
        return None

    if balance < threshold:
        await notify_admins(
            bot,
            f"⚠️ Низкий баланс поставщика: <b>${balance}</b>\n"
            f"Порог: ${threshold}",
        )
    return balance
