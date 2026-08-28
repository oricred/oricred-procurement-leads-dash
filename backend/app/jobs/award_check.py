import hashlib
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import or_, select

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
from app.models.award import Award
from app.models.award_ingestion_state import AwardIngestionState
from app.models.company import Company
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.past_due import PastDueQueue
from app.models.tender import Tender
from app.models.watchlist import WatchlistItem
from app.services.admin_config import get_config
from app.services.buyer_preference import compute_buyer_preference
from app.services.contact_enrichment import RECOVERABLE
from app.services.crm.sync import push_opportunity_to_crm
from app.services.email_alert import EmailAlertService
from app.services.funding_suitability import compute_funding_suitability
from app.services.lead_scoring import refresh_lead_scoring
from app.services.lead_service import (
    retry_contact_lookup_for_opportunity,
    retry_new_lead_contact_lookups,
)
from app.services.text_utils import best_title
from app.workflow import WORKFLOW_STAGES

logger = structlog.get_logger()

AWARD_FIELDS = [
    "id", "tender_id", "supplier_name", "amount", "award_date",
    "created_at", "bee_level", "bee_points", "supplier_canonical_id",
]
TENDER_FIELDS = [
    "id", "tender_id", "title", "description", "estimated_value", "province",
    "category_id", "closing_date", "source_organization_id",
    "source_organization", "type", "publication_date",
    "ai_title_enriched",
]
COMPANY_FIELDS = [
    "id", "name", "registration_number", "bbbee_level",
    "contact_email", "contact_phone", "website",
]
ORGANIZATION_FIELDS = [
    "id", "name", "organization_type", "contact_email", "contact_phone",
    "website", "confidence_score", "contact_email_is_role_based",
]

# Award publication may be delayed or corrected by a source. Re-reading this
# window makes the ingestion idempotent while keeping the scheduled query bounded.
AWARD_INGEST_LOOKBACK_DAYS = 30
# Every run re-reads this much already-seen history, so a late-published award
# cannot fall through the boundary between two runs.
AWARD_INGEST_OVERLAP_DAYS = 3
AWARD_INGEST_LIMIT = 5_000
AWARD_INGEST_MAX_PAGES = 20

# Marker stored on awards.date_source. Only "source" means the date came from
# Tenders-SA; anything else was synthesised and stays in the repair scan.
DATE_SOURCE_SOURCE = "source"
DATE_SOURCE_SYNTHESISED = "synthesised"
# Caps one nightly repair run so the job cannot grow unbounded with the table.
REPAIR_BATCH_SIZE = 5_000


def _supplier_fallback_api_id(supplier: str) -> str:
    digest = hashlib.sha1(supplier.strip().lower().encode("utf-8")).hexdigest()[:32]
    return f"award:{digest}"


def _award_api_id(raw: dict) -> str:
    if raw.get("id"):
        return str(raw["id"])
    identity = "|".join(str(raw.get(key) or "") for key in ("tender_id", "supplier_name", "award_date", "amount"))
    return f"award:{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:32]}"


@dataclass(frozen=True)
class ResolvedAwardDate:
    """An award date and whether we actually read it from the source.

    `from_source` exists to keep two different jobs honest about the same
    number. The award date is a business value that must never be NULL, so the
    resolver synthesises one when the source has nothing usable. The ingestion
    cursor is a sync value that must never move past a date we have confirmed.
    Feeding a synthesised date into the cursor pushes it to today and silently
    skips every award published afterwards with an older date — see
    docs/specifications/remediation-03-ingestion-correctness.md section 1.
    """

    value: datetime
    from_source: bool


def _as_aware(value: datetime | None) -> datetime | None:
    """Treat a naive datetime as UTC.

    Values reach the resolver from two sources: parse_datetime, which always
    returns an aware datetime, and the database. PostgreSQL round-trips
    DateTime(timezone=True) as aware; SQLite discards the offset and hands back
    a naive value. Comparing the two raises, so normalise at the boundary.
    """
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _resolve_award_date(
    raw_date: Any,
    source_created_at: datetime | None,
    discovered_at: datetime,
    now: datetime,
) -> ResolvedAwardDate:
    """Resolve award date. Never returns None.

    Priority:
    1. Raw date from source — if it parses and is sane, use as-is  (from_source)
    2. Source created_at — the full timestamp from TSA DB           (from_source)
    3. discovered_at — when we first saw the record                 (synthesised)
    """
    source_created_at = _as_aware(source_created_at)
    discovered_at = _as_aware(discovered_at) or now
    now = _as_aware(now) or now

    dt = parse_datetime(raw_date)
    if dt is not None and dt <= discovered_at:
        return ResolvedAwardDate(dt, from_source=True)

    if source_created_at is not None and source_created_at <= now:
        return ResolvedAwardDate(source_created_at, from_source=True)

    return ResolvedAwardDate(
        discovered_at if discovered_at <= now else now, from_source=False
    )


