import asyncio
from datetime import datetime, timezone
from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger()


class TSAClient:
    BASE_URL = settings.tsa_base_url
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 4, 16]
    DEFAULT_RETRY_AFTER = 60
    MAX_RETRY_AFTER_SECONDS = 120

    def __init__(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {settings.tsa_api_key}"},
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )

    def _retry_after(self, response: httpx.Response) -> int:
        """Seconds to wait after a 429, bounded.

        int() on the raw header raised ValueError for the HTTP-date form the RFC
        also permits, and an unbounded value would block a request handler —
        the admin dead-letter retry calls request() from an HTTP endpoint.
        """
        raw = response.headers.get("Retry-After", "")
        try:
            delay = int(raw)
        except ValueError:
            delay = self.DEFAULT_RETRY_AFTER
        return min(max(delay, 1), self.MAX_RETRY_AFTER_SECONDS)

    async def request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        """Send a request, retrying transient failures.

        Exactly one exit path records a dead-letter row and raises. The previous
        shape recorded on the final network-error attempt and then again after
        the loop, so every network failure produced two rows — inflating the
        admin dead-letter count and leaving a twin unresolved when one was
        retried. It could also fall out of the loop with last_exception unset
        after four consecutive 429s and raise None.
        """
        last_exception: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
                if response.status_code == 429:
                    delay = self._retry_after(response)
                    logger.warning("rate_limited", retry_after=delay, path=path)
                    last_exception = httpx.HTTPStatusError(
                        "rate limited", request=response.request, response=response
                    )
                    await asyncio.sleep(delay)
                    continue
                response.raise_for_status()
                payload: dict[str, Any] = response.json()
                return payload
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    logger.error("api_auth_error", status=e.response.status_code, path=path)
                    raise
                last_exception = e
                logger.warning("api_retry", attempt=attempt + 1, path=path)
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                logger.warning("api_retry_network", attempt=attempt + 1, path=path)

            if attempt < self.MAX_RETRIES:
                await asyncio.sleep(self.RETRY_DELAYS[attempt])

        assert last_exception is not None
        await self._record_failure(
            method, path, kwargs, str(last_exception), self.MAX_RETRIES + 1
        )
        raise last_exception

    async def _record_failure(
        self, method: str, path: str, params: dict[str, Any], error: str, attempts: int
    ) -> None:
        try:
            from app.database import async_session
            from app.models.failed_api_call import FailedApiCall
            async with async_session() as dl_db:
                dl_db.add(FailedApiCall(
                    endpoint=path,
                    method=method,
                    params=params,
                    error=error[:500],
                    attempts=attempts,
                    failed_at=datetime.now(timezone.utc),
                ))
                await dl_db.commit()
        except Exception as e:
            logger.warning("failed_to_record_api_failure", error=str(e))

    async def close(self) -> None:
        await self._client.aclose()
