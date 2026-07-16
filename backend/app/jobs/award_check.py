import hashlib
from collections import defaultdict
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import or_, select


from app.utils import MAX_VALID_YEAR, parse_datetime


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
from app.services.buyer_preference import compute_buyer_preference
from app.services.crm.sync import push_opportunity_to_crm
from app.services.email_alert import EmailAlertService
from app.services.funding_suitability import compute_funding_suitability
from app.services.lead_scoring import refresh_lead_scoring
from app.services.lead_service import retry_contact_lookup_for_opportunity, retry_new_lead_contact_lookups
from app.services.text_utils import best_title
from app.workflow import WORKFLOW_STAGES

logger = structlog.get_logger()

AWARD_FIELDS = [
    "id", "tender_id", "supplier_name", "amount", "award_date",
    "publication_date", "bee_level", "bee_points", "supplier_canonical_id",
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
AWARD_INGEST_LIMIT = 5_000
AWARD_INGEST_MAX_PAGES = 20


def _supplier_fallback_api_id(supplier: str) -> str:
    digest = hashlib.sha1(supplier.strip().lower().encode("utf-8")).hexdigest()[:32]
    return f"award:{digest}"


def _award_api_id(raw: dict) -> str:
    if raw.get("id"):
        return str(raw["id"])
    identity = "|".join(str(raw.get(key) or "") for key in ("tender_id", "supplier_name", "award_date", "amount"))
    return f"award:{hashlib.sha1(identity.encode('utf-8')).hexdigest()[:32]}"


def _parse_lenient(raw_date: Any) -> datetime | None:
    """Parse a date without the MAX_VALID_YEAR guard, for year-correction recovery."""
    if raw_date is None:
        return None
    if isinstance(raw_date, datetime):
        return raw_date if raw_date.tzinfo else raw_date.replace(tzinfo=timezone.utc)
    if isinstance(raw_date, str):
        try:
            dt = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _resolve_award_date(
    raw_date: Any,
    award_publication_date: datetime | None,
    tender_published_at: datetime | None,
    tender_closing_date: datetime | None,
    discovered_at: datetime,
    now: datetime,
) -> datetime:
    """Resolve the best possible award date. Never returns None.

    The award_date is the core business value — a missing date makes the
    record useless for client workflows (contacting awarded suppliers to
    propose funding). This aggressively recovers a usable date:

    1. If raw_date parses to a valid, sane date → use as-is
    2. If raw year is borderline (2026-2027) → fix year using reference
       years preserving month/day; if corrected date violates timeline
       → fall through to step 3
    3. If raw year is clearly corrupt (>2027, month/day unreliable) →
       skip year correction, use best available proxy
    4. Fallback to best available proxy (pub_date → tender dates → discovered_at)
    """
    stricter = parse_datetime(raw_date)
    lenient = _parse_lenient(raw_date)

    # Reference years in priority order (deduped)
    ref_years: list[int] = []
    for ref in (award_publication_date, tender_published_at, tender_closing_date):
        if ref is not None and ref.year <= now.year:
            ref_years.append(ref.year)
    ref_years.append(discovered_at.year)
    if discovered_at.year - 1 >= 2000:
        ref_years.append(discovered_at.year - 1)
    ref_years = list(dict.fromkeys(ref_years))

    # Step 1 — direct use if date is already valid
    if stricter is not None and stricter <= discovered_at:
        lower = tender_published_at or tender_closing_date
        upper = award_publication_date
        if (lower is None or stricter >= lower) and (upper is None or stricter <= upper):
            return stricter

    # Step 2 — year correction only for borderline years (month/day plausibly real)
    if lenient is not None and lenient.year <= MAX_VALID_YEAR:
        for ref_year in ref_years:
            try:
                corrected = lenient.replace(year=ref_year)
            except (ValueError, OverflowError):
                continue
            if corrected <= discovered_at:
                lower = tender_published_at or tender_closing_date
                if lower is None or corrected >= lower:
                    if award_publication_date is None or corrected <= award_publication_date:
                        if stricter is None or corrected != stricter:
                            logger.warning(
                                "award_date_resolved",
                                original=lenient.isoformat(), resolved=corrected.isoformat(),
                                ref_year=ref_year,
                            )
                        return corrected
                    if award_publication_date <= discovered_at:
                        logger.warning(
                            "award_date_month_wrong_using_pub",
                            original=lenient.isoformat(), corrected=corrected.isoformat(),
                            publication_date=award_publication_date.isoformat(),
                        )
                        return award_publication_date

    # Step 3 — fallback to best available proxy
    for candidate in (award_publication_date, tender_published_at, tender_closing_date, discovered_at):
        if candidate is not None and candidate <= now:
            if candidate is not discovered_at:
                logger.warning("award_date_fallback", candidate=candidate.isoformat())
            return candidate

    return now


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
    company.raw_payload = _sanitize(co_data) or {
        "source": "award",
        "award_id": raw.get("id"),
        "supplier_canonical_id": raw.get("supplier_canonical_id"),
    }
    company.last_refreshed_at = now
    return company


async def _upsert_tender_for_award(db, raw: dict, metadata: dict | None, now: datetime) -> Tender | None:
    """Ensure every imported award has local tender context without gating ingestion."""
    award_tender_id = raw.get("tender_id")
    if not award_tender_id:
        logger.warning("award_without_tender_id", award_id=raw.get("id"))
        return None

    metadata = metadata or {}
    biz_tender_id = metadata.get("tender_id")
    buyer_org_id = metadata.get("source_organization_id")

    tender = None
    # Look up by business ID first (matching discovery job's api_id scheme)
    if biz_tender_id:
        tender = (await db.execute(select(Tender).where(Tender.api_id == biz_tender_id))).scalar_one_or_none()
    if not tender:
        # Fallback: look up by UUID (the award's tender_id = TSA DB t.id)
        tender = (await db.execute(select(Tender).where(Tender.api_id == award_tender_id))).scalar_one_or_none()

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
            published_at=metadata.get("publication_date"),
            discovered_at=now,
        )
        db.add(tender)
        await db.flush()
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


