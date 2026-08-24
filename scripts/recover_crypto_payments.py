import asyncio
from decimal import Decimal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.logging import setup_logging
from app.db import async_session_factory
from app.db.models import Order, Payment, PaymentStatus
from app.payments.cryptobot import CryptoBotProvider
from app.services.payments import mark_payment_paid


async def main() -> None:
    setup_logging()
    provider = CryptoBotProvider()
    async with async_session_factory() as session:
        payments = (
            await session.execute(
                select(Payment)
                .where(
                    Payment.payment_method == "crypto",
                    Payment.status == PaymentStatus.PENDING,
                )
                .order_by(Payment.id.desc())
            )
        ).scalars().all()
        print(f"pending crypto payments: {len(payments)}")
        for p in payments:
            print(
                f" payment#{p.id} external={p.external_id} order={p.order_id} "
                f"amount={p.amount} payload={p.payload}"
            )
            if not p.external_id:
                continue
            try:
                invoice = await provider.get_invoice(int(p.external_id))
            except Exception as exc:
                print(f"  get_invoice failed: {exc}")
                continue
            print(f"  invoice status={invoice.get('status')} amount={invoice.get('amount')}")
            if invoice.get("status") == "paid":
                await mark_payment_paid(session, p)
                print(f"  -> marked paid, processing order {p.order_id}")
        await session.commit()

        orders = (
            await session.execute(
                select(Order).options(selectinload(Order.service)).order_by(Order.id.desc())
            )
        ).scalars().all()
        print("=== ORDERS AFTER ===")
        for o in orders:
            print(
                f"#{o.id} status={o.status} panel={o.panel_order_id} "
                f"sale={o.sale_price} purchase={o.purchase_price}"
            )


if __name__ == "__main__":
    asyncio.run(main())
