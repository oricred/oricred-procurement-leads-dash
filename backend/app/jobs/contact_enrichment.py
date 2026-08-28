import structlog

from app.services.contact_enrichment import enrich_all_contacts
from app.services.lead_service import retry_new_lead_contact_lookups

logger = structlog.get_logger()

# Above this share of failures, the run is treated as broken rather than merely
# unproductive. A pass that reports success with zero contacts is exactly how
# the enrichment outage went unnoticed for months — see remediation-01 §2.3.
ERROR_RATE_THRESHOLD = 0.5


async def run_contact_enrichment() -> int:
    logger.info("job_started", job="contact_enrichment")
    result = await enrich_all_contacts()
    retried = await retry_new_lead_contact_lookups()

    if result.companies_attempted and result.error_rate >= ERROR_RATE_THRESHOLD:
        # Raised so run_job records status=failed with this message on the
        # job_runs row, which the Admin -> Jobs table already renders.
        raise RuntimeError(
            f"Contact enrichment failed for {result.errors} of "
            f"{result.companies_attempted} companies"
        )

    logger.info(
        "job_completed",
        job="contact_enrichment",
        added=result.added,
        errors=result.errors,
        attempted=result.companies_attempted,
        lead_retries=retried,
    )
    return result.added