@dataclass
class IngestCache:
    """Local rows this batch may touch, loaded once up front.

    The loop issued a company lookup, an award lookup, a watchlist lookup, an
    opportunity lookup and up to two tender lookups per award — roughly 30,000
    queries for a 5,000-award page.

    Rows created during the loop are written back here, so a second award for
    the same tender or company in the same batch reuses the row rather than
    inserting a duplicate.
    """

    tenders: dict[str, Tender]
    companies: dict[str, Company]
    awards: dict[str, Award]
    watches: dict[str, WatchlistItem]
    opportunity_award_ids: set[str]


async def _preload(db, raw_awards: list[dict], tender_by_api_id: dict) -> IngestCache:
    """Load the local rows this batch could touch, keyed for O(1) lookup."""
    tender_keys: set[str] = set()
    for raw in raw_awards:
        row_uuid = str(raw.get("tender_id") or "")
        if row_uuid:
            tender_keys.add(row_uuid)
            reference = (tender_by_api_id.get(row_uuid) or {}).get("tender_id")
            if reference:
                tender_keys.add(str(reference))

    award_api_ids = {_award_api_id(raw) for raw in raw_awards}
    supplier_ids = {
        str(raw["supplier_canonical_id"]) for raw in raw_awards if raw.get("supplier_canonical_id")
    }
    supplier_ids |= {
        _supplier_fallback_api_id(raw.get("supplier_name") or "Unknown") for raw in raw_awards
    }

    tenders: dict[str, Tender] = {}
    if tender_keys:
        for tender in (
            await db.execute(select(Tender).where(Tender.api_id.in_(tender_keys)))
        ).scalars():
            tenders[tender.api_id] = tender

    awards: dict[str, Award] = {}
    if award_api_ids:
        for award in (
            await db.execute(select(Award).where(Award.api_id.in_(award_api_ids)))
        ).scalars():
            awards[award.api_id] = award

    companies: dict[str, Company] = {}
    if supplier_ids:
        for company in (
            await db.execute(select(Company).where(Company.api_id.in_(supplier_ids)))
        ).scalars():
            companies[company.api_id] = company

    tender_ids = [t.id for t in tenders.values()]
    watches: dict[str, WatchlistItem] = {}
    opportunity_award_ids: set[str] = set()
    if tender_ids:
        for watch in (
            await db.execute(
                select(WatchlistItem).where(
                    WatchlistItem.tender_id.in_(tender_ids),
                    WatchlistItem.status == "watching",
                )
            )
        ).scalars():
            watches[watch.tender_id] = watch
    if awards:
        opportunity_award_ids = set(
            (
                await db.execute(
                    select(Opportunity.award_id).where(
                        Opportunity.award_id.in_([a.id for a in awards.values()])
                    )
                )
            ).scalars()
        )

    return IngestCache(tenders, companies, awards, watches, opportunity_award_ids)


async def _upsert_awarded_company(db, raw: dict, company_by_name: dict[str, dict], now: datetime, cache: IngestCache) -> Company:
    supplier = raw.get("supplier_name") or "Unknown"
    co_data = company_by_name.get(supplier) or company_by_name.get(supplier.strip().lower()) or {}
    api_id = co_data.get("id") or raw.get("supplier_canonical_id") or _supplier_fallback_api_id(supplier)

    company = cache.companies.get(api_id)
    if not company:
        company = Company(api_id=api_id, name=co_data.get("name") or supplier)
        db.add(company)
        await db.flush()
        cache.companies[api_id] = company

    company.name = co_data.get("name") or supplier
    company.bee_level = co_data.get("bbbee_level") or raw.get("bee_level") or company.bee_level
    company.registration_number = co_data.get("registration_number") or company.registration_number
    company.raw_payload = _sanitize(co_data) or {
        "source": "award",
        "award_id": raw.get("id"),
        "supplier_canonical_id": raw.get("supplier_canonical_id"),
    }
    company.last_refreshed_at = now
    return company


