from datetime import datetime, timezone

import structlog

from app.services.crm.sync import pull_crm_activity

logger = structlog.get_logger()


async def sync_crm() -> None:
    logger.info("crm_sync_started")
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    await pull_crm_activity(since=today)
    logger.info("crm_sync_completed")
