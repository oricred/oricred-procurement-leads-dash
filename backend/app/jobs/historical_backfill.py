from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select

from app.utils import parse_datetime

from app.clients import TSADatabase
from app.database import async_session
from app.models.award import Award
from app.models.award_ingestion_state import AwardIngestionState
from app.models.company import Company
from app.models.historical_ingestion_state import HistoricalIngestionState
from app.models.opportunity import Opportunity
from app.models.organization import Organization
from app.models.tender import Tender
from app.services.buyer_preference import compute_buyer_preference
from app.services.funding_suitability import compute_funding_suitability
from app.services.lead_scoring import refresh_lead_scoring
from app.workflow import WORKFLOW_STAGES

from app.jobs.award_check import (
    _award_api_id,
    _resolve_award_date,
    _sanitize,
    _upsert_awarded_company,
    _upsert_tender_for_award,
    AWARD_FIELDS,
    AWARD_INGEST_LIMIT,
    COMPANY_FIELDS,
    ORGANIZATION_FIELDS,
    TENDER_FIELDS,
)

logger = structlog.get_logger()

HISTORICAL_AWARD_CHUNK_DAYS = 90
HISTORICAL_AWARD_MAX_PAGES = 100


EARLIEST_SANE_YEAR = 2000


async def _find_earliest_award_date(tsa_db: TSADatabase) -> datetime | None:
    """Query the TSA DB for the earliest award_date among all awards.
    Skips sentinel dates (year < EARLIEST_SANE_YEAR) that are data-entry errors.
    """
    try:
        since = datetime(EARLIEST_SANE_YEAR, 1, 1)
        rows = await tsa_db.query_awards(
            filters={"since": since},
            fields=["award_date"],
            limit=1,
            direction="asc",
        )
        if rows and rows[0].get("award_date"):
            return parse_datetime(rows[0]["award_date"])
    except Exception as exc:
        logger.error("earliest_award_query_failed", error=str(exc))
    return datetime(EARLIEST_SANE_YEAR, 1, 1, tzinfo=timezone.utc)


async def _fetch_award_chunk(
    tsa_db: TSADatabase,
    since: datetime,
    until: datetime,
) -> list[dict[str, Any]]:
    """Fetch all awards in a date range. Handles pagination up to max pages."""
    raw_awards: list[dict[str, Any]] = []
    for page in range(HISTORICAL_AWARD_MAX_PAGES):
        batch = await tsa_db.query_awards(
            filters={
                "since": since.replace(tzinfo=None) if since.tzinfo else since,
                "until": until.replace(tzinfo=None) if until.tzinfo else until,
            },
            fields=AWARD_FIELDS,
            limit=AWARD_INGEST_LIMIT,
            offset=page * AWARD_INGEST_LIMIT,
            direction="asc",
        )
        raw_awards.extend(batch)
        if len(batch) < AWARD_INGEST_LIMIT:
            break
    else:
        logger.warning(
            "historical_award_page_limit_reached",
            pages=HISTORICAL_AWARD_MAX_PAGES,
            since=since.isoformat(),
            until=until.isoformat(),
        )
    return raw_awards


async def _load_related_data(
    tsa_db: TSADatabase,
    raw_awards: list[dict[str, Any]],
) -> tuple[dict[str, dict], dict[str, dict], dict[str, list[str]], set[str]]:
    """Batch-load tender metadata, company data, bidders, and collect unique org IDs."""
    tender_api_ids = list({str(raw["tender_id"]) for raw in raw_awards if raw.get("tender_id")})
    tender_by_api_id: dict[str, dict] = {}
    if tender_api_ids:
        try:
            raw_tenders = await tsa_db.query_tenders(
                filters={"ids": tender_api_ids},
                fields=TENDER_FIELDS,
                limit=max(len(tender_api_ids), 1),
            )
            tender_by_api_id = {str(t["id"]): t for t in raw_tenders if t.get("id")}
        except Exception as exc:
            logger.warning("historical_tender_context_query_failed", error=str(exc))

    company_by_name: dict[str, dict] = {}
    suppliers = list({raw.get("supplier_name") for raw in raw_awards if raw.get("supplier_name")})
    if suppliers:
        try:
            for company in await tsa_db.query_companies(
                filters={"names": suppliers}, fields=COMPANY_FIELDS,
            ):
                name = company.get("name", "")
                company_by_name[name] = company
                company_by_name[name.strip().lower()] = company
        except Exception as exc:
            logger.warning("historical_company_query_failed", error=str(exc))

    bidders_by_tender: dict[str, list[str]] = defaultdict(list)
    if tender_api_ids:
        try:
            for bidder in await tsa_db.query_bidders(tender_ids=tender_api_ids):
                if bidder.get("tender_id") and bidder.get("name"):
                    bidders_by_tender[str(bidder["tender_id"])].append(bidder["name"])
        except Exception as exc:
            logger.warning("historical_bidder_query_failed", error=str(exc))

    org_ids: set[str] = set()
    for raw in raw_awards:
        meta = tender_by_api_id.get(str(raw.get("tender_id")))
        if meta and meta.get("source_organization_id"):
            org_ids.add(str(meta["source_organization_id"]))

    return tender_by_api_id, company_by_name, bidders_by_tender, org_ids