async def _upsert_tender_for_award(db, raw: dict, metadata: dict | None, now: datetime, cache: IngestCache) -> Tender | None:
    """Ensure every imported award has local tender context without gating ingestion."""
    award_tender_id = raw.get("tender_id")
    if not award_tender_id:
        logger.warning("award_without_tender_id", award_id=raw.get("id"))
        return None

    metadata = metadata or {}
    biz_tender_id = metadata.get("tender_id")
    buyer_org_id = metadata.get("source_organization_id")

    # Business ID first (matching the discovery job's api_id scheme), then the
    # TSA row UUID. Both were separate SELECTs per award.
    tender = None
    if biz_tender_id:
        tender = cache.tenders.get(str(biz_tender_id))
    if not tender:
        tender = cache.tenders.get(str(award_tender_id))

    if not tender:
        api_id = biz_tender_id or award_tender_id
        tender_title = best_title(metadata) if metadata else f"Awarded tender {api_id}"
        tender = Tender(
            api_id=api_id,
            raw_payload=_sanitize(metadata) or {"source": "award_ingestion", "award_id": raw.get("id"), "tender_uuid": award_tender_id},
            title=tender_title,
            description=metadata.get("description"),
            estimated_value=metadata.get("estimated_value"),
            province=metadata.get("province"),
            category_id=metadata.get("category_id"),
            closing_date=parse_datetime(metadata.get("closing_date")),
            buyer_org_id=buyer_org_id,
            tender_type=metadata.get("type"),
            # parse_datetime, matching closing_date above and the update branch
            # below. Passing the raw value here skipped the MAX_VALID_YEAR guard
            # and fails outright whenever the source hands back a string.
            published_at=parse_datetime(metadata.get("publication_date")),
            discovered_at=now,
        )
        db.add(tender)
        await db.flush()
        cache.tenders[tender.api_id] = tender
    elif metadata:
        tender.raw_payload = _sanitize(metadata)
        tender.title = best_title(metadata) or tender.title
        tender.description = metadata.get("description") or tender.description
        tender.estimated_value = metadata.get("estimated_value") or tender.estimated_value
        tender.province = metadata.get("province") or tender.province
        tender.category_id = metadata.get("category_id") or tender.category_id
        tender.closing_date = parse_datetime(metadata.get("closing_date")) or tender.closing_date
        tender.buyer_org_id = buyer_org_id or tender.buyer_org_id
        tender.tender_type = metadata.get("type") or tender.tender_type
        tender.published_at = parse_datetime(metadata.get("publication_date")) or tender.published_at
    return tender


async def _sync_buyer_organizations(
    db, tsa_db: TSADatabase, org_ids: set[str], now: datetime
) -> None:
    """Fetch every buyer organisation for this batch in one query.

    This ran per award, so a 5,000-award page made 5,000 round trips to the
    external read-only database for an organisation set that is usually a few
    dozen distinct values repeated over and over.
    """
    if not org_ids:
        return
    try:
        rows = await tsa_db.query_organizations(
            filters={"ids": sorted(org_ids)},
            fields=ORGANIZATION_FIELDS,
            limit=max(len(org_ids), 1),
        )
    except RECOVERABLE as exc:
        logger.warning("buyer_org_batch_failed", count=len(org_ids), error=str(exc))
        return

    for org in rows:
        org_id = org.get("id")
        if not org_id:
            continue
        await db.merge(Organization(
            id=org_id,
            name=org.get("name") or org_id,
            organization_type=org.get("organization_type"),
            contact_email=org.get("contact_email"),
            contact_phone=org.get("contact_phone"),
            contact_website=org.get("website"),
            contact_email_is_role_based=org.get("contact_email_is_role_based"),
            confidence_score=org.get("confidence_score"),
            raw_payload=_sanitize(org),
            last_refreshed_at=now,
        ))


