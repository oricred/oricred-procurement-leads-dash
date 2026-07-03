import structlog

from app.services.contact_enrichment import enrich_all_contacts
from app.services.lead_service import retry_new_lead_contact_lookups

logger = structlog.get_logger()


async def run_contact_enrichment():
    logger.info("job_started", job="contact_enrichment")
    result = await enrich_all_contacts()
    retried = await retry_new_lead_contact_lookups()
    logger.info("job_completed", job="contact_enrichment", added=result.get("added"), lead_retries=retried)

