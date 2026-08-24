"""Crypto Bot (Crypto Pay API) — https://help.crypt.bot/crypto-pay-api"""

from __future__ import annotations

import hashlib
import hmac
from decimal import Decimal
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings


class CryptoBotProvider:
    MAINNET_URL = "https://pay.crypt.bot/api"
    TESTNET_URL = "https://testnet-pay.crypt.bot/api"

    def __init__(self) -> None:
        settings = get_settings()
        self.token = settings.cryptobot_token
        self.testnet = settings.cryptobot_testnet
        self.asset = settings.cryptobot_asset or "USDT"
        self.fiat = settings.currency or "USD"
        self.paid_btn_url = settings.yookassa_return_url
        self.enabled = bool(self.token)
        self.base_url = self.TESTNET_URL if self.testnet else self.MAINNET_URL

    def _headers(self) -> dict[str, str]:
        return {
            "Crypto-Pay-API-Token": self.token or "",
            "Content-Type": "application/json",
        }

    async def _request(self, method: str, **params: Any) -> dict[str, Any]:
        if not self.enabled:
            raise RuntimeError("Crypto Bot is not configured")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.base_url}/{method}",
                headers=self._headers(),
                json={k: v for k, v in params.items() if v is not None},
            )
            response.raise_for_status()
            data = response.json()

        if not data.get("ok"):
            error = data.get("error") or data
            raise RuntimeError(f"Crypto Bot API error: {error}")
        return data["result"]

    async def create_invoice(
        self,
        amount: Decimal,
        payload: str,
        description: str,
    ) -> dict[str, Any]:
        """
        Create fiat-priced invoice (USD by default).
        User pays in crypto (USDT/TON/BTC/...) via @CryptoBot.
        """
        result = await self._request(
            "createInvoice",
            currency_type="fiat",
            fiat=self.fiat.upper(),
            amount=f"{amount:.2f}",
            accepted_assets=self.asset,
            description=description[:1024],
            payload=payload[:4096],
            allow_comments=False,
            allow_anonymous=False,
            expires_in=3600,
            paid_btn_name="callback" if self.paid_btn_url else None,
            paid_btn_url=self.paid_btn_url,
        )
        logger.info("CryptoBot invoice created: {}", result.get("invoice_id"))
        return result

    async def get_invoices(
        self,
        *,
        invoice_ids: list[int] | None = None,
        status: str | None = None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"count": count}
        if invoice_ids:
            params["invoice_ids"] = ",".join(str(i) for i in invoice_ids)
        if status:
            params["status"] = status
        result = await self._request("getInvoices", **params)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "items" in result:
            return list(result["items"])
        return []

    async def get_invoice(self, invoice_id: int) -> dict[str, Any]:
        items = await self.get_invoices(invoice_ids=[invoice_id])
        if not items:
            raise RuntimeError(f"Invoice {invoice_id} not found")
        return items[0]

    @staticmethod
    def invoice_url(invoice: dict[str, Any]) -> str | None:
        return (
            invoice.get("bot_invoice_url")
            or invoice.get("mini_app_invoice_url")
            or invoice.get("pay_url")
        )

    def verify_webhook_signature(self, body: bytes, signature: str | None) -> bool:
        """
        crypto-pay-api-signature = HMAC-SHA256(body, secret)
        secret = SHA256(app_token)
        """
        if not self.token or not signature:
            return False
        secret = hashlib.sha256(self.token.encode()).digest()
        expected = hmac.new(secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
