import structlog
from datetime import datetime, timezone

from sqlalchemy import select

from app.clients import TSADatabase
from app.database import async_session
from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.buyer_relationship import BuyerRelationship
from app.services.buyer_relationship import compute_relationship
from app.services.buyer_preference import compute_buyer_preference
from app.services.funding_suitability import compute_funding_suitability
from app.services.lead_scoring import refresh_lead_scoring
from app.services.text_utils import best_title

logger = structlog.get_logger()

TENDER_FIELDS = [
    "id", "tender_id", "title", "description", "estimated_value", "province",
    "category_id", "closing_date", "source_organization_id",
    "source_organization", "type", "publication_date",
    "ai_title_enriched",
]


async def backfill_stub_tenders() -> int:
    """Backfill province, category, buyer_org for stub tenders created before the
    award_check tender_id mapping fix, then recompute dependent data."""
    tsa_db = TSADatabase()
    logger.info("job_started", job="backfill_stub_tenders")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            # Find all stub tenders — those where province is NULL (created
            # by the broken award_check path before the fix).
            stub_result = await db.execute(
                select(Tender).where(Tender.province.is_(None))
            )
            stubs = stub_result.scalars().all()
            if not stubs:
                logger.info("no_stub_tenders_found")
                return 0

            stub_uuids = [t.api_id for t in stubs if t.api_id]
            logger.info("found_stub_tenders", count=len(stubs), uuids=len(stub_uuids))

            # Query TSA DB for full tender data by UUID (t.id)
            try:
                raw_tenders = await tsa_db.query_tenders(
                    filters={"ids": stub_uuids},
                    fields=TENDER_FIELDS,
                    limit=max(len(stub_uuids), 1),
                )
            except Exception as exc:
                logger.error("tsa_query_failed", error=str(exc))
                raw_tenders = []

            # Build lookup by UUID
            tsa_by_uuid = {str(t["id"]): t for t in raw_tenders if t.get("id")}
            logger.info("tsa_results", queried=len(stub_uuids), matched=len(tsa_by_uuid))

            updated_count = 0
            orgs_to_fetch = set()

            for stub in stubs:
                tsa_data = tsa_by_uuid.get(stub.api_id)
                if not tsa_data:
                    logger.warning("no_tsa_data_for_stub", api_id=stub.api_id, title=stub.title)
                    continue

                biz_id = tsa_data.get("tender_id")
                province = tsa_data.get("province")
                category_id = tsa_data.get("category_id")
                buyer_org_id = tsa_data.get("source_organization_id")

                # If this business ID matches an existing real tender, copy
                # data from it instead of overwriting the stub entirely.
                if biz_id:
                    real = await db.execute(
                        select(Tender).where(Tender.api_id == biz_id, Tender.id != stub.id)
                    )
                    real_tender = real.scalar_one_or_none()
                    if real_tender:
                        province = province or real_tender.province
                        category_id = category_id or real_tender.category_id
                        buyer_org_id = buyer_org_id or real_tender.buyer_org_id

                # Update stub tender with populated data
                stub.title = best_title(tsa_data) or stub.title
                stub.description = tsa_data.get("description") or stub.description
                stub.estimated_value = tsa_data.get("estimated_value") or stub.estimated_value
                if province:
                    stub.province = province
                if category_id:
                    stub.category_id = category_id
                if buyer_org_id:
                    stub.buyer_org_id = buyer_org_id
                    orgs_to_fetch.add(buyer_org_id)
                stub.tender_type = tsa_data.get("type") or stub.tender_type
                if biz_id:
                    stub.api_id = biz_id

                updated_count += 1

            if not updated_count:
                logger.info("no_tenders_updated")
                return 0

            await db.flush()
            logger.info("stub_tenders_updated", count=updated_count, orgs_to_fetch=len(orgs_to_fetch))

            # Fetch buyer organizations from TSA DB
            for org_id in orgs_to_fetch:
                try:
                    org_results = await tsa_db.query_organizations(
                        filters={"ids": [org_id]},
                        fields=["id", "name", "organization_type", "contact_email",
                                "contact_phone", "website", "confidence_score",
                                "contact_email_is_role_based"],
                    )
                    if org_results:
                        from app.models.organization import Organization
                        org_data = org_results[0]
                        await db.merge(Organization(
                            id=org_data["id"],
                            name=org_data.get("name", org_id),
                            organization_type=org_data.get("organization_type"),
                            contact_email=org_data.get("contact_email"),
                            contact_phone=org_data.get("contact_phone"),
                            contact_website=org_data.get("website"),
                            contact_email_is_role_based=org_data.get("contact_email_is_role_based"),
                            confidence_score=org_data.get("confidence_score"),
                            raw_payload={k: v for k, v in org_data.items() if v is not None},
                            last_refreshed_at=now,
                        ))
                except Exception as exc:
                    logger.warning("org_upsert_failed", org_id=org_id, error=str(exc))

            await db.flush()

            # Update awards' buyer_org_id from now-populated tenders
            stub_ids = [s.id for s in stubs]
            award_result = await db.execute(
                select(Award).where(Award.tender_id.in_(stub_ids))
            )
            awards = award_result.scalars().all()
            for award in awards:
                t_result = await db.execute(select(Tender).where(Tender.id == award.tender_id))
                tender_for_award = t_result.scalar_one_or_none()
                if tender_for_award:
                    award.buyer_org_id = tender_for_award.buyer_org_id
            await db.flush()

            # Recompute relationships for all companies linked to these opportunities
            opp_result = await db.execute(
                select(Opportunity).where(Opportunity.tender_id.in_(stub_ids))
            )
            opps = opp_result.scalars().all()
            for opp in opps:
                if not opp.company_id:
                    continue
                # Get org_id from the now-populated tender
                tender_result = await db.execute(
                    select(Tender).where(Tender.id == opp.tender_id)
                )
                tender = tender_result.scalar_one_or_none()
                if not tender or not tender.buyer_org_id:
                    continue

                # Compute relationship
                try:
                    await compute_relationship(opp.company_id, tender.buyer_org_id, db)
                except Exception as exc:
                    logger.warning("relationship_compute_failed", opportunity_id=opp.id, error=str(exc))

                # Recompute scores
                try:
                    opp.buyer_preference_score = await compute_buyer_preference(str(opp.id), db)
                except Exception as exc:
                    logger.warning("preference_compute_failed", opportunity_id=opp.id, error=str(exc))

                company_obj = (await db.execute(select(Company).where(Company.id == opp.company_id))).scalar_one_or_none() if opp.company_id else None
                try:
                    if company_obj:
                        opp.funding_suitability = await compute_funding_suitability(company_obj.id, db)
                except Exception as exc:
                    logger.warning("funding_compute_failed", opportunity_id=opp.id, error=str(exc))

                award_obj = (await db.execute(select(Award).where(Award.id == opp.award_id))).scalar_one_or_none() if opp.award_id else None
                try:
                    await refresh_lead_scoring(opp, db, tender=tender, award=award_obj, company=company_obj, contacts=[])
                except Exception as exc:
                    logger.warning("lead_scoring_failed", opportunity_id=opp.id, error=str(exc))

            await db.commit()
            logger.info("backfill_complete", tenders_updated=updated_count, awards_updated=len(awards), opportunities_recomputed=len(opps))
            return updated_count

    finally:
        await tsa_db.close()
