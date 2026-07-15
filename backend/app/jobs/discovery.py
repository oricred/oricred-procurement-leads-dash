from datetime import datetime, timezone, timedelta

import structlog
from sqlalchemy import select

from app.clients import TSADatabase
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

SOURCE_MAP = {
    "joburg": ("municipal", "City of Johannesburg", CityOfJoburgAdapter),
    "capetown": ("municipal", "City of Cape Town", CityOfCapeTownAdapter),
    "ocpo": ("api", "OCPO", None),
    "etenders": ("api", "e-Tenders", None),
    "tsa_ocp": ("api", "Tenders-SA OCP", None),
}

TENDER_FIELDS = [
    "tender_id", "title", "description", "estimated_value", "province",
    "category_id", "closing_date", "source_organization_id",
    "source_organization", "type", "publication_date",
]
TENDER_INGEST_PAGE_SIZE = 1_000
TENDER_INGEST_MAX_PAGES = 20


async def _process_tender(raw: dict, db, now: datetime) -> int:
    api_id = raw.get("tender_id")
    if not api_id:
        return 0

    existing = await db.execute(select(Tender).where(Tender.api_id == api_id))
    if existing.scalar_one_or_none():
        return 0

    org_id = raw.get("source_organization_id")
    org_name = raw.get("source_organization", org_id or "")
    if org_id:
        org_result = await db.execute(select(Organization).where(Organization.id == org_id))
        if not org_result.scalar_one_or_none():
            db.add(Organization(id=org_id, name=org_name))

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
        tender_type=raw.get("type"),
        published_at=raw.get("publication_date"),
        discovered_at=now,
    )
    db.add(tender)
    await db.flush()

    await _qualify_and_watch(tender, db, now)
    return 1


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

    await _qualify_and_watch(tender, db, now)
    return 1


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
    tsa_db = TSADatabase()
    logger.info("job_started", job="discover_tenders")

    try:
        # Refresh categories from TSA DB
        try:
            cats = await tsa_db.query_categories()
            async with async_session() as db:
                for cat in cats:
                    await db.merge(Category(
                        id=cat["id"],
                        name=cat.get("canonical_name") or cat.get("name", ""),
                        parent_id=cat.get("parent_id"),
                        raw_payload=cat,
                    ))
                await db.commit()
        except Exception as e:
            logger.warning("category_refresh_failed", error=str(e))

        now = datetime.now(timezone.utc)

        async with async_session() as db:
            count = 0

            # Persist every currently open Tenders-SA tender. Qualification is
            # applied only after storage to decide whether it should be watched.
            raw_tenders: list[dict] = []
            try:
                source_filters = {"closing_from": now.isoformat()}
                for page in range(TENDER_INGEST_MAX_PAGES):
                    batch = await tsa_db.query_tenders(
                        filters=source_filters,
                        fields=TENDER_FIELDS,
                        limit=TENDER_INGEST_PAGE_SIZE,
                        offset=page * TENDER_INGEST_PAGE_SIZE,
                    )
                    raw_tenders.extend(batch)
                    if len(batch) < TENDER_INGEST_PAGE_SIZE:
                        break
                else:
                    logger.warning("tender_ingestion_page_limit_reached", pages=TENDER_INGEST_MAX_PAGES)
            except Exception as e:
                logger.error("tender_query_failed", error=str(e))
                raw_tenders = []

            for raw in raw_tenders:
                count += await _process_tender(raw, db, now)

            # ── Discover tenders from municipal scrapers ──
            try:
                src_config = await get_config("admin_sources", db)
                enabled = src_config.get("enabled", [])
                metros = src_config.get("metros", {})
                api_sources = src_config.get("api_sources", {})
            except Exception:
                enabled = ["joburg", "capetown"]
                metros = {}
                api_sources = {}

            source_since = now - timedelta(days=7)
            for src_key in enabled:
                meta = SOURCE_MAP.get(src_key)
                if not meta:
                    continue
                src_type, src_name, adapter_cls = meta

                if src_type == "municipal":
                    src_config_section = metros.get(src_key, {})
                    if not src_config_section.get("enabled", True):
                        continue
                    if not adapter_cls:
                        continue
                    adapter = adapter_cls(src_config_section.get("base_url") or None)
                    try:
                        results = await adapter.get_new_tenders(source_since)
                        for res in results:
                            count += await _process_scraper_tender(res, src_key, db, now)
                        logger.info("source_tenders_fetched", source=src_key, count=len(results))
                    except Exception as e:
                        logger.error("source_fetch_failed", source=src_key, error=str(e))
                    finally:
                        await adapter.close()

                elif src_type == "api":
                    src_cfg = api_sources.get(src_key, {})
                    if not src_cfg.get("enabled", False):
                        continue
                    logger.info("api_source_configured", source=src_key, name=src_name, base_url=src_cfg.get("base_url"))

            await db.commit()
            logger.info("tenders_ingested", source="tenders_sa", new=count, queried=len(raw_tenders))
            return count

    finally:
        await tsa_db.close()
