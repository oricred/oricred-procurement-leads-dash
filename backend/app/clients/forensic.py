from typing import Any

from app.clients.base import TSAClient


class ForensicClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def check_restricted_supplier(self, company_name: str) -> dict[str, Any]:
        data = await self._client.request(
            "POST", "/forensic/restricted-suppliers/check",
            json={"company_name": company_name},
        )
        return data

    async def match_company(self, name: str) -> dict[str, Any] | None:
        data = await self._client.request(
            "GET", "/match",
            params={"name": name},
        )
        return data.get("match")
