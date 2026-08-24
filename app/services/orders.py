from datetime import datetime, timezone
from decimal import Decimal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.pricing import calculate_order_price, calculate_purchase_price
from app.db.models import Order, OrderStatus, Service, User
from app.panel import PanelAPIError, PanelClient
from app.services.users import debit_balance

ACTIVE_PANEL_STATUSES = {
    OrderStatus.PENDING,
    OrderStatus.IN_PROGRESS,
    OrderStatus.PARTIAL,
}

PANEL_STATUS_MAP = {
    "pending": OrderStatus.PENDING,
    "in progress": OrderStatus.IN_PROGRESS,
    "processing": OrderStatus.IN_PROGRESS,
    "completed": OrderStatus.COMPLETED,
    "partial": OrderStatus.PARTIAL,
    "canceled": OrderStatus.CANCELED,
    "cancelled": OrderStatus.CANCELED,
    "refunded": OrderStatus.REFUNDED,
}


def map_panel_status(raw: str | None) -> str:
    if not raw:
        return OrderStatus.PENDING
    return PANEL_STATUS_MAP.get(raw.strip().lower(), OrderStatus.PENDING)


async def create_draft_order(
    session: AsyncSession,
    user: User,
    service: Service,
    link: str,
    quantity: int,
) -> Order:
    sale_price = calculate_order_price(Decimal(service.resale_rate), quantity)
    order = Order(
        user_id=user.id,
        service_id=service.id,
        link=link,
        quantity=quantity,
        sale_price=sale_price,
        status=OrderStatus.AWAITING_PAYMENT,
    )
    session.add(order)
    await session.flush()
    return order


async def place_order_on_panel(session: AsyncSession, order_id: int) -> Order:
    """After payment: check panel balance, create panel order, save panel_order_id."""
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.service), selectinload(Order.user))
        .where(Order.id == order_id)
    )
    order = result.scalar_one()
    service = order.service

    async with PanelClient() as client:
        balance = await client.get_balance()
        purchase_price = calculate_purchase_price(Decimal(service.panel_rate), order.quantity)

        if balance < purchase_price:
            logger.error(
                "Insufficient panel balance: have={}, need={}, order={}",
                balance,
                purchase_price,
                order.id,
            )
            order.status = OrderStatus.FAILED
            await session.flush()
            raise PanelAPIError("Insufficient panel balance")

        try:
            panel_order_id = await client.add_order(
                service_id=service.panel_service_id,
                link=order.link,
                quantity=order.quantity,
            )
        except PanelAPIError:
            order.status = OrderStatus.FAILED
            await session.flush()
            raise

    order.panel_order_id = panel_order_id
    order.purchase_price = purchase_price
    order.profit = Decimal(order.sale_price) - purchase_price
    order.status = OrderStatus.PENDING
    order.panel_status = "Pending"
    await session.flush()
    logger.info(
        "Order {} placed on panel as {}, profit={}",
        order.id,
        panel_order_id,
        order.profit,
    )
    return order


async def pay_order_from_balance(session: AsyncSession, order: Order, user: User) -> Order:
    from app.services.promos import finalize_promo_redemption
    from app.services.referrals import award_referral_for_order
    from app.services.users import credit_balance

    amount = Decimal(order.sale_price)
    ok = await debit_balance(session, user, amount)
    if not ok:
        raise ValueError("Insufficient user balance")
    try:
        placed = await place_order_on_panel(session, order.id)
        await finalize_promo_redemption(session, placed, user)
        await award_referral_for_order(session, buyer=user, order=placed)
        return placed
    except PanelAPIError:
        await credit_balance(session, user, amount)
        raise


async def get_user_orders(
    session: AsyncSession,
    user_id: int,
    limit: int = 10,
) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.service))
        .where(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_active_orders(session: AsyncSession) -> list[Order]:
    result = await session.execute(
        select(Order)
        .options(selectinload(Order.user), selectinload(Order.service))
        .where(
            Order.panel_order_id.is_not(None),
            Order.status.in_(
                [
                    OrderStatus.PENDING,
                    OrderStatus.IN_PROGRESS,
                    OrderStatus.PARTIAL,
                ]
            ),
        )
    )
    return list(result.scalars().all())


async def update_order_from_panel(
    session: AsyncSession,
    order: Order,
    panel_data: dict,
) -> tuple[Order, bool]:
    """Returns (order, status_changed)."""
    raw_status = str(panel_data.get("status") or "")
    new_status = map_panel_status(raw_status)
    changed = order.status != new_status or order.panel_status != raw_status

    order.panel_status = raw_status
    order.status = new_status

    if panel_data.get("start_count") not in (None, ""):
        try:
            order.start_count = int(panel_data["start_count"])
        except (TypeError, ValueError):
            pass
    if panel_data.get("remains") not in (None, ""):
        try:
            order.remains = int(panel_data["remains"])
        except (TypeError, ValueError):
            pass

    if new_status in {OrderStatus.COMPLETED, OrderStatus.CANCELED, OrderStatus.REFUNDED}:
        if order.completed_at is None:
            order.completed_at = datetime.now(timezone.utc)

    # Partial refunds: credit remains proportionally if refunded/canceled after payment
    await session.flush()
    return order, changed
