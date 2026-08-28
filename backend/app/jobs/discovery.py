from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select

from app.utils import parse_datetime


def _sanitize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {k: _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value

from app.clients import TSADatabase
from app.database import async_session
from app.models.category import Category
from app.models.organization import Organization
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.services.admin_config import get_config
from app.services.award_timing import AwardTimingService
from app.services.municipal_scraper import CityOfCapeTownAdapter, CityOfJoburgAdapter
from app.services.qualification import QualificationService
from app.services.text_utils import best_title

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
    "source_organization", "organization_type", "type", "publication_date",
    "ai_title_enriched",
]
TENDER_INGEST_PAGE_SIZE = 1_000
TENDER_INGEST_MAX_PAGES = 20
# Tenders per preload-process-commit chunk. Each chunk takes a connection from
# the pool, does four bulk SELECTs, and gives the connection back. The whole run
# used to be one session and one transaction across every tender.
TENDER_PROCESS_CHUNK = 500


@dataclass
class DiscoveryCache:
    """Local rows this chunk may touch, loaded once up front.

    The loop issued a tender lookup, an organization lookup, a watchlist lookup
    and a past-due lookup per tender — four round trips across up to 20,000
    tenders, every fifteen minutes, which is what kept a discovery pass running
    for hours and held a connection for all of it.

    `loaded_tender_ids` is what makes a cache miss trustworthy. A miss only means
    "no such row" for a tender that was actually in the preload scope; for
    anything else the caller must still query, or it would create a second
    watchlist item for a tender that already has one. Tenders created inside the
    loop are added to it, since a brand-new tender cannot have dependent rows.
    """

    tenders: dict[str, Tender]
    organizations: dict[str, Organization]
    watches: dict[str, WatchlistItem]
    past_due: dict[str, PastDueQueue]
    loaded_tender_ids: set[str]


async def _preload(db, raw_tenders: list[dict]) -> DiscoveryCache:
    """Load every local row this chunk could touch, keyed for O(1) lookup."""
    api_ids = {str(raw["tender_id"]) for raw in raw_tenders if raw.get("tender_id")}
    org_ids = {
        str(raw["source_organization_id"])
        for raw in raw_tenders
        if raw.get("source_organization_id")
    }

    tenders: dict[str, Tender] = {}
    if api_ids:
        for tender in (
            await db.execute(select(Tender).where(Tender.api_id.in_(api_ids)))
        ).scalars():
            tenders[tender.api_id] = tender

    organizations: dict[str, Organization] = {}
    if org_ids:
        for org in (
            await db.execute(select(Organization).where(Organization.id.in_(org_ids)))
        ).scalars():
            organizations[org.id] = org

    tender_ids = {tender.id for tender in tenders.values()}
    watches: dict[str, WatchlistItem] = {}
    past_due: dict[str, PastDueQueue] = {}
    if tender_ids:
        # No status filter: qualification reconciles awarded, unqualified and
        # past-due watches, so it needs to see all of them.
        for watch in (
            await db.execute(
                select(WatchlistItem).where(WatchlistItem.tender_id.in_(tender_ids))
            )
        ).scalars():
            watches[watch.tender_id] = watch
        for row in (
            await db.execute(
                select(PastDueQueue).where(PastDueQueue.tender_id.in_(tender_ids))
            )
        ).scalars():
            past_due[row.tender_id] = row

    return DiscoveryCache(tenders, organizations, watches, past_due, tender_ids)


async def _process_tender(
    raw: dict, db, now: datetime, stats: Counter | None = None,
    cache: DiscoveryCache | None = None,
) -> int:
    api_id = raw.get("tender_id")
    if not api_id:
        return 0

    api_id = str(api_id)
    tender = cache.tenders.get(api_id) if cache is not None else None
    if tender is None and (cache is None or api_id not in cache.tenders):
        tender = (
            await db.execute(select(Tender).where(Tender.api_id == api_id))
        ).scalar_one_or_none()

    org_id = raw.get("source_organization_id")
    org_name = raw.get("source_organization", org_id or "")
    if org_id:
        org = cache.organizations.get(org_id) if cache is not None else None
        if org is None:
            org = (
                await db.execute(select(Organization).where(Organization.id == org_id))
            ).scalar_one_or_none()
        if not org:
            org = Organization(id=org_id, name=org_name)
            db.add(org)
        else:
            org.name = org_name or org.name
        org.organization_type = raw.get("organization_type") or org.organization_type
        if cache is not None:
            # A later tender in the same chunk shares this buyer.
            cache.organizations[org_id] = org

    created = tender is None
    if tender is None:
        tender = Tender(api_id=api_id, raw_payload={}, title=best_title(raw), discovered_at=now)
        db.add(tender)
        if cache is not None:
            cache.tenders[api_id] = tender

    # Guarded: this is the largest column on the row, and rewriting it on every
    # pass made 20,000 JSON updates every fifteen minutes out of a feed that
    # barely changes between runs.
    payload = _sanitize(raw)
    if tender.raw_payload != payload:
        tender.raw_payload = payload
    tender.title = best_title(raw)
    tender.description = raw.get("description")
    tender.estimated_value = raw.get("estimated_value")
    tender.province = raw.get("province")
    tender.category_id = raw.get("category_id")
    tender.closing_date = parse_datetime(raw.get("closing_date"))
    tender.buyer_org_id = org_id
    tender.tender_type = raw.get("type")
    tender.published_at = parse_datetime(raw.get("publication_date"))
    await db.flush()

    if cache is not None and created:
        # Only a tender created just now. It cannot have a watchlist or past-due
        # row, so a cache miss for it is the truth. A tender that already existed
        # but was not preloaded must stay out of scope, or _qualify_and_watch
        # would read the miss as "no watch" and insert a second one.
        cache.loaded_tender_ids.add(tender.id)

    await _qualify_and_watch(tender, db, now, stats, cache)
    return 1


