from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.crm import CRMAdapter
from app.services.crm.monday import (
    MONDAY_API_VERSION,
    CRMError,
    MondayDotComAdapter,
    validate_board_id,
)

# Monday board IDs are numeric. The shipped default was the string
# "oricred_opportunities", which produced a GraphQL syntax error on every
# request — see remediation-05 section 1.
BOARD_ID = "1234567890"


class TestCRMAdapterInterface:
    def test_is_abstract(self):
        with pytest.raises(TypeError):
            CRMAdapter()  # type: ignore


class TestValidateBoardId:
    def test_a_numeric_id_passes(self):
        assert validate_board_id("1234567890") == "1234567890"

    def test_surrounding_whitespace_is_trimmed(self):
        assert validate_board_id("  1234567890 ") == "1234567890"

    @pytest.mark.parametrize("value", [
        "oricred_opportunities",  # the shipped default
        "board_1",
        "",
        None,
        "123abc",
    ])
    def test_a_non_numeric_id_is_refused_with_an_actionable_message(self, value):
        with pytest.raises(CRMError, match="must be numeric"):
            validate_board_id(value)


class TestMondayDotComAdapter:
    @pytest.mark.asyncio
    async def test_create_item(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"create_item": {"id": "12345"}}
            item_id = await adapter.create_item(BOARD_ID, "group_1", "Test Co", {"status": "New"})
            assert item_id == "12345"

            # Identifiers travel as variables, never interpolated into the document.
            query, variables = mock_exec.call_args[0]
            assert BOARD_ID not in query
            assert variables["boardId"] == BOARD_ID
            assert variables["itemName"] == "Test Co"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_create_item_refuses_a_bad_board_id(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with pytest.raises(CRMError, match="must be numeric"):
            await adapter.create_item("oricred_opportunities", "main", "Test Co", {})
        await adapter.close()

    @pytest.mark.asyncio
    async def test_update_columns_issues_one_request(self):
        """Replaces a loop of one HTTP round trip per column."""
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {}
            await adapter.update_columns(BOARD_ID, "item_1", {
                "status": "Qualified Lead",
                "numbers": "2500000",
                "text": "SANRAL",
                "people": "u1",
            })
            assert mock_exec.await_count == 1
        await adapter.close()

    @pytest.mark.asyncio
    async def test_update_columns_with_nothing_to_set_makes_no_request(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            await adapter.update_columns(BOARD_ID, "item_1", {})
            assert mock_exec.await_count == 0
        await adapter.close()

    @pytest.mark.asyncio
    async def test_update_column_value(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {}
            await adapter.update_column_value("item_1", "status", "Contacted")
            _query, variables = mock_exec.call_args[0]
            assert variables == {"itemId": "item_1", "columnId": "status", "value": "Contacted"}
        await adapter.close()

    @pytest.mark.asyncio
    async def test_get_recent_activity(self):
        mock_response = {
            "boards": [
                {
                    "activity_logs": [
                        {
                            "event": "update_column_value",
                            "data": {"column_id": "status", "item_name": "Test Co"},
                            "created_at": "2026-07-01T08:00:00Z",
                        }
                    ]
                }
            ]
        }
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_response
            since = datetime(2026, 7, 1, tzinfo=timezone.utc)
            activities = await adapter.get_recent_activity(BOARD_ID, since)

        assert len(activities) == 1
        assert activities[0].event == "update_column_value"
        assert activities[0].created_at.tzinfo is not None
        await adapter.close()

    @pytest.mark.asyncio
    async def test_get_recent_activity_with_no_board(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"boards": []}
            since = datetime(2026, 7, 1, tzinfo=timezone.utc)
            assert await adapter.get_recent_activity(BOARD_ID, since) == []
        await adapter.close()

    @pytest.mark.asyncio
    async def test_search_items_is_explicitly_unimplemented(self):
        """It queried boards { items }, removed by Monday in API 2023-10, and
        had no callers. Raising beats silently returning wrong results."""
        adapter = MondayDotComAdapter(api_key="test-key")
        with pytest.raises(NotImplementedError, match="items_page"):
            await adapter.search_items(BOARD_ID, "Acme")
        await adapter.close()

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        adapter = MondayDotComAdapter(api_key="test-key")

        class _Response:
            @staticmethod
            def raise_for_status() -> None:
                return None

            @staticmethod
            def json() -> dict:
                return {"errors": [{"message": "Invalid board"}]}

        with patch.object(adapter._client, "post", new_callable=AsyncMock) as mock_post:
            mock_post.return_value = _Response()
            with pytest.raises(CRMError, match="Monday.com API error"):
                await adapter.get_recent_activity(BOARD_ID, datetime.now(timezone.utc))
        await adapter.close()

    def test_the_api_version_is_pinned(self):
        """An unversioned request resolves to the account's rolling default,
        which can change behaviour without a deploy."""
        adapter = MondayDotComAdapter(api_key="test-key")
        assert adapter._client.headers["API-Version"] == MONDAY_API_VERSION
