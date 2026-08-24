from decimal import Decimal
from uuid import uuid4

from loguru import logger

from app.core.config import get_settings


class YooKassaProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self.shop_id = settings.yookassa_shop_id
        self.secret_key = settings.yookassa_secret_key
        self.return_url = settings.yookassa_return_url
        self.enabled = bool(self.shop_id and self.secret_key)

    def create_payment(
        self,
        amount: Decimal,
        description: str,
        metadata: dict | None = None,
    ) -> dict:
        if not self.enabled:
            raise RuntimeError("YooKassa is not configured")

        from yookassa import Configuration, Payment

        Configuration.account_id = self.shop_id
        Configuration.secret_key = self.secret_key

        idempotence_key = str(uuid4())
        payment = Payment.create(
            {
                "amount": {"value": f"{amount:.2f}", "currency": "RUB"},
                "confirmation": {
                    "type": "redirect",
                    "return_url": self.return_url or "https://t.me/",
                },
                "capture": True,
                "description": description[:128],
                "metadata": metadata or {},
            },
            idempotence_key,
        )
        logger.info("YooKassa payment created: {}", payment.id)
        return {
            "id": payment.id,
            "status": payment.status,
            "confirmation_url": payment.confirmation.confirmation_url,
        }
