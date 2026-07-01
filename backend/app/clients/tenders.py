from datetime import datetime
from typing import Any

from app.clients.base import TSAClient


class TendersClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_new_tenders(self, since: datetime) -> list[dict[str, Any]]:
        data = await self._client.request(
            "GET", "/tenders/new",
            params={"since": since.isoformat(), "limit": 100},
        )
        return data.get("tenders", [])

    async def get_tender_detail(self, tender_id: str) -> dict[str, Any]:
        data = await self._client.request("GET", f"/tenders/{tender_id}")
        return data.get("tender", {})

    async def get_bidders(self, tender_id: str) -> list[dict[str, Any]]:
        data = await self._client.request("GET", f"/tenders/{tender_id}/bidders")
        return data.get("bidders", [])
