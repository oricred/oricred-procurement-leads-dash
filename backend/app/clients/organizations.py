from typing import Any

from app.clients.base import TSAClient


class OrganizationsClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_organization(self, org_id: str) -> dict[str, Any] | None:
        data = await self._client.request("GET", f"/organizations/{org_id}")
        return data.get("organization")
