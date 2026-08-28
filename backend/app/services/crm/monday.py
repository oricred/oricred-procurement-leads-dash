"""Monday.com GraphQL adapter.

Two things were wrong with the previous implementation and both are addressed
here — see docs/specifications/remediation-05-integrations-and-delivery.md §1.

Identifiers were interpolated straight into the document, so the shipped default
board ID ("oricred_opportunities") produced `boards (ids: oricred_opportunities)`
— an unquoted identifier where Monday expects an ID, i.e. a syntax error on
every request until someone happened to replace it. Everything now travels as
GraphQL variables.

Column updates issued one HTTP request per column, up to seven per opportunity,
awaited inside three request handlers.
"""

import json
from datetime import datetime
from typing import Any

import httpx
import structlog

from app.services.crm import Activity, CRMAdapter, CRMItem

logger = structlog.get_logger()

# Pinned so the account's rolling default cannot change behaviour underneath us.
# Review annually; `items` became `items_page` in 2023-10.
MONDAY_API_VERSION = "2024-10"


class CRMError(RuntimeError):
    """The CRM rejected a request, or is misconfigured."""


def validate_board_id(board_id: str) -> str:
    """Monday board IDs are numeric. Fail with something an operator can act on.

    Without this the misconfiguration surfaces as an opaque GraphQL syntax
    error, which is what the shipped default produced.
    """
    candidate = str(board_id or "").strip()
    if not candidate.isdigit():
        raise CRMError(
            f"Monday.com board ID must be numeric, got {board_id!r}. "
            "Copy it from the board URL: monday.com/boards/<board-id>."
        )
    return candidate


CREATE_ITEM = """
mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON!) {
  create_item (
    board_id: $boardId,
    group_id: $groupId,
    item_name: $itemName,
    column_values: $columnValues
  ) { id }
}
"""

CHANGE_SIMPLE_COLUMN = """
mutation ($itemId: ID!, $columnId: String!, $value: String!) {
  change_simple_column_value (item_id: $itemId, column_id: $columnId, value: $value) { id }
}
"""

CHANGE_MULTIPLE_COLUMNS = """
mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
  change_multiple_column_values (
    board_id: $boardId, item_id: $itemId, column_values: $columnValues
  ) { id }
}
"""

RECENT_ACTIVITY = """
query ($boardId: ID!, $since: String!, $limit: Int!) {
  boards (ids: [$boardId]) {
    activity_logs (limit: $limit, from: $since) {
      event
      data
      created_at
    }
  }
}
"""


class MondayDotComAdapter(CRMAdapter):
    BASE_URL = "https://api.monday.com/v2"

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": api_key,
                "Content-Type": "application/json",
                "API-Version": MONDAY_API_VERSION,
            },
            timeout=30.0,
        )

    async def _execute(self, query: str, variables: dict[str, Any] | None = None) -> dict:
        response = await self._client.post(
            "", json={"query": query, "variables": variables or {}}
        )
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error("monday_api_error", errors=data["errors"])
            raise CRMError(f"Monday.com API error: {data['errors']}")
        return data["data"]

    async def create_item(
        self, board_id: str, group_id: str, name: str, column_values: dict
    ) -> str:
        result = await self._execute(CREATE_ITEM, {
            "boardId": validate_board_id(board_id),
            "groupId": group_id,
            "itemName": name,
            "columnValues": json.dumps(column_values),
        })
        item_id = result["create_item"]["id"]
        logger.info("monday_item_created", item_id=item_id, name=name)
        return str(item_id)

    async def update_column_value(self, item_id: str, column_id: str, value: Any) -> None:
        await self._execute(CHANGE_SIMPLE_COLUMN, {
            "itemId": item_id,
            "columnId": column_id,
            "value": str(value),
        })
        logger.info("monday_column_updated", item_id=item_id, column_id=column_id)

    async def update_columns(
        self, board_id: str, item_id: str, column_values: dict
    ) -> None:
        """Set every column in one request.

        Replaces a loop of update_column_value, which issued one HTTP round trip
        per column — up to seven per opportunity.
        """
        if not column_values:
            return
        await self._execute(CHANGE_MULTIPLE_COLUMNS, {
            "boardId": validate_board_id(board_id),
            "itemId": item_id,
            "columnValues": json.dumps(column_values),
        })
        logger.info("monday_columns_updated", item_id=item_id, columns=len(column_values))

    async def get_recent_activity(self, board_id: str, since: datetime) -> list[Activity]:
        result = await self._execute(RECENT_ACTIVITY, {
            "boardId": validate_board_id(board_id),
            "since": since.isoformat(),
            "limit": 50,
        })
        boards = result.get("boards", [])
        if not boards:
            return []
        return [
            Activity(
                event=log["event"],
                data=log.get("data", {}),
                created_at=datetime.fromisoformat(log["created_at"].replace("Z", "+00:00")),
            )
            for log in boards[0].get("activity_logs", [])
        ]

    async def search_items(self, board_id: str, term: str) -> list[CRMItem]:
        raise NotImplementedError(
            "Item search is not implemented. The previous version queried "
            "boards { items }, a field Monday replaced with items_page in API "
            "version 2023-10; it had no callers and was never exercised against "
            "a live workspace. See remediation-07 section 3."
        )

    async def close(self) -> None:
        await self._client.aclose()
