from decimal import Decimal
from typing import Any

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings


class PanelAPIError(Exception):
    def __init__(self, message: str, payload: Any = None) -> None:
        super().__init__(message)
        self.payload = payload


class PanelClient:
    """Async client for smmpanelus.com API v2 (Perfect Panel compatible)."""

    def __init__(self, api_url: str | None = None, api_key: str | None = None) -> None:
        settings = get_settings()
        self.api_url = api_url or settings.panel_api_url
        self.api_key = api_key or settings.panel_api_key
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "PanelClient":
        self._client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
    async def _request(self, data: dict[str, Any]) -> Any:
        payload = {"key": self.api_key, **data}
        client = self._client or httpx.AsyncClient(timeout=30.0)
        owns_client = self._client is None
        try:
            response = await client.post(self.api_url, data=payload)
            response.raise_for_status()
            result = response.json()
        except httpx.HTTPError as exc:
            logger.error("Panel HTTP error: {}", exc)
            raise PanelAPIError(f"HTTP error: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

        if isinstance(result, dict) and "error" in result:
            raise PanelAPIError(str(result["error"]), payload=result)
        return result

    async def get_services(self) -> list[dict[str, Any]]:
        result = await self._request({"action": "services"})
        if not isinstance(result, list):
            raise PanelAPIError("Unexpected services response", payload=result)
        return result

    async def get_balance(self) -> Decimal:
        result = await self._request({"action": "balance"})
        if not isinstance(result, dict) or "balance" not in result:
            raise PanelAPIError("Unexpected balance response", payload=result)
        return Decimal(str(result["balance"]))

    async def add_order(
        self,
        service_id: int,
        link: str,
        quantity: int,
        **extra: Any,
    ) -> int:
        data: dict[str, Any] = {
            "action": "add",
            "service": service_id,
            "link": link,
            "quantity": quantity,
        }
        data.update(extra)
        result = await self._request(data)
        if not isinstance(result, dict) or "order" not in result:
            raise PanelAPIError("Unexpected add order response", payload=result)
        return int(result["order"])

    async def get_status(self, order_id: int) -> dict[str, Any]:
        result = await self._request({"action": "status", "order": order_id})
        if not isinstance(result, dict):
            raise PanelAPIError("Unexpected status response", payload=result)
        return result

    async def get_statuses(self, order_ids: list[int]) -> dict[str, Any]:
        joined = ",".join(str(oid) for oid in order_ids)
        result = await self._request({"action": "status", "orders": joined})
        if not isinstance(result, dict):
            raise PanelAPIError("Unexpected multi-status response", payload=result)
        return result
