from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.crm import CRMAdapter
from app.services.crm.monday import MondayDotComAdapter


class TestCRMAdapterInterface:

    def test_is_abstract(self):
        with pytest.raises(TypeError):
            CRMAdapter()  # type: ignore


class TestMondayDotComAdapter:

    @pytest.mark.asyncio
    async def test_create_item(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {"create_item": {"id": "12345"}}
            item_id = await adapter.create_item("board_1", "group_1", "Test Co", {"status": "New"})
            assert item_id == "12345"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_update_column_value(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = {}
            await adapter.update_column_value("item_1", "status", "Contacted")
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
        since = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_response
            activities = await adapter.get_recent_activity("board_1", since)
            assert len(activities) == 1
            assert activities[0].event == "update_column_value"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_search_items(self):
        mock_response = {
            "boards": [
                {
                    "items": [
                        {
                            "id": "1",
                            "name": "Acme Construction",
                            "column_values": [{"id": "status", "text": "New"}],
                        }
                    ]
                }
            ]
        }
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.return_value = mock_response
            items = await adapter.search_items("board_1", "Acme")
            assert len(items) == 1
            assert items[0].name == "Acme Construction"
        await adapter.close()

    @pytest.mark.asyncio
    async def test_api_error_raises(self):
        adapter = MondayDotComAdapter(api_key="test-key")
        with patch.object(adapter, "_execute", new_callable=AsyncMock) as mock_exec:
            mock_exec.side_effect = RuntimeError("Monday.com API error")
            with pytest.raises(RuntimeError, match="Monday.com API error"):
                await adapter.get_recent_activity("board_1", datetime.now(timezone.utc))
        await adapter.close()
