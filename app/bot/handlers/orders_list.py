from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.bot.keyboards import orders_list_kb
from app.bot.states import OrderFSM
from app.db.models import Order, User
from app.services.catalog import format_rate, get_service, get_service_purchase_count
from app.services.orders import get_user_orders

router = Router(name="orders_list")

STATUS_LABELS = {
    "awaiting_payment": "ожидает оплаты",
    "pending": "в очереди",
    "in_progress": "выполняется",
    "completed": "выполнен",
    "partial": "частично",
    "canceled": "отменён",
    "refunded": "возврат",
    "failed": "ошибка",
}


@router.message(F.text == "📦 Мои заказы")
async def my_orders(message: Message, session: AsyncSession, db_user: User) -> None:
    orders = await get_user_orders(session, db_user.id, limit=15)
    if not orders:
        await message.answer("У вас пока нет заказов.")
        return

    lines = ["<b>Ваши заказы:</b>\n"]
    for order in orders:
        status = STATUS_LABELS.get(order.status, order.status)
        svc_name = order.service.name if order.service else "—"
        lines.append(
            f"<b>#{order.id}</b> — {svc_name}\n"
            f"{order.quantity} шт · ${order.sale_price:.2f} · {status}"
        )

    await message.answer("\n\n".join(lines), reply_markup=orders_list_kb(orders))


@router.callback_query(F.data.startswith("reorder:"))
async def reorder(
    callback: CallbackQuery,
    session: AsyncSession,
    state: FSMContext,
    db_user: User,
) -> None:
    order_id = int(callback.data.split(":")[1])
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.service))
        .where(Order.id == order_id, Order.user_id == db_user.id)
    )
    old = result.scalar_one_or_none()
    if not old or not old.service or not old.service.is_active:
        await callback.answer("Услуга больше недоступна.", show_alert=True)
        return

    service = await get_service(session, old.service_id)
    if not service:
        await callback.answer("Услуга больше недоступна.", show_alert=True)
        return

    await state.set_state(OrderFSM.entering_link)
    await state.update_data(
        service_id=service.id,
        reorder_link=old.link,
        reorder_qty=old.quantity,
    )
    bought = await get_service_purchase_count(session, service.id)
    social = f"Уже купили: <b>{bought}</b> раз\n" if bought else ""
    await callback.message.answer(
        f"Повтор заказа <b>#{old.id}</b>\n\n"
        f"<b>{service.name}</b>\n"
        f"{social}"
        f"Цена: {format_rate(service.resale_rate)} / 1000\n"
        f"Прошлая ссылка: <code>{old.link}</code>\n"
        f"Прошлое кол-во: <b>{old.quantity}</b>\n\n"
        "Отправьте ссылку или напишите <code>та же</code>:"
    )
    await callback.answer()
