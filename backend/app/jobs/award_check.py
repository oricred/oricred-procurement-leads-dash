import hashlib
from collections import defaultdict
from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.clients import TSADatabase
from app.database import async_session
from app.models.watchlist import WatchlistItem
from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.models.organization import Organization
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.services.email_alert import EmailAlertService
from app.services.buyer_preference import compute_buyer_preference
from app.services.funding_suitability import compute_funding_suitability
from app.services.lead_scoring import refresh_lead_scoring
from app.services.lead_service import retry_contact_lookup_for_opportunity, retry_new_lead_contact_lookups
from app.services.crm.sync import push_opportunity_to_crm
from app.workflow import WORKFLOW_STAGES

logger = structlog.get_logger()

AWARD_FIELDS = [
    "id", "tender_id", "supplier_name", "amount", "award_date",
    "bee_level", "bee_points", "supplier_canonical_id",
]

COMPANY_FIELDS = [
    "id", "name", "registration_number", "bbbee_level",
    "contact_email", "contact_phone", "website",
]

ORGANIZATION_FIELDS = [
    "id", "name", "organization_type", "contact_email", "contact_phone",
    "website", "confidence_score", "contact_email_is_role_based",
]


def _supplier_fallback_api_id(supplier: str) -> str:
    digest = hashlib.sha1(supplier.strip().lower().encode("utf-8")).hexdigest()[:32]
    return f"award:{digest}"


async def _upsert_awarded_company(db, raw: dict, company_by_name: dict[str, dict], now: datetime) -> Company:
    supplier = raw.get("supplier_name") or "Unknown"
    co_data = company_by_name.get(supplier) or company_by_name.get(supplier.strip().lower()) or {}
    api_id = co_data.get("id") or raw.get("supplier_canonical_id") or _supplier_fallback_api_id(supplier)

    result = await db.execute(select(Company).where(Company.api_id == api_id))
    company = result.scalar_one_or_none()
    if not company:
        company = Company(api_id=api_id, name=co_data.get("name") or supplier)
        db.add(company)
        await db.flush()

    company.name = co_data.get("name") or supplier
    company.bee_level = co_data.get("bbbee_level") or raw.get("bee_level") or company.bee_level
    company.registration_number = co_data.get("registration_number") or company.registration_number
    company.raw_payload = co_data or {
        "source": "award",
        "award_id": raw.get("id"),
        "supplier_canonical_id": raw.get("supplier_canonical_id"),
    }
    company.last_refreshed_at = now
    return company


