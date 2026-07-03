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
from app.services.contact_sufficiency import ContactSufficiencyService
from app.services.email_alert import EmailAlertService
from app.services.buyer_preference import compute_buyer_preference
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


async def check_awards_for_watching():
    tsa_db = TSADatabase()
    email = EmailAlertService()
    logger.info("job_started", job="check_awards")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            # Load all watching watchlist items with their tenders
            result = await db.execute(
                select(WatchlistItem, Tender)
                .join(Tender, WatchlistItem.tender_id == Tender.id)
                .where(WatchlistItem.status == "watching")
            )
            rows = result.all()

            if not rows:
                logger.info("award_check_no_watching")
                return

            # Build lookup: TSA tender_id → (wl, our_tender)
            wl_by_api_id = {tender.api_id: (wl, tender) for wl, tender in rows}
            tender_api_ids = list(wl_by_api_id.keys())

            # ── Batch query awards from TSA DB ──
            try:
                raw_awards = await tsa_db.query_awards(
                    filters={"tender_ids": tender_api_ids},
                    fields=AWARD_FIELDS,
                )
            except Exception as e:
                logger.error("batch_award_query_failed", error=str(e))
                raw_awards = []

            # Group awards by TSA tender_id
            awards_by_tender: dict[str, list[dict]] = defaultdict(list)
            for aw in raw_awards:
                tid = aw.get("tender_id")
                if tid:
                    awards_by_tender[tid].append(aw)

            # ── Batch query companies for all unique suppliers ──
            all_suppliers = list({aw.get("supplier_name") for aw in raw_awards if aw.get("supplier_name")})
            company_by_name: dict[str, dict] = {}

            if all_suppliers:
                try:
                    raw_companies = await tsa_db.query_companies(
                        filters={"names": all_suppliers},
                        fields=COMPANY_FIELDS,
                    )
                    for co in raw_companies:
                        company_by_name[co.get("name", "")] = co
                except Exception as e:
                    logger.warning("batch_company_query_failed", error=str(e))

            # ── Batch query bidders for competitor intel ──
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

            # Process each watching tender
            for wl, tender in rows:
                matched_awards = awards_by_tender.get(tender.api_id, [])

                if matched_awards:
                    for raw in matched_awards:
                        supplier = raw.get("supplier_name", "Unknown")

                        # Upsert company (from batch data)
                        company = None
                        co_data = company_by_name.get(supplier)
                        if co_data:
                            company = await db.merge(Company(
                                api_id=co_data.get("id", supplier),
                                name=supplier,
                                bee_level=co_data.get("bbbee_level"),
                                registration_number=co_data.get("registration_number"),
                                raw_payload=co_data,
                                last_refreshed_at=now,
                            ))
                            await db.flush()
                        elif raw.get("supplier_canonical_id"):
                            company = await db.merge(Company(
                                api_id=raw["supplier_canonical_id"],
                                name=supplier,
                                raw_payload={"source": "award", "award_id": raw.get("id")},
                                last_refreshed_at=now,
                            ))
                            await db.flush()

                        # Upsert buyer organization
                        org = None
                        if tender.buyer_org_id:
                            try:
                                org_results = await tsa_db.query_organizations(
                                    filters={"ids": [tender.buyer_org_id]},
                                    fields=ORGANIZATION_FIELDS,
                                )
                                if org_results:
                                    org_data = org_results[0]
                                    org = Organization(
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
                                    )
                                    db.merge(org)
                                    await db.flush()
                            except Exception:
                                pass

                        # Create award record
                        award = Award(
                            api_id=raw.get("id"),
                            tender_id=tender.id,
                            raw_payload=raw,
                            supplier_name=supplier,
                            supplier_company_id=company.api_id if company else None,
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

                        # Classify contact sufficiency
                        cs = ContactSufficiencyService.classify(org)

                        # Create opportunity
                        opp = Opportunity(
                            tender_id=tender.id,
                            award_id=award.id,
                            company_id=company.id if company else None,
                            kanban_stage=WORKFLOW_STAGES[0],
                            contact_sufficiency=cs.label,
                            risk_flag="green",
                        )
                        db.add(opp)
                        await db.flush()

                        opp.buyer_preference_score = await compute_buyer_preference(str(opp.id), db)

                        # Build related bidders from TSA DB bidders
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

                        await push_opportunity_to_crm(str(opp.id))

                    wl.status = "awarded"
                    wl.awarded_at = now

                else:
                    # No award found — check if past due
                    if wl.expected_window_end and now > wl.expected_window_end:
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
            logger.info("award_check_complete", checked=len(rows), awards_found=len(raw_awards))

    finally:
        await tsa_db.close()