async def _mark_overdue_watches(db, email: EmailAlertService, now: datetime) -> None:
    rows = await db.execute(
        select(WatchlistItem, Tender)
        .join(Tender, WatchlistItem.tender_id == Tender.id)
        .where(
            WatchlistItem.status == "watching",
            WatchlistItem.expected_window_end.isnot(None),
            WatchlistItem.expected_window_end < now,
        )
    )
    for watch, tender in rows.all():
        has_award = await db.scalar(select(Award.id).where(Award.tender_id == tender.id).limit(1))
        if has_award:
            watch.status = "awarded"
            watch.awarded_at = now
            continue
        watch.status = "past_due"
        watch.past_due_at = now
        existing = await db.execute(select(PastDueQueue).where(PastDueQueue.tender_id == tender.id))
        if existing.scalar_one_or_none():
            continue
        db.add(PastDueQueue(tender_id=tender.id, entered_queue_at=now))
        await email.queue(
            "past_due", tender_title=tender.title,
            buyer_org=tender.buyer_org_id or "", category=tender.category_id or "",
            window_start=str(watch.expected_window_start), window_end=str(watch.expected_window_end),
            days_overdue=str((now - watch.expected_window_end).days), dashboard_url="/watchlist",
        )


async def check_awards_for_watching(backfill: bool = False):
    """Ingest Tenders-SA awards regardless of watchlist membership.

    A watchlist match only updates that tender's monitoring state; it never filters
    the award feed or prevents an awarded supplier from becoming a lead.
    """
    tsa_db = TSADatabase()
    logger.info("job_started", job="ingest_awards")

    try:
        async with async_session() as db:
            # Recipients and per-event toggles live in Admin -> Notifications.
            email = await EmailAlertService.from_config(db)
            now = datetime.now(timezone.utc)
            new_opportunity_ids: list[str] = []
            # Only dates we actually read from Tenders-SA. A synthesised date
            # would push the cursor to today and skip everything published
            # afterwards with an older award_date.
            source_backed_timestamps: list[datetime] = []
            synthesised_dates = 0
            state = await db.get(AwardIngestionState, "tenders_sa")
            if backfill or not (state and state.latest_award_at):
                since = now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS)
            else:
                # Re-read a fixed window on every run. The upsert path is
                # idempotent by api_id, and the source backfills late records.
                since = _as_aware(state.latest_award_at) - timedelta(days=AWARD_INGEST_OVERLAP_DAYS)
            raw_awards: list[dict] = []
            try:
                for page in range(AWARD_INGEST_MAX_PAGES):
                    batch = await tsa_db.query_awards(
                        filters={"since": since.replace(tzinfo=None) if isinstance(since, datetime) and since.tzinfo else since},
                        fields=AWARD_FIELDS,
                        limit=AWARD_INGEST_LIMIT,
                        offset=page * AWARD_INGEST_LIMIT,
                        direction="asc",
                    )
                    raw_awards.extend(batch)
                    if len(batch) < AWARD_INGEST_LIMIT:
                        break
                else:
                    logger.warning("award_ingestion_page_limit_reached", pages=AWARD_INGEST_MAX_PAGES, since=since.isoformat())
            except Exception as exc:
                logger.error("award_ingestion_query_failed", error=str(exc))
                raw_awards = []

            tender_api_ids = list({str(raw["tender_id"]) for raw in raw_awards if raw.get("tender_id")})
            tender_by_api_id: dict[str, dict] = {}
            if tender_api_ids:
                try:
                    raw_tenders = await tsa_db.query_tenders(
                        filters={"ids": tender_api_ids}, fields=TENDER_FIELDS,
                        limit=max(len(tender_api_ids), 1),
                    )
                    tender_by_api_id = {str(tender["id"]): tender for tender in raw_tenders if tender.get("id")}
                except Exception as exc:
                    logger.warning("award_tender_context_query_failed", error=str(exc))

            company_by_name: dict[str, dict] = {}
            suppliers = list({raw.get("supplier_name") for raw in raw_awards if raw.get("supplier_name")})
            if suppliers:
                try:
                    for company in await tsa_db.query_companies(filters={"names": suppliers}, fields=COMPANY_FIELDS):
                        name = company.get("name", "")
                        company_by_name[name] = company
                        company_by_name[name.strip().lower()] = company
                except Exception as exc:
                    logger.warning("batch_company_query_failed", error=str(exc))

            bidders_by_tender: dict[str, list[str]] = defaultdict(list)
            if tender_api_ids:
                try:
                    for bidder in await tsa_db.query_bidders(tender_ids=tender_api_ids):
                        if bidder.get("tender_id") and bidder.get("name"):
                            bidders_by_tender[str(bidder["tender_id"])].append(bidder["name"])
                except Exception as exc:
                    logger.warning("batch_bidder_query_failed", error=str(exc))

            # One query per table instead of one per award, and one remote call
            # for every buyer organisation instead of one per award.
            # The scoring config is identical for every opportunity in a run;
            # loading it per lead cost one query each.
            buyer_preference_config = (
                await get_config("admin_scoring", db)
            ).get("buyer_preference", {})

            cache = await _preload(db, raw_awards, tender_by_api_id)
            await _sync_buyer_organizations(
                db,
                tsa_db,
                {
                    str(meta["source_organization_id"])
                    for meta in tender_by_api_id.values()
                    if meta.get("source_organization_id")
                },
                now,
            )

            for raw in raw_awards:
                tender = await _upsert_tender_for_award(
                    db, raw, tender_by_api_id.get(str(raw.get("tender_id"))), now, cache
                )
                if not tender:
                    continue
                company = await _upsert_awarded_company(db, raw, company_by_name, now, cache)
                supplier = raw.get("supplier_name", "Unknown")

                award_api_id = _award_api_id(raw)
                award = cache.awards.get(award_api_id)
                if not award:
                    award = Award(api_id=award_api_id, tender_id=tender.id, supplier_name=supplier, source="tenders_api", discovered_at=now)
                    db.add(award)
                    await db.flush()
                    cache.awards[award_api_id] = award
                award.tender_id = tender.id
                award.raw_payload = _sanitize(raw)
                award.supplier_name = supplier
                award.supplier_company_id = company.api_id
                award.amount = raw.get("amount")
                award.publication_date = parse_datetime(raw.get("publication_date"))
                award.source_created_at = parse_datetime(raw.get("created_at"))
                resolved = _resolve_award_date(
                    raw.get("award_date"), award.source_created_at, award.discovered_at, now,
                )
                award.award_date = resolved.value
                award.date_source = (
                    DATE_SOURCE_SOURCE if resolved.from_source else DATE_SOURCE_SYNTHESISED
                )
                award.bee_level = raw.get("bee_level")
                award.bee_points = raw.get("bee_points")
                award.buyer_org_id = tender.buyer_org_id
                if resolved.from_source:
                    source_backed_timestamps.append(resolved.value)
                else:
                    synthesised_dates += 1

                # Watchlist matching happens after the Tenders-SA award was stored.
                watch = cache.watches.pop(tender.id, None)
                if watch:
                    watch.status = "awarded"
                    watch.awarded_at = now

                if award.id in cache.opportunity_award_ids:
                    continue
                cache.opportunity_award_ids.add(award.id)
                opp = Opportunity(
                    tender_id=tender.id, award_id=award.id, company_id=company.id,
                    kanban_stage=WORKFLOW_STAGES[0], contact_sufficiency="none", risk_flag="green",
                )
                db.add(opp)
                await db.flush()
                opp.buyer_preference_score = await compute_buyer_preference(
                    str(opp.id), db, config=buyer_preference_config, opp=opp, tender=tender
                )
                opp.funding_suitability = await compute_funding_suitability(
                    company.id, db, company=company
                )
                await refresh_lead_scoring(opp, db, tender=tender, award=award, company=company, contacts=[])
                opp.related_bidders = [
                    {"name": name, "inferred": False, "reason": "confirmed bidder"}
                    # Keyed by the Tenders-SA row UUID (a.tender_id == t.id),
                    # which is what query_bidders returned. tender.api_id holds
                    # the business reference (t.tender_id) and never matches.
                    for name in bidders_by_tender.get(str(raw.get("tender_id") or ""), [])
                    if name.lower() != supplier.lower()
                ] or None
                new_opportunity_ids.append(str(opp.id))
                await email.queue(
                    "award_detected", company_name=supplier,
                    tender_title=tender.title, supplier_name=supplier,
                    amount=float(raw.get("amount", 0) or 0), award_date=str(raw.get("award_date", "")),
                    dashboard_url="/opportunities/" + str(opp.id),
                )

            await _mark_overdue_watches(db, email, now)
            delivered = await email.flush()
            if source_backed_timestamps:
                # Never past now, even if the source hands us a future date.
                latest_award_at = min(max(source_backed_timestamps), now)
                if not state:
                    state = AwardIngestionState(source="tenders_sa", latest_award_at=latest_award_at)
                    db.add(state)
                elif not state.latest_award_at or latest_award_at > _as_aware(state.latest_award_at):
                    state.latest_award_at = latest_award_at
            elif raw_awards:
                # Rows ingested but nothing to advance on: every date was
                # synthesised. Visible rather than silently stalling.
                logger.warning(
                    "award_cursor_not_advanced",
                    awards_seen=len(raw_awards),
                    synthesised_dates=synthesised_dates,
                )
            await db.commit()

            contacts_added = 0
            lookup_errors = 0
            for opportunity_id in new_opportunity_ids:
                try:
                    async with async_session() as lookup_db:
                        _, lookup = await retry_contact_lookup_for_opportunity(
                            opportunity_id, lookup_db, tsa_db
                        )
                        contacts_added += lookup.added
                        lookup_errors += lookup.errors
                    await push_opportunity_to_crm(opportunity_id)
                except RECOVERABLE as exc:
                    lookup_errors += 1
                    logger.warning("lead_post_create_sync_failed", opportunity_id=opportunity_id, error=str(exc))

            retry_processed = await retry_new_lead_contact_lookups(limit=100)
            logger.info(
                "award_ingestion_complete", source="tenders_sa", since=since.isoformat(), awards_checked=len(raw_awards),
                leads_created=len(new_opportunity_ids), contacts_added=contacts_added,
                lookup_errors=lookup_errors, alerts_delivered=delivered,
                contact_retry_processed=retry_processed,
            )
            return len(raw_awards)
    finally:
        await tsa_db.close()