async def _upsert_buyer_organization(db, tsa_db: TSADatabase, tender: Tender, now: datetime) -> None:
    if not tender.buyer_org_id:
        return
    try:
        org_results = await tsa_db.query_organizations(
            filters={"ids": [tender.buyer_org_id]}, fields=ORGANIZATION_FIELDS,
        )
        if not org_results:
            return
        org = org_results[0]
        await db.merge(Organization(
            id=tender.buyer_org_id,
            name=org.get("name", tender.buyer_org_id),
            organization_type=org.get("organization_type"),
            contact_email=org.get("contact_email"),
            contact_phone=org.get("contact_phone"),
            contact_website=org.get("website"),
            contact_email_is_role_based=org.get("contact_email_is_role_based"),
            confidence_score=org.get("confidence_score"),
            raw_payload=_sanitize(org),
            last_refreshed_at=now,
        ))
    except Exception as exc:
        logger.warning("buyer_org_upsert_failed", tender_id=tender.api_id, error=str(exc))


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
        await email.send(
            "past_due", "ops@oricred.com", tender_title=tender.title,
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
    email = EmailAlertService()
    logger.info("job_started", job="ingest_awards")

    try:
        async with async_session() as db:
            now = datetime.now(timezone.utc)
            new_opportunity_ids: list[str] = []
            ingested_award_timestamps: list[datetime] = []
            state = await db.get(AwardIngestionState, "tenders_sa")
            since = now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS) if backfill else (state.latest_award_at if state and state.latest_award_at else now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS))
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

            for raw in raw_awards:
                tender = await _upsert_tender_for_award(db, raw, tender_by_api_id.get(str(raw.get("tender_id"))), now)
                if not tender:
                    continue
                company = await _upsert_awarded_company(db, raw, company_by_name, now)
                supplier = raw.get("supplier_name", "Unknown")
                await _upsert_buyer_organization(db, tsa_db, tender, now)

                award_api_id = _award_api_id(raw)
                award = (await db.execute(select(Award).where(Award.api_id == award_api_id))).scalar_one_or_none()
                if not award:
                    award = Award(api_id=award_api_id, tender_id=tender.id, supplier_name=supplier, source="tenders_api", discovered_at=now)
                    db.add(award)
                    await db.flush()
                award.tender_id = tender.id
                award.raw_payload = _sanitize(raw)
                award.supplier_name = supplier
                award.supplier_company_id = company.api_id
                award.amount = raw.get("amount")
                award.publication_date = parse_datetime(raw.get("publication_date"))
                award.award_date = _resolve_award_date(
                    raw.get("award_date"), award.publication_date, tender.published_at, tender.closing_date,
                    award.discovered_at, now,
                )
                award.bee_level = raw.get("bee_level")
                award.bee_points = raw.get("bee_points")
                award.buyer_org_id = tender.buyer_org_id
                timestamp = award.award_date
                if timestamp:
                    ingested_award_timestamps.append(timestamp)

                # Watchlist matching happens after the Tenders-SA award was stored.
                watch = (await db.execute(select(WatchlistItem).where(WatchlistItem.tender_id == tender.id, WatchlistItem.status == "watching"))).scalar_one_or_none()
                if watch:
                    watch.status = "awarded"
                    watch.awarded_at = now

                existing_opp = await db.execute(select(Opportunity).where(Opportunity.award_id == award.id))
                if existing_opp.scalar_one_or_none():
                    continue
                opp = Opportunity(
                    tender_id=tender.id, award_id=award.id, company_id=company.id,
                    kanban_stage=WORKFLOW_STAGES[0], contact_sufficiency="none", risk_flag="green",
                )
                db.add(opp)
                await db.flush()
                opp.buyer_preference_score = await compute_buyer_preference(str(opp.id), db)
                opp.funding_suitability = await compute_funding_suitability(company.id, db)
                await refresh_lead_scoring(opp, db, tender=tender, award=award, company=company, contacts=[])
                opp.related_bidders = [
                    {"name": name, "inferred": False, "reason": "confirmed bidder"}
                    for name in bidders_by_tender.get(tender.api_id, []) if name.lower() != supplier.lower()
                ] or None
                new_opportunity_ids.append(str(opp.id))
                await email.send(
                    "award_detected", "ops@oricred.com", company_name=supplier,
                    tender_title=tender.title, supplier_name=supplier,
                    amount=float(raw.get("amount", 0) or 0), award_date=str(raw.get("award_date", "")),
                    dashboard_url="/opportunities/" + str(opp.id),
                )

            await _mark_overdue_watches(db, email, now)
            if ingested_award_timestamps:
                valid_timestamps = [ts for ts in ingested_award_timestamps if ts <= now]
                if valid_timestamps:
                    latest_award_at = max(valid_timestamps)
                    if not state:
                        state = AwardIngestionState(source="tenders_sa", latest_award_at=latest_award_at)
                        db.add(state)
                    elif not state.latest_award_at or latest_award_at > state.latest_award_at:
                        state.latest_award_at = latest_award_at
                else:
                    logger.warning("all_award_timestamps_in_future", count=len(ingested_award_timestamps))
            await db.commit()

            contacts_added = 0
            for opportunity_id in new_opportunity_ids:
                try:
                    async with async_session() as lookup_db:
                        _, added = await retry_contact_lookup_for_opportunity(opportunity_id, lookup_db, tsa_db)
                        contacts_added += added
                    await push_opportunity_to_crm(opportunity_id)
                except Exception as exc:
                    logger.warning("lead_post_create_sync_failed", opportunity_id=opportunity_id, error=str(exc))

            retry_processed = await retry_new_lead_contact_lookups(limit=100)
            logger.info(
                "award_ingestion_complete", source="tenders_sa", since=since.isoformat(), awards_checked=len(raw_awards),
                leads_created=len(new_opportunity_ids), contacts_added=contacts_added,
                contact_retry_processed=retry_processed,
            )
            return len(raw_awards)
    finally:
        await tsa_db.close()


