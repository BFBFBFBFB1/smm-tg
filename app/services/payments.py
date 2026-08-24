from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Order, Payment, PaymentMethod, PaymentStatus, User
from app.services.orders import place_order_on_panel
from app.services.users import credit_balance


async def create_payment(
    session: AsyncSession,
    user: User,
    amount: Decimal,
    method: str,
    order_id: int | None = None,
    external_id: str | None = None,
    payload: str | None = None,
) -> Payment:
    payment = Payment(
        user_id=user.id,
        order_id=order_id,
        amount=amount,
        payment_method=method,
        status=PaymentStatus.PENDING,
        external_id=external_id or f"pay_{uuid4().hex}",
        payload=payload,
    )
    session.add(payment)
    await session.flush()
    return payment


async def get_payment_by_external_id(
    session: AsyncSession,
    external_id: str,
) -> Payment | None:
    result = await session.execute(
        select(Payment).where(Payment.external_id == external_id)
    )
    return result.scalar_one_or_none()


async def mark_payment_paid(session: AsyncSession, payment: Payment) -> Payment:
    if payment.status == PaymentStatus.PAID:
        return payment

    payment.status = PaymentStatus.PAID
    payment.paid_at = datetime.now(timezone.utc)

    result = await session.execute(select(User).where(User.id == payment.user_id))
    user = result.scalar_one()

    if payment.order_id:
        # Direct order payment → place on panel
        try:
            order = await place_order_on_panel(session, payment.order_id)
            from app.services.promos import finalize_promo_redemption
            from app.services.referrals import award_referral_for_order

            await finalize_promo_redemption(session, order, user)
            await award_referral_for_order(
                session,
                buyer=user,
                order=order,
                payment_id=payment.id,
            )
        except Exception as exc:
            logger.exception("Failed to place order {} after payment: {}", payment.order_id, exc)
            # Keep funds on user balance so they can retry / support can fix
            await credit_balance(session, user, Decimal(payment.amount))
            order_result = await session.execute(
                select(Order).where(Order.id == payment.order_id)
            )
            order = order_result.scalar_one_or_none()
            if order:
                from app.db.models import OrderStatus

                order.status = OrderStatus.FAILED
    else:
        # Top-up
        await credit_balance(session, user, Decimal(payment.amount))

    await session.flush()
    return payment
