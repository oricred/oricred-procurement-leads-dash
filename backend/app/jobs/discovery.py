from datetime import datetime, timezone, timedelta

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
from app.services.municipal_scraper import CityOfCapeTownAdapter, CityOfJoburgAdapter
from app.services.admin_config import get_config

logger = structlog.get_logger()

SCRAPER_MAP = {
    "joburg": ("City of Johannesburg", CityOfJoburgAdapter),
    "capetown": ("City of Cape Town", CityOfCapeTownAdapter),
}


async def _process_tender(raw: dict, db, now: datetime) -> int:
    api_id = raw.get("id")
    if not api_id:
        return 0

    existing = await db.execute(select(Tender).where(Tender.api_id == api_id))
    if existing.scalar_one_or_none():
        return 0

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

    return await _qualify_and_watch(tender, db, now)


async def _process_scraper_tender(result, metro_name: str, db, now: datetime) -> int:
    api_id = f"municipal_{metro_name}_{result.reference}"
    existing = await db.execute(select(Tender).where(Tender.api_id == api_id))
    if existing.scalar_one_or_none():
        return 0

    raw = {
        "source": f"municipal_scraper_{metro_name}",
        "reference": result.reference,
        "url": result.url,
    }
    org_id = result.buyer_org
    org_result = await db.execute(select(Organization).where(Organization.name == org_id))
    existing_org = org_result.scalar_one_or_none()
    if not existing_org:
        existing_org = Organization(id=org_id, name=org_id)
        db.add(existing_org)
        await db.flush()

    tender = Tender(
        api_id=api_id,
        raw_payload=raw,
        title=result.title,
        description=result.title,
        estimated_value=result.estimated_value,
        province=result.province,
        closing_date=result.closing_date,
        buyer_org_id=existing_org.id,
        tender_type="municipal",
        published_at=now,
        discovered_at=now,
    )
    db.add(tender)
    await db.flush()

    return await _qualify_and_watch(tender, db, now)


async def _qualify_and_watch(tender: Tender, db, now: datetime) -> int:
    qual = QualificationService(db)
    result = await qual.evaluate(tender)
    if not result.passed:
        return 0

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
    return 1


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

        # Discover new tenders from Tenders-SA
        now = datetime.now(timezone.utc)
        since = now
        try:
            raw_tenders = await tenders_client.get_new_tenders(since)
        except Exception as e:
            logger.error("tender_discovery_failed", error=str(e))
            return

        async with async_session() as db:
            count = 0
            for raw in raw_tenders:
                count += await _process_tender(raw, db, now)

            # Discover municipal tenders
            try:
                scraper_config = await get_config("admin_scrapers", db)
                enabled = scraper_config.get("enabled", [])
                metros = scraper_config.get("metros", {})
            except Exception:
                enabled = ["joburg", "capetown"]
                metros = {}

            scraper_since = now - timedelta(days=7)
            for metro_key in enabled:
                meta = SCRAPER_MAP.get(metro_key)
                if not meta:
                    continue
                metro_name, adapter_cls = meta
                metro_config = metros.get(metro_key, {})
                if not metro_config.get("enabled", True):
                    continue

                adapter = adapter_cls()
                try:
                    results = await adapter.get_new_tenders(scraper_since)
                    for res in results:
                        count += await _process_scraper_tender(res, metro_key, db, now)
                    logger.info("municipal_tenders_fetched", metro=metro_key, count=len(results))
                except Exception as e:
                    logger.error("municipal_scraper_failed", metro=metro_key, error=str(e))
                finally:
                    await adapter.close()

            await db.commit()
            logger.info("tenders_discovered", new=count)

    finally:
        await tsa.close()
