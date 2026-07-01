from datetime import datetime, timezone

import structlog
from sqlalchemy import select, and_

from app.clients import TSAClient, AwardsClient, CompaniesClient, OrganizationsClient, ForensicClient
from app.database import async_session
from app.models.watchlist import WatchlistItem
from app.models.tender import Tender
from app.models.award import Award
from app.models.company import Company
from app.models.organization import Organization
from app.models.opportunity import Opportunity
from app.models.past_due import PastDueQueue
from app.services.contact_sufficiency import ContactSufficiencyService
from app.services.competitor_intel import CompetitorIntelService
from app.services.email_alert import EmailAlertService
from app.services.buyer_preference import compute_buyer_preference
from app.services.crm.sync import push_opportunity_to_crm

logger = structlog.get_logger()


async def check_awards_for_watching():
    tsa = TSAClient()
    awards_client = AwardsClient(tsa)
    companies_client = CompaniesClient(tsa)
    orgs_client = OrganizationsClient(tsa)
    forensic_client = ForensicClient(tsa)
    email = EmailAlertService()
    logger.info("job_started", job="check_awards")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)

            # Watching tenders inside or past their window
            result = await db.execute(
                select(WatchlistItem, Tender)
                .join(Tender, WatchlistItem.tender_id == Tender.id)
                .where(WatchlistItem.status == "watching")
            )
            rows = result.all()

            for wl, tender in rows:
                try:
                    raw_awards = await awards_client.get_awards_by_tender(tender.api_id)
                except Exception as e:
                    logger.warning("award_check_failed", tender_id=tender.api_id, error=str(e))
                    continue

                if raw_awards:
                    # Award found
                    for raw in raw_awards:
                        supplier = raw.get("supplier_name", "Unknown")

                        # Upsert company
                        company = None
                        try:
                            co_data = await companies_client.get_company(supplier)
                            if co_data:
                                company = Company(
                                    api_id=co_data.get("id", supplier),
                                    name=supplier,
                                    bee_level=co_data.get("bee_level"),
                                    cipc_forensic_risk_score=co_data.get("cipc_forensic_risk_score"),
                                    restricted_supplier=co_data.get("restricted_supplier", False),
                                    raw_payload=co_data,
                                    last_refreshed_at=now,
                                )
                                db.merge(company)
                                await db.flush()
                        except Exception:
                            pass

                        # Upsert organization
                        org = None
                        if tender.buyer_org_id:
                            try:
                                org_data = await orgs_client.get_organization(tender.buyer_org_id)
                                if org_data:
                                    org = Organization(
                                        id=tender.buyer_org_id,
                                        name=org_data.get("name", tender.buyer_org_id),
                                        organization_type=org_data.get("organization_type"),
                                        contact_email=org_data.get("contact_email"),
                                        contact_phone=org_data.get("contact_phone"),
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
                            kanban_stage="new",
                            contact_sufficiency=cs.label,
                            risk_flag="green",
                        )
                        db.add(opp)
                        await db.flush()

                        opp.buyer_preference_score = await compute_buyer_preference(str(opp.id), db)

                        try:
                            ci = CompetitorIntelService(db, tenders_client, companies_client, forensic_client)
                            related = []
                            try:
                                if tender.closing_date and now > tender.closing_date:
                                    related = [
                                        {"name": c.name, "inferred": c.inferred, "company_id": c.company_id, "resolved": c.resolved, "reason": c.reason}
                                        for c in await ci.get_confirmed_competitors(tender.api_id)
                                    ]
                                else:
                                    related = [
                                        {"name": c.name, "inferred": c.inferred, "company_id": c.company_id, "resolved": c.resolved, "reason": c.reason}
                                        for c in await ci.get_speculative_competitors(tender.buyer_org_id, tender.category_id)
                                    ]
                            except Exception as e:
                                logger.warning("related_bidders_fetch_failed", error=str(e))
                            opp.related_bidders = related or None
                        except Exception as e:
                            logger.warning("competitor_intel_failed", error=str(e))

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
            logger.info("award_check_complete", checked=len(rows))

    finally:
        await tsa.close()
