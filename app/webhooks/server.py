"""HTTP webhooks for YooKassa and Crypto Bot."""

from aiohttp import web
from loguru import logger
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import setup_logging
from app.db import async_session_factory
from app.db.models import Payment
from app.payments import CryptoBotProvider
from app.services.payments import get_payment_by_external_id, mark_payment_paid


async def yookassa_webhook(request: web.Request) -> web.Response:
    try:
        payload = await request.json()
    except Exception:
        return web.json_response({"ok": False}, status=400)

    event = payload.get("event")
    obj = payload.get("object") or {}
    if event != "payment.succeeded":
        return web.json_response({"ok": True})

    external_id = obj.get("id")
    if not external_id:
        return web.json_response({"ok": False}, status=400)

    async with async_session_factory() as session:
        payment = await get_payment_by_external_id(session, external_id)
        if not payment:
            meta = obj.get("metadata") or {}
            payment_id = meta.get("payment_id")
            if payment_id:
                result = await session.execute(
                    select(Payment).where(Payment.id == int(payment_id))
                )
                payment = result.scalar_one_or_none()
        if not payment:
            logger.warning("YooKassa payment not found: {}", external_id)
            return web.json_response({"ok": True})

        await mark_payment_paid(session, payment)
        await session.commit()
        logger.info("YooKassa payment {} marked paid", payment.id)

    return web.json_response({"ok": True})


async def cryptobot_webhook(request: web.Request) -> web.Response:
    body = await request.read()
    provider = CryptoBotProvider()
    signature = request.headers.get("crypto-pay-api-signature")

    if not provider.verify_webhook_signature(body, signature):
        logger.warning("Crypto Bot webhook: invalid signature")
        return web.json_response({"ok": False}, status=403)

    try:
        import orjson

        update = orjson.loads(body)
    except Exception:
        return web.json_response({"ok": False}, status=400)

    if update.get("update_type") != "invoice_paid":
        return web.json_response({"ok": True})

    invoice = update.get("payload") or {}
    invoice_id = invoice.get("invoice_id")
    invoice_payload = str(invoice.get("payload") or "")

    async with async_session_factory() as session:
        payment = None
        if invoice_id is not None:
            payment = await get_payment_by_external_id(session, str(invoice_id))

        if not payment and invoice_payload.startswith("payment:"):
            try:
                payment_id = int(invoice_payload.split(":", 1)[1])
            except ValueError:
                payment_id = None
            if payment_id:
                result = await session.execute(
                    select(Payment).where(Payment.id == payment_id)
                )
                payment = result.scalar_one_or_none()

        if not payment:
            logger.warning("Crypto Bot payment not found: {}", invoice)
            return web.json_response({"ok": True})

        if invoice_id is not None:
            payment.external_id = str(invoice_id)

        await mark_payment_paid(session, payment)
        await session.commit()
        logger.info("Crypto Bot payment {} marked paid (invoice {})", payment.id, invoice_id)

    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhooks/yookassa", yookassa_webhook)
    app.router.add_post("/webhooks/cryptobot", cryptobot_webhook)
    app.router.add_get("/health", lambda r: web.json_response({"status": "ok"}))
    return app


def main() -> None:
    setup_logging()
    settings = get_settings()
    web.run_app(create_app(), host=settings.webhook_host, port=settings.webhook_port)


if __name__ == "__main__":
    main()