async def _batch_upsert_organizations(
    db, tsa_db: TSADatabase, org_ids: set[str], now: datetime,
) -> None:
    """Upsert buyer organizations in sorted order to avoid deadlocks."""
    if not org_ids:
        return
    sorted_ids = sorted(org_ids)
    try:
        org_results = await tsa_db.query_organizations(
            filters={"ids": sorted_ids}, fields=ORGANIZATION_FIELDS,
        )
        org_map = {r["id"]: r for r in org_results if r.get("id")}
    except Exception as exc:
        logger.warning("historical_batch_org_query_failed", error=str(exc))
        return

    for org_id in sorted_ids:
        org_data = org_map.get(org_id)
        if not org_data:
            continue
        await db.merge(Organization(
            id=org_id,
            name=org_data.get("name", org_id),
            organization_type=org_data.get("organization_type"),
            contact_email=org_data.get("contact_email"),
            contact_phone=org_data.get("contact_phone"),
            contact_website=org_data.get("website"),
            contact_email_is_role_based=org_data.get("contact_email_is_role_based"),
            confidence_score=org_data.get("confidence_score"),
            raw_payload=_sanitize(org_data),
            last_refreshed_at=now,
        ))


async def _process_award_chunk(
    db,
    tsa_db: TSADatabase,
    raw_awards: list[dict[str, Any]],
    tender_by_api_id: dict[str, dict],
    company_by_name: dict[str, dict],
    bidders_by_tender: dict[str, list[str]],
    org_ids: set[str],
    now: datetime,
) -> tuple[int, int]:
    """Process a batch of awards: upsert tenders, companies, orgs, awards, opportunities.
    
    Returns (created_count, skipped_count).
    """
    await _batch_upsert_organizations(db, tsa_db, org_ids, now)

    created = 0
    skipped = 0

    for raw in raw_awards:
        tender = await _upsert_tender_for_award(db, raw, tender_by_api_id.get(str(raw.get("tender_id"))), now)
        if not tender:
            skipped += 1
            continue

        company = await _upsert_awarded_company(db, raw, company_by_name, now)
        supplier = raw.get("supplier_name") or "Unknown"

        award_api_id = _award_api_id(raw)
        award = (await db.execute(select(Award).where(Award.api_id == award_api_id))).scalar_one_or_none()
        if not award:
            award = Award(
                api_id=award_api_id,
                tender_id=tender.id,
                supplier_name=supplier,
                source="tenders_api",
                discovered_at=now,
            )
            db.add(award)
            await db.flush()
            created += 1
        else:
            skipped += 1

        award.tender_id = tender.id
        award.raw_payload = _sanitize(raw)
        award.supplier_name = supplier
        award.supplier_company_id = company.api_id
        award.amount = raw.get("amount")
        award.publication_date = parse_datetime(raw.get("publication_date"))
        award.source_created_at = parse_datetime(raw.get("created_at"))
        award.award_date = _resolve_award_date(
            raw.get("award_date"), award.source_created_at, award.discovered_at, now,
        )
        award.bee_level = raw.get("bee_level")
        award.bee_points = raw.get("bee_points")
        award.buyer_org_id = tender.buyer_org_id

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
        opp.related_bidders = [
            {"name": name, "inferred": False, "reason": "confirmed bidder"}
            for name in bidders_by_tender.get(tender.api_id, [])
            if name.lower() != supplier.lower()
        ] or None

    return created, skipped


