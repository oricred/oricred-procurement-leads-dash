import structlog
from datetime import datetime
from typing import Any

import httpx

from app.services.crm import CRMAdapter, CRMItem, Activity

logger = structlog.get_logger()


class MondayDotComAdapter(CRMAdapter):
    BASE_URL = "https://api.monday.com/v2"

    def __init__(self, api_key: str):
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def _execute(self, query: str) -> dict:
        response = await self._client.post("", json={"query": query})
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error("monday_api_error", errors=data["errors"])
            raise RuntimeError(f"Monday.com API error: {data['errors']}")
        return data["data"]

    async def create_item(
        self, board_id: str, group_id: str, name: str, column_values: dict
    ) -> str:
        import json

        query = f"""
        mutation {{
          create_item (
            board_id: {board_id},
            group_id: "{group_id}",
            item_name: {json.dumps(name)},
            column_values: {json.dumps(json.dumps(column_values))}
          ) {{ id }}
        }}
        """
        result = await self._execute(query)
        item_id = result["create_item"]["id"]
        logger.info("monday_item_created", item_id=item_id, name=name)
        return item_id

    async def update_column_value(
        self, item_id: str, column_id: str, value: Any
    ) -> None:
        import json

        query = f"""
        mutation {{
          change_simple_column_value (
            item_id: {item_id},
            column_id: "{column_id}",
            value: {json.dumps(str(value))}
          ) {{ id }}
        }}
        """
        await self._execute(query)
        logger.info("monday_column_updated", item_id=item_id, column_id=column_id)

    async def get_recent_activity(
        self, board_id: str, since: datetime
    ) -> list[Activity]:
        query = f"""
        query {{
          boards (ids: {board_id}) {{
            activity_logs (
              limit: 50,
              from: "{since.isoformat()}"
            ) {{
              event
              data
              created_at
            }}
          }}
        }}
        """
        result = await self._execute(query)
        boards = result.get("boards", [])
        if not boards:
            return []
        logs = boards[0].get("activity_logs", [])
        return [
            Activity(
                event=log["event"],
                data=log.get("data", {}),
                created_at=datetime.fromisoformat(log["created_at"].replace("Z", "+00:00")),
            )
            for log in logs
        ]

    async def search_items(self, board_id: str, term: str) -> list[CRMItem]:
        query = f"""
        query {{
          boards (ids: {board_id}) {{
            items (limit: 50) {{
              id
              name
              column_values {{
                id
                text
              }}
            }}
          }}
        }}
        """
        result = await self._execute(query)
        boards = result.get("boards", [])
        if not boards:
            return []
        items = boards[0].get("items", [])
        return [
            CRMItem(
                id=item["id"],
                name=item["name"],
                column_values={cv["id"]: cv["text"] for cv in item.get("column_values", [])},
            )
            for item in items
            if term.lower() in item["name"].lower()
        ]

    async def close(self) -> None:
        await self._client.aclose()