async def check_awards_for_watching():
    tsa_db = TSADatabase()
    email = EmailAlertService()
    logger.info("job_started", job="check_awards")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            new_opportunity_ids: list[str] = []

            result = await db.execute(
                select(WatchlistItem, Tender)
                .join(Tender, WatchlistItem.tender_id == Tender.id)
                .where(WatchlistItem.status == "watching")
            )
            rows = result.all()

            if not rows:
                retry_processed = await retry_new_lead_contact_lookups(limit=100)
                logger.info("award_check_no_watching", contact_retry_processed=retry_processed)
                return

            wl_by_api_id = {tender.api_id: (wl, tender) for wl, tender in rows}
            tender_api_ids = list(wl_by_api_id.keys())

            try:
                raw_awards = await tsa_db.query_awards(
                    filters={"tender_ids": tender_api_ids},
                    fields=AWARD_FIELDS,
                )
            except Exception as e:
                logger.error("batch_award_query_failed", error=str(e))
                raw_awards = []

            awards_by_tender: dict[str, list[dict]] = defaultdict(list)
            for aw in raw_awards:
                tid = aw.get("tender_id")
                if tid:
                    awards_by_tender[tid].append(aw)

            all_suppliers = list({aw.get("supplier_name") for aw in raw_awards if aw.get("supplier_name")})
            company_by_name: dict[str, dict] = {}

            if all_suppliers:
                try:
                    raw_companies = await tsa_db.query_companies(
                        filters={"names": all_suppliers},
                        fields=COMPANY_FIELDS,
                    )
                    for co in raw_companies:
                        name = co.get("name", "")
                        company_by_name[name] = co
                        company_by_name[name.strip().lower()] = co
                except Exception as e:
                    logger.warning("batch_company_query_failed", error=str(e))

            bidders_by_tender: dict[str, list[str]] = defaultdict(list)
            try:
                raw_bidders = await tsa_db.query_bidders(tender_ids=tender_api_ids)
                for b in raw_bidders:
                    tid = b.get("tender_id")
                    name = b.get("name")
                    if tid and name:
                        bidders_by_tender[tid].append(name)
            except Exception as e:
                logger.warning("batch_bidder_query_failed", error=str(e))

            for wl, tender in rows:
                matched_awards = awards_by_tender.get(tender.api_id, [])

                if matched_awards:
                    for raw in matched_awards:
                        supplier = raw.get("supplier_name", "Unknown")
                        company = await _upsert_awarded_company(db, raw, company_by_name, now)

                        if tender.buyer_org_id:
                            try:
                                org_results = await tsa_db.query_organizations(
                                    filters={"ids": [tender.buyer_org_id]},
                                    fields=ORGANIZATION_FIELDS,
                                )
                                if org_results:
                                    org_data = org_results[0]
                                    await db.merge(Organization(
                                        id=tender.buyer_org_id,
                                        name=org_data.get("name", tender.buyer_org_id),
                                        organization_type=org_data.get("organization_type"),
                                        contact_email=org_data.get("contact_email"),
                                        contact_phone=org_data.get("contact_phone"),
                                        contact_website=org_data.get("website"),
                                        contact_email_is_role_based=org_data.get("contact_email_is_role_based"),
                                        confidence_score=org_data.get("confidence_score"),
                                        raw_payload=org_data,
                                        last_refreshed_at=now,
                                    ))
                                    await db.flush()
                            except Exception as e:
                                logger.warning("buyer_org_upsert_failed", tender_id=tender.api_id, error=str(e))

                        award = None
                        if raw.get("id"):
                            existing_award = await db.execute(select(Award).where(Award.api_id == raw.get("id")))
                            award = existing_award.scalar_one_or_none()
                        if not award:
                            award = Award(
                                api_id=raw.get("id"),
                                tender_id=tender.id,
                                raw_payload=raw,
                                supplier_name=supplier,
                                supplier_company_id=company.api_id,
                                amount=raw.get("amount"),
                                award_date=raw.get("award_date"),
                                bee_level=raw.get("bee_level"),
                                bee_points=raw.get("bee_points"),
                                buyer_org_id=tender.buyer_org_id,
                                source="tenders_api",
                                discovered_at=now,
                            )
                            db.add(award)
                            await db.flush()

                        existing_opp = await db.execute(select(Opportunity).where(Opportunity.award_id == award.id))
                        if existing_opp.scalar_one_or_none():
                            continue

                        opp = Opportunity(
                            tender_id=tender.id,
                            award_id=award.id,
                            company_id=company.id,
                            kanban_stage=WORKFLOW_STAGES[0],
                            contact_sufficiency="none",
                            risk_flag="green",
                        )
                        db.add(opp)
                        await db.flush()

                        opp.buyer_preference_score = await compute_buyer_preference(str(opp.id), db)
                        opp.funding_suitability = await compute_funding_suitability(company.id, db)
                        await refresh_lead_scoring(opp, db, tender=tender, award=award, company=company, contacts=[])
                        new_opportunity_ids.append(str(opp.id))

                        related = []
                        bidders = bidders_by_tender.get(tender.api_id, [])
                        for bidder_name in bidders:
                            if bidder_name.lower() != supplier.lower():
                                related.append({
                                    "name": bidder_name,
                                    "inferred": False,
                                    "reason": "confirmed bidder",
                                })
                        opp.related_bidders = related if related else None

                        await email.send(
                            "award_detected",
                            "ops@oricred.com",
                            company_name=supplier,
                            tender_title=tender.title,
                            supplier_name=supplier,
                            amount=float(raw.get("amount", 0) or 0),
                            award_date=str(raw.get("award_date", "")),
                            dashboard_url="/opportunities/" + str(opp.id),
                        )

                    wl.status = "awarded"
                    wl.awarded_at = now

                elif wl.expected_window_end and now > wl.expected_window_end:
                    wl.status = "past_due"
                    wl.past_due_at = now
                    existing = await db.execute(
                        select(PastDueQueue).where(PastDueQueue.tender_id == tender.id)
                    )
                    if not existing.scalar_one_or_none():
                        db.add(PastDueQueue(
                            tender_id=tender.id,
                            entered_queue_at=now,
                        ))
                        await email.send(
                            "past_due",
                            "ops@oricred.com",
                            tender_title=tender.title,
                            buyer_org=tender.buyer_org_id or "",
                            category=tender.category_id or "",
                            window_start=str(wl.expected_window_start),
                            window_end=str(wl.expected_window_end),
                            days_overdue=str((now - wl.expected_window_end).days),
                            dashboard_url="/watchlist",
                        )

            await db.commit()

            contacts_added = 0
            for opp_id in new_opportunity_ids:
                try:
                    async with async_session() as lookup_db:
                        _, added = await retry_contact_lookup_for_opportunity(opp_id, lookup_db, tsa_db)
                        contacts_added += added
                    await push_opportunity_to_crm(opp_id)
                except Exception as e:
                    logger.warning("lead_post_create_sync_failed", opportunity_id=opp_id, error=str(e))

            retry_processed = await retry_new_lead_contact_lookups(limit=100)

            logger.info(
                "award_check_complete",
                checked=len(rows),
                awards_found=len(raw_awards),
                leads_created=len(new_opportunity_ids),
                contacts_added=contacts_added,
                contact_retry_processed=retry_processed,
            )

    finally:
        await tsa_db.close()
