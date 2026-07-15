from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.tsa_db import TSADatabase
from app.database import async_session
from app.models.opportunity import Opportunity, OpportunityAudit
from app.services.contact_enrichment import enrich_company_contacts_by_id
from app.services.lead_scoring import refresh_lead_scoring
from app.workflow import WORKFLOW_STAGES

logger = structlog.get_logger()
CONTACT_RETRY_COOLDOWN_HOURS = 6


async def retry_contact_lookup_for_opportunity(
    opportunity_id: str,
    db: AsyncSession,
    tsa_db: TSADatabase | None = None,
) -> tuple[Opportunity, int]:
    opp = await db.get(Opportunity, opportunity_id)
    if not opp:
        raise ValueError("Opportunity not found")

    added = 0
    owns_client = tsa_db is None
    client = tsa_db or TSADatabase()
    try:
        if opp.company_id:
            added = await enrich_company_contacts_by_id(opp.company_id, client)
        opp.last_contact_lookup_at = datetime.now(timezone.utc)
        await refresh_lead_scoring(opp, db)
        await db.commit()
        await db.refresh(opp)
        return opp, added
    finally:
        if owns_client:
            await client.close()


async def retry_new_lead_contact_lookups(limit: int = 50) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=CONTACT_RETRY_COOLDOWN_HOURS)
    processed = 0
    tsa_db = TSADatabase()
    try:
        async with async_session() as db:
            result = await db.execute(
                select(Opportunity)
                .where(Opportunity.kanban_stage == WORKFLOW_STAGES[0])
                .where(Opportunity.company_id.isnot(None))
                .where(or_(
                    Opportunity.contact_sufficiency.is_(None),
                    Opportunity.contact_sufficiency.in_(("none", "role_based")),
                ))
                .where(or_(
                    Opportunity.last_contact_lookup_at.is_(None),
                    Opportunity.last_contact_lookup_at <= cutoff,
                ))
                .order_by(Opportunity.created_at.desc())
                .limit(limit)
            )
            opportunities = result.scalars().all()

            for opp in opportunities:
                try:
                    await retry_contact_lookup_for_opportunity(str(opp.id), db, tsa_db)
                    processed += 1
                except Exception as e:
                    logger.warning("lead_contact_retry_failed", opportunity_id=str(opp.id), error=str(e))
                    await db.rollback()
    finally:
        await tsa_db.close()
    return processed


async def mark_opportunity_contacted(
    opportunity_id: str,
    version: int,
    db: AsyncSession,
    contact_id: str | None = None,
    note: str | None = None,
    changed_by: str = "system",
) -> Opportunity:
    opp = await db.get(Opportunity, opportunity_id)
    if not opp:
        raise ValueError("Opportunity not found")
    if opp.version != version:
        raise RuntimeError("Version conflict: opportunity was modified")

    if opp.kanban_stage != "new_lead":
        raise RuntimeError("Only a new lead can be marked contacted")

    old_stage = opp.kanban_stage
    opp.kanban_stage = "client_contacted"
    opp.contacted_at = datetime.now(timezone.utc)
    opp.version += 1
    opp.updated_at = datetime.now(timezone.utc)
    opp.next_action = "Qualify lead"
    if note:
        prefix = opp.notes + "\n\n" if opp.notes else ""
        opp.notes = f"{prefix}{note}"

    db.add(OpportunityAudit(
        opportunity_id=opp.id,
        from_stage=old_stage,
        to_stage="client_contacted",
        changed_by=changed_by,
    ))
    await db.commit()
    await db.refresh(opp)
    return opp

