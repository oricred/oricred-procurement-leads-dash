import structlog

from app.services.award_timing import AwardTimingService

logger = structlog.get_logger()


async def refresh_timing_model():
    logger.info("job_started", job="refresh_timing_model")
    await AwardTimingService.compute_model()
    logger.info("job_completed", job="refresh_timing_model")
