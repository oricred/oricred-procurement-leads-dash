from typing import Any

from app.clients.base import TSAClient


class ReferenceClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_categories(self) -> list[dict[str, Any]]:
        data = await self._client.request("GET", "/categories")
        return data.get("categories", [])

    async def get_provinces(self) -> list[dict[str, Any]]:
        data = await self._client.request("GET", "/provinces")
        return data.get("provinces", [])
