from datetime import datetime, timezone

import structlog
from sqlalchemy import select

from app.clients import TSAClient, TendersClient, ReferenceClient
from app.database import async_session
from app.models.tender import Tender
from app.models.category import Category
from app.models.organization import Organization
from app.models.watchlist import WatchlistItem
from app.services.qualification import QualificationService
from app.services.award_timing import AwardTimingService

logger = structlog.get_logger()


async def discover_new_tenders():
    tsa = TSAClient()
    tenders_client = TendersClient(tsa)
    ref_client = ReferenceClient(tsa)
    logger.info("job_started", job="discover_tenders")

    try:
        # Refresh reference data
        try:
            cats = await ref_client.get_categories()
            async with async_session() as db:
                for cat in cats:
                    await db.merge(Category(id=cat["id"], name=cat.get("name", ""), parent_id=cat.get("parent_id"), raw_payload=cat))
                await db.commit()
        except Exception as e:
            logger.warning("category_refresh_failed", error=str(e))

        # Discover new tenders
        now = datetime.now(timezone.utc)
        since = now  # Will need a persistent last_poll timestamp in production
        try:
            raw_tenders = await tenders_client.get_new_tenders(since)
        except Exception as e:
            logger.error("tender_discovery_failed", error=str(e))
            return

        async with async_session() as db:
            count = 0
            for raw in raw_tenders:
                api_id = raw.get("id")
                if not api_id:
                    continue

                existing = await db.execute(select(Tender).where(Tender.api_id == api_id))
                if existing.scalar_one_or_none():
                    continue

                org_id = raw.get("organization_id")
                if org_id:
                    org_result = await db.execute(select(Organization).where(Organization.id == org_id))
                    if not org_result.scalar_one_or_none():
                        db.add(Organization(id=org_id, name=raw.get("buyer_name", org_id)))

                tender = Tender(
                    api_id=api_id,
                    raw_payload=raw,
                    title=raw.get("title", "Untitled"),
                    description=raw.get("description"),
                    estimated_value=raw.get("estimated_value"),
                    province=raw.get("province"),
                    category_id=raw.get("category_id"),
                    closing_date=raw.get("closing_date"),
                    buyer_org_id=org_id,
                    tender_type=raw.get("tender_type"),
                    published_at=raw.get("published_at"),
                    discovered_at=now,
                )
                db.add(tender)
                await db.flush()

                # Run qualification filter
                qual = QualificationService(db)
                result = await qual.evaluate(tender)
                if result.passed:
                    timing = AwardTimingService(db)
                    start, end = await timing.get_expected_window(
                        tender.buyer_org_id, tender.category_id, tender.closing_date
                    )
                    db.add(WatchlistItem(
                        tender_id=tender.id,
                        status="watching",
                        expected_window_start=start,
                        expected_window_end=end,
                        started_watching_at=now,
                    ))
                    count += 1

            await db.commit()
            logger.info("tenders_discovered", new=count)

    finally:
        await tsa.close()
