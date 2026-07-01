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

    def __init__(self):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {settings.tsa_api_key}"},
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )

    async def request(self, method: str, path: str, **kwargs: Any) -> dict:
        last_exception: Exception | None = None
        last_status = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    logger.warning("rate_limited", retry_after=retry_after, path=path)
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                last_status = e.response.status_code
                if e.response.status_code in (401, 403, 404):
                    logger.error("api_auth_error", status=e.response.status_code, path=path)
                    raise
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning("api_retry", attempt=attempt + 1, delay=delay, path=path)
                    await asyncio.sleep(delay)
                else:
                    await self._record_failure(path, kwargs, str(e), self.MAX_RETRIES + 1)
                    raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    delay = self.RETRY_DELAYS[attempt]
                    logger.warning("api_retry_network", attempt=attempt + 1, delay=delay, path=path)
                    await asyncio.sleep(delay)
                else:
                    await self._record_failure(path, kwargs, str(e), self.MAX_RETRIES + 1)
        if last_exception:
            await self._record_failure(path, kwargs, str(last_exception), self.MAX_RETRIES + 1)
        raise last_exception  # type: ignore

    async def _record_failure(self, path: str, params: dict, error: str, attempts: int):
        try:
            from app.database import async_session
            from app.models.failed_api_call import FailedApiCall
            async with async_session() as dl_db:
                dl_db.add(FailedApiCall(
                    endpoint=path,
                    params=params,
                    error=error[:500],
                    attempts=attempts,
                    failed_at=datetime.now(timezone.utc),
                ))
                await dl_db.commit()
        except Exception as e:
            logger.warning("failed_to_record_api_failure", error=str(e))

    async def close(self):
        await self._client.aclose()