async def find_corrupted_award_dates(db=None) -> list[Award]:
    """Awards whose date is missing, in the future, or was synthesised.

    Bounded by design. The previous implementation selected every healthy award
    with a payload, materialised all of them, and filtered in Python by
    re-parsing the raw JSON year — a full scan of a table that only grows,
    running nightly.

    date_source records how each award's date was resolved, so a repaired row
    drops out of this scan permanently and the working set shrinks rather than
    grows. NULL covers rows written before the column existed; the one-off
    backfill in app.cli clears those.
    """
    if db is None:
        async with async_session() as s:
            return await find_corrupted_award_dates(s)
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(Award)
        .where(
            or_(
                Award.award_date.is_(None),
                Award.award_date > now,
                Award.date_source.is_(None),
                Award.date_source != DATE_SOURCE_SOURCE,
            )
        )
        .order_by(Award.discovered_at.desc())
        .limit(REPAIR_BATCH_SIZE)
    )
    return list(result.scalars().all())


async def fix_corrupted_award_dates() -> int:
    """Repair awards with a NULL or obviously-wrong award_date.

    Re-parses the raw payload through _resolve_award_date, which prefers the
    source date, falls back to the source's created_at, and finally to our own
    discovery timestamp. Returns the count of awards whose date actually
    changed.
    """

    async with async_session() as db:
        rows = await find_corrupted_award_dates(db)
        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        fixed = 0
        for award in rows:
            original = award.award_date

            recovered = _resolve_award_date(
                award.raw_payload.get("award_date") if award.raw_payload else None,
                award.source_created_at, award.discovered_at, now,
            )
            award.date_source = (
                DATE_SOURCE_SOURCE if recovered.from_source else DATE_SOURCE_SYNTHESISED
            )
            if recovered.value != original:
                award.award_date = recovered.value
                fixed += 1
                logger.info(
                    "award_date_recovered",
                    award_id=award.id,
                    original=str(original) if original else "NULL",
                    resolved=recovered.value.isoformat(),
                    from_source=recovered.from_source,
                )

        await db.commit()
        logger.info("corrupted_award_dates_fixed", total=len(rows), fixed=fixed)
        return fixed


async def backfill_recent_awards() -> int:
    """Admin-triggered recovery path: re-ingest the full current 30-day window."""
    return await check_awards_for_watching(backfill=True)
