from typing import Any

from app.clients.base import TSAClient


class CompaniesClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_company(self, name: str) -> dict[str, Any] | None:
        data = await self._client.request("GET", f"/companies/{name}")
        return data.get("company")

    async def get_top_companies(self, organization_id: str, category_id: str, limit: int = 10) -> list[dict[str, Any]]:
        data = await self._client.request(
            "GET", "/companies/top",
            params={"organization_id": organization_id, "category_id": category_id, "limit": limit},
        )
        return data.get("companies", [])
