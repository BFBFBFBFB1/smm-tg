import asyncio

from loguru import logger

from app.core.config import get_settings
from app.core.telegram import make_bot
from app.db import async_session_factory
from app.panel import PanelClient
from app.services.orders import get_active_orders, update_order_from_panel
from app.tasks import celery_app

STATUS_MESSAGES = {
    "pending": "🕐 Заказ #{order_id}: ожидает обработки.",
    "in_progress": "🔄 Заказ #{order_id}: выполняется.",
    "completed": "✅ Заказ #{order_id}: выполнен!",
    "partial": "🔶 Заказ #{order_id}: выполнен частично (остаток: {remains}).",
    "canceled": "❌ Заказ #{order_id}: отменён.",
    "refunded": "💸 Заказ #{order_id}: средства возвращены.",
}


def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _notify(tg_id: int, text: str) -> None:
    bot = make_bot()
    try:
        await bot.send_message(tg_id, text)
    except Exception as exc:
        logger.warning("Notify failed for {}: {}", tg_id, exc)
    finally:
        await bot.session.close()


async def _poll() -> int:
    updated = 0
    async with async_session_factory() as session:
        try:
            orders = await get_active_orders(session)
            if not orders:
                await session.commit()
                return 0

            # Batch by panels that support multi-status
            by_panel_id = {o.panel_order_id: o for o in orders if o.panel_order_id}
            panel_ids = list(by_panel_id.keys())

            async with PanelClient() as client:
                # Prefer multi-status in chunks of 100
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
                                await _notify(order.user.tg_id, text)

            await session.commit()
        except Exception:
            await session.rollback()
            raise
    return updated


@celery_app.task(name="app.tasks.poll_orders.poll_order_statuses_task")
def poll_order_statuses_task() -> dict:
    try:
        updated = _run(_poll())
        logger.info("Polled orders, updated={}", updated)
        return {"updated": updated}
    except Exception as exc:
        logger.exception("Poll orders failed: {}", exc)
        return {"error": str(exc)}
