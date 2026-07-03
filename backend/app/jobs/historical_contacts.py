import structlog

from app.services.historical_contacts import sync_historical_contacts

logger = structlog.get_logger()


async def sync_historical_contacts_job():
    logger.info("job_started", job="historical_contacts")
    result = await sync_historical_contacts()
    logger.info("job_completed", job="historical_contacts", **result)
