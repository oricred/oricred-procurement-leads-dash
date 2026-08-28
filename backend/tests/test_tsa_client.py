"""Retry and dead-letter behaviour of the Tenders-SA REST client.

Regression guard for the L9 defect: request() recorded a dead-letter row on the
final network-error attempt and again after the loop, so every network failure
produced two rows. The admin dead-letter count was double the real figure, and
retrying one row left its twin unresolved.
"""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.clients.base import TSAClient


def _response(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status,
        headers=headers or {},
        json={},
        request=httpx.Request("GET", "https://api.tenders-sa.org/x"),
    )


@pytest.fixture
def client(monkeypatch):
    c = TSAClient()
    # Retries are exercised for their control flow, not their timing.
    monkeypatch.setattr("app.clients.base.asyncio.sleep", AsyncMock())
    yield c


class TestDeadLetterRecording:
    async def test_a_network_failure_records_exactly_one_row(self, client):
        with (
            patch.object(client._client, "request", side_effect=httpx.ConnectError("down")),
            patch.object(client, "_record_failure", new_callable=AsyncMock) as record,
        ):
            with pytest.raises(httpx.ConnectError):
                await client.request("GET", "/tenders")

        assert record.await_count == 1, (
            f"recorded {record.await_count} dead-letter rows for one failure"
        )

    async def test_a_server_error_records_exactly_one_row(self, client):
        with (
            patch.object(client._client, "request", return_value=_response(500)),
            patch.object(client, "_record_failure", new_callable=AsyncMock) as record,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.request("GET", "/tenders")

        assert record.await_count == 1

    @pytest.mark.parametrize("status", [401, 403, 404])
    async def test_auth_errors_raise_without_retrying_or_recording(self, client, status):
        with (
            patch.object(client._client, "request", return_value=_response(status)) as send,
            patch.object(client, "_record_failure", new_callable=AsyncMock) as record,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.request("GET", "/tenders")

        assert send.call_count == 1
        assert record.await_count == 0

    async def test_a_successful_retry_records_nothing(self, client):
        responses = [_response(500), _response(200)]
        with (
            patch.object(client._client, "request", side_effect=responses),
            patch.object(client, "_record_failure", new_callable=AsyncMock) as record,
        ):
            assert await client.request("GET", "/tenders") == {}
        assert record.await_count == 0


class TestRateLimiting:
    async def test_persistent_429s_raise_rather_than_returning_none(self, client):
        """The loop could exit with last_exception unset and `raise None`,
        which is a TypeError, not the error the caller expects."""
        with (
            patch.object(client._client, "request", return_value=_response(429)),
            patch.object(client, "_record_failure", new_callable=AsyncMock) as record,
        ):
            with pytest.raises(httpx.HTTPStatusError):
                await client.request("GET", "/tenders")
        assert record.await_count == 1

    def test_a_numeric_retry_after_is_honoured(self, client):
        assert client._retry_after(_response(429, {"Retry-After": "30"})) == 30

    def test_an_http_date_retry_after_does_not_raise(self, client):
        """The RFC permits a date here; int() on it raised ValueError."""
        response = _response(429, {"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"})
        assert client._retry_after(response) == client.DEFAULT_RETRY_AFTER

    def test_a_missing_header_uses_the_default(self, client):
        assert client._retry_after(_response(429)) == client.DEFAULT_RETRY_AFTER

    def test_an_enormous_retry_after_is_capped(self, client):
        """request() is called from an HTTP endpoint (the admin dead-letter
        retry), so an unbounded sleep would hold a worker."""
        response = _response(429, {"Retry-After": "86400"})
        assert client._retry_after(response) == client.MAX_RETRY_AFTER_SECONDS

    def test_a_negative_retry_after_is_floored(self, client):
        assert client._retry_after(_response(429, {"Retry-After": "-5"})) == 1