async def backfill_historical_awards() -> int:
    """Backfill ALL historical tender awards from TSA DB, chunked by date.

    Walks backward from the current AwardIngestionState cursor to the earliest
    award in the TSA DB, processing in configurable date-windows. Skips email
    alerts, CRM sync, watchlist matching, and contact lookups.
    """
    tsa_db = TSADatabase()
    logger.info("job_started", job="backfill_historical_awards")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            state = await db.get(HistoricalIngestionState, "historical_awards")

            if state and state.status == "running":
                logger.warning("historical_backfill_already_running", resumed=False)
                return 0

            # Determine the upper bound: current incremental cursor
            inc_state = await db.get(AwardIngestionState, "tenders_sa")
            upper_bound = inc_state.latest_award_at if inc_state and inc_state.latest_award_at else now

            # If we have a saved state with progress, resume from there
            if state and state.current_lower_bound:
                since = state.current_lower_bound
                until = state.current_upper_bound if state.current_upper_bound else upper_bound
                logger.info("historical_backfill_resuming", since=since.isoformat(), until=until.isoformat())
            else:
                # Determine the lower bound: earliest award in TSA DB
                earliest = await _find_earliest_award_date(tsa_db)
                target = earliest if earliest else now - timedelta(days=365 * 20)

                # Initialize state
                if state:
                    state.target_lower_bound = target
                else:
                    state = HistoricalIngestionState(
                        job_name="historical_awards",
                        status="idle",
                        target_lower_bound=target,
                    )
                    db.add(state)

                since = upper_bound - timedelta(days=HISTORICAL_AWARD_CHUNK_DAYS)
                until = upper_bound

            state.status = "running"
            state.started_at = now
            await db.commit()

            total_processed = state.total_processed
            total_errors = state.errors

            while True:
                chunk_until = until
                chunk_since = max(since, state.target_lower_bound)

                if chunk_since >= chunk_until:
                    break  # nothing left to process

                logger.info(
                    "historical_backfill_chunk",
                    since=chunk_since.isoformat() if chunk_since else "null",
                    until=chunk_until.isoformat() if chunk_until else "null",
                )

                raw_awards = await _fetch_award_chunk(tsa_db, chunk_since, chunk_until)

                chunk_success = True
                if not raw_awards:
                    logger.info("historical_backfill_chunk_empty", since=chunk_since.isoformat())
                else:
                    tender_by_api_id, company_by_name, bidders_by_tender, org_ids = await _load_related_data(
                        tsa_db, raw_awards,
                    )

                    try:
                        created, skipped = await _process_award_chunk(
                            db, tsa_db, raw_awards,
                            tender_by_api_id, company_by_name, bidders_by_tender, org_ids, now,
                        )
                        total_processed += created
                        await db.commit()
                        logger.info(
                            "historical_backfill_chunk_done",
                            chunk_size=len(raw_awards), created=created, skipped=skipped,
                        )
                    except Exception as exc:
                        logger.error("historical_backfill_chunk_failed", error=str(exc))
                        await db.rollback()
                        total_errors += 1
                        chunk_success = False

                # Update progress state (on success or failure, to support resume)
                async with async_session() as update_db:
                    s = await update_db.get(HistoricalIngestionState, "historical_awards")
                    if s:
                        s.current_lower_bound = chunk_since
                        s.current_upper_bound = chunk_until
                        s.total_processed = total_processed
                        s.errors = total_errors
                        s.updated_at = now
                    await update_db.commit()

                # On failure, pause so next run can retry this chunk
                if not chunk_success:
                    async with async_session() as pause_db:
                        s = await pause_db.get(HistoricalIngestionState, "historical_awards")
                        if s:
                            s.status = "idle"
                        await pause_db.commit()
                    logger.info("historical_backfill_paused", chunk_since=chunk_since.isoformat())
                    return total_processed

                # Move to next chunk (walk backward)
                until = chunk_since
                since = until - timedelta(days=HISTORICAL_AWARD_CHUNK_DAYS)

                if since < state.target_lower_bound:
                    # One more iteration covers the final truncated chunk
                    # (since will be clamped to target_lower_bound by max() above)
                    continue

            # Mark as completed
            async with async_session() as update_db:
                s = await update_db.get(HistoricalIngestionState, "historical_awards")
                if s:
                    s.status = "completed"
                    s.updated_at = datetime.now(timezone.utc)
                await update_db.commit()

            logger.info(
                "historical_backfill_complete",
                total_processed=total_processed,
                total_errors=total_errors,
            )
            return total_processed

    finally:
        await tsa_db.close()


async def backfill_historical_tenders() -> int:
    """Backfill full tender data for stubs created during historical award ingestion.
    
    Finds tenders with NULL province (the stub marker) and resolves them from TSA DB.
    Reuses the same logic as tender_backfill.backfill_stub_tenders().
    """
    from app.jobs.tender_backfill import backfill_stub_tenders
    return await backfill_stub_tenders()