async def find_corrupted_award_dates(db=None) -> list[Award]:
    """Return all awards with NULL, future, or raw-year-corrupted award_date."""
    if db is None:
        async with async_session() as s:
            return await find_corrupted_award_dates(s)
    now = datetime.now(timezone.utc)
    corrupt = await db.execute(
        select(Award).where(
            or_(
                Award.award_date.is_(None),
                Award.award_date > now,
            )
        )
    )
    result: list[Award] = list(corrupt.scalars().all())

    # Also find records whose raw payload has a clearly-corrupt year (> MAX_VALID_YEAR)
    # even if the stored date was already corrected by a previous recovery run.
    extras = await db.execute(
        select(Award).where(
            Award.raw_payload.isnot(None),
            Award.award_date.isnot(None),
            Award.award_date <= now,
        )
    )
    for award in extras.scalars().all():
        payload = award.raw_payload or {}
        raw_date = payload.get("award_date") if isinstance(payload, dict) else None
        if raw_date and isinstance(raw_date, str) and len(raw_date) >= 4:
            try:
                raw_year = int(raw_date[:4])
            except ValueError:
                continue
            if raw_year > MAX_VALID_YEAR:
                result.append(award)

    return result


async def fix_corrupted_award_dates() -> int:
    """Repair awards with NULL or obviously-wrong award_date.

    Re-parses the raw payload and applies _resolve_award_date, which
    aggressively recovers a usable date using year correction (via
    reference years from pub_date, tender dates, or discovered_at),
    then falls back to the best available proxy. Returns the count of
    awards whose award_date actually changed.
    """

    async with async_session() as db:
        rows = await find_corrupted_award_dates(db)
        if not rows:
            return 0

        now = datetime.now(timezone.utc)
        fixed = 0
        for award in rows:
            original = award.award_date

            t_result = await db.execute(select(Tender).where(Tender.id == award.tender_id))
            tender = t_result.scalar_one_or_none()

            recovered = _resolve_award_date(
                award.raw_payload.get("award_date") if award.raw_payload else None,
                award.publication_date,
                tender.published_at if tender else None,
                tender.closing_date if tender else None,
                award.discovered_at, now,
            )
            if recovered != original:
                award.award_date = recovered
                fixed += 1
                logger.info(
                    "award_date_recovered",
                    award_id=award.id,
                    original=str(original) if original else "NULL",
                    resolved=recovered.isoformat(),
                )

        await db.commit()
        logger.info("corrupted_award_dates_fixed", total=len(rows), fixed=fixed)
        return fixed


async def backfill_recent_awards() -> int:
    """Admin-triggered recovery path: re-ingest the full current 30-day window."""
    return await check_awards_for_watching(backfill=True)
