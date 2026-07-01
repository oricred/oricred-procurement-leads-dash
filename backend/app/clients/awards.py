from datetime import datetime
from typing import Any

from app.clients.base import TSAClient


class AwardsClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_awards_by_tender(self, tender_id: str) -> list[dict[str, Any]]:
        data = await self._client.request("GET", f"/awards/by-tender/{tender_id}")
        return data.get("awards", [])

    async def get_awards_analytics_category(self) -> list[dict[str, Any]]:
        data = await self._client.request("GET", "/awards/analytics/category")
        return data.get("analytics", [])

    async def get_awards_since(self, since: datetime) -> list[dict[str, Any]]:
        data = await self._client.request(
            "GET", "/awards",
            params={"since": since.isoformat(), "limit": 100},
        )
        return data.get("awards", [])