async def _process_scraper_tender(
    result, metro_name: str, db, now: datetime, stats: Counter | None = None,
    cache: DiscoveryCache | None = None,
) -> int:
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
        raw_payload=_sanitize(raw),
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

    if cache is not None:
        cache.loaded_tender_ids.add(tender.id)

    await _qualify_and_watch(tender, db, now, stats, cache)
    return 1


async def _qualify_and_watch(
    tender: Tender, db, now: datetime, stats: Counter | None = None,
    cache: DiscoveryCache | None = None,
) -> int:
    # Both optional so the helpers stay callable on their own; only the full
    # discovery pass cares about the totals or the preloaded rows.
    stats = Counter() if stats is None else stats

    # A miss is only conclusive for a tender the preload actually covered.
    if cache is not None and tender.id in cache.loaded_tender_ids:
        existing = cache.watches.get(tender.id)
        past_due = cache.past_due.get(tender.id)
    else:
        existing = (
            await db.execute(
                select(WatchlistItem).where(WatchlistItem.tender_id == tender.id)
            )
        ).scalar_one_or_none()
        past_due = (
            await db.execute(
                select(PastDueQueue).where(PastDueQueue.tender_id == tender.id)
            )
        ).scalar_one_or_none()

    qual = QualificationService(db)
    result = await qual.evaluate(tender)
    if not result.passed:
        # Counted, not logged. Per-tender rejection lines are at debug in
        # QualificationService; the run summary carries the totals.
        stats["rejected"] += 1
        stats[f"reason:{result.reason}"] += 1
        if existing and existing.status != "awarded":
            existing.status = "unqualified"
            existing.expected_window_start = None
            existing.expected_window_end = None
            existing.past_due_at = None
        if past_due and past_due.resolution == "pending":
            past_due.resolution = "unqualified"
            past_due.resolved_at = now
        return 0

    stats["qualified"] += 1
    timing = AwardTimingService(db)
    start, end = await timing.get_expected_window(
        tender.buyer_org_id, tender.category_id, tender.closing_date
    )
    if existing:
        if existing.status == "awarded":
            return 0
        existing.expected_window_start = start
        existing.expected_window_end = end
        if end is not None and end < now:
            existing.status = "past_due"
            existing.past_due_at = existing.past_due_at or now
            if not past_due:
                queued = PastDueQueue(tender_id=tender.id, entered_queue_at=now)
                db.add(queued)
                if cache is not None:
                    cache.past_due[tender.id] = queued
            elif past_due.resolution != "pending":
                past_due.resolution = "pending"
                past_due.resolved_at = None
                past_due.entered_queue_at = now
                past_due.poll_count_since_due = 0
        else:
            existing.status = "watching"
            existing.past_due_at = None
            if past_due and past_due.resolution == "pending":
                past_due.resolution = "date_extended"
                past_due.resolved_at = now
        return 0

    is_past_due = end is not None and end < now
    watch = WatchlistItem(
        tender_id=tender.id,
        status="past_due" if is_past_due else "watching",
        expected_window_start=start,
        expected_window_end=end,
        started_watching_at=now,
        past_due_at=now if is_past_due else None,
    )
    db.add(watch)
    if cache is not None:
        cache.watches[tender.id] = watch
    if is_past_due and not past_due:
        queued = PastDueQueue(tender_id=tender.id, entered_queue_at=now)
        db.add(queued)
        if cache is not None:
            cache.past_due[tender.id] = queued
    return 1


async def _fetch_open_tenders(tsa_db: TSADatabase, now: datetime) -> list[dict]:
    """Every currently open tender on the source, paged."""
    raw_tenders: list[dict] = []
    source_filters = {"closing_from": now.replace(tzinfo=None)}
    try:
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
            logger.warning(
                "tender_ingestion_page_limit_reached", pages=TENDER_INGEST_MAX_PAGES
            )
    except Exception as e:
        logger.exception("tender_query_failed", error=str(e))
        raise
    return raw_tenders


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
                        id=cat.get("canonical_name") or cat.get("id"),
                        name=cat.get("name") or cat.get("canonical_name", ""),
                        parent_id=cat.get("parent_id"),
                        raw_payload=_sanitize(cat),
                    ))
                await db.commit()
        except Exception as e:
            logger.warning("category_refresh_failed", error=str(e))

        now = datetime.now(timezone.utc)
        count = 0
        stats: Counter = Counter()

        # Persist every currently open Tenders-SA tender. Qualification is
        # applied only after storage to decide whether it should be watched.
        raw_tenders = await _fetch_open_tenders(tsa_db, now)

        # One session and one transaction per chunk, not one for the whole pass.
        # A pass over 20,000 tenders held a single connection for hours, which
        # starved the pool that every other job and every API request draws from.
        for start_index in range(0, len(raw_tenders), TENDER_PROCESS_CHUNK):
            chunk = raw_tenders[start_index:start_index + TENDER_PROCESS_CHUNK]
            async with async_session() as db:
                cache = await _preload(db, chunk)
                for raw in chunk:
                    count += await _process_tender(raw, db, now, stats, cache)
                await db.commit()

        async with async_session() as db:
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
                            count += await _process_scraper_tender(
                                res, src_key, db, now, stats
                            )
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
            logger.info(
                "tenders_synced",
                source="tenders_sa",
                processed=count,
                queried=len(raw_tenders),
                qualified=stats["qualified"],
                rejected=stats["rejected"],
                rejection_reasons={
                    key.removeprefix("reason:"): value
                    for key, value in stats.most_common()
                    if key.startswith("reason:")
                },
            )
            return count

    finally:
        await tsa_db.close()
