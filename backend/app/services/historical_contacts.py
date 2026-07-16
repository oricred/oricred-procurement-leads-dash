import hashlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from app.utils import parse_datetime

import structlog
from sqlalchemy import select

from app.clients.tsa_db import TSADatabase
from app.database import async_session
from app.models.company import Company
from app.models.historical_contact import HistoricalContact
from app.services.contact_enrichment import enrich_company_contacts_by_id
from app.services.qualification import QualificationService

logger = structlog.get_logger()

HISTORICAL_CUTOFF_DAYS = 90
HISTORICAL_AWARD_FIELDS = [
    "id",
    "tender_id",
    "supplier_name",
    "supplier_canonical_id",
    "amount",
    "award_date",
    "bee_level",
    "bee_points",
]
COMPANY_FIELDS = ["id", "name", "registration_number", "bbbee_level", "contact_email", "contact_phone", "website"]


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().split())


def _stable_company_api_id(name: str, canonical_id: str | None) -> str:
    if canonical_id:
        return canonical_id[:64]
    digest = hashlib.sha1(_normalize_name(name).lower().encode("utf-8")).hexdigest()[:32]
    return f"historical:{digest}"


def _award_key(raw: dict[str, Any]) -> str:
    if raw.get("id"):
        return str(raw["id"])
    basis = "|".join(str(raw.get(k) or "") for k in ("supplier_name", "tender_id", "award_date", "amount"))
    return "synthetic:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:40]



def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _filters_from_config(config: dict[str, Any], cutoff: datetime) -> dict[str, Any]:
    filters: dict[str, Any] = {"until": cutoff}

    for rule in config.get("value_range", {}).get("rules", []):
        if rule.get("min") is not None:
            filters["value_min"] = rule["min"]
        if rule.get("max") is not None:
            filters["value_max"] = rule["max"]

    for rule in config.get("sector", {}).get("rules", []):
        if rule.get("type") == "include" and rule.get("values"):
            filters["category"] = rule["values"]

    for rule in config.get("province", {}).get("rules", []):
        if rule.get("type") == "include" and rule.get("values"):
            filters["province"] = rule["values"]

    return filters


async def _company_lookup(tsa_db: TSADatabase, awards: list[dict[str, Any]]) -> tuple[dict[str, dict], dict[str, dict]]:
    names = sorted({_normalize_name(a.get("supplier_name", "")) for a in awards if a.get("supplier_name")})
    api_ids = sorted({str(a.get("supplier_canonical_id")) for a in awards if a.get("supplier_canonical_id")})
    by_name: dict[str, dict] = {}
    by_id: dict[str, dict] = {}

    if names:
        try:
            rows = await tsa_db.query_companies(filters={"names": names}, fields=COMPANY_FIELDS, limit=min(len(names), 5000))
            by_name = {_normalize_name(str(row.get("name") or "")).lower(): row for row in rows if row.get("name")}
            by_id.update({str(row.get("id")): row for row in rows if row.get("id")})
        except Exception as e:
            logger.warning("historical_company_name_lookup_failed", error=str(e))

    if api_ids:
        try:
            rows = await tsa_db.query_companies(filters={"api_ids": api_ids}, fields=COMPANY_FIELDS, limit=min(len(api_ids), 5000))
            by_id.update({str(row.get("id")): row for row in rows if row.get("id")})
            by_name.update({_normalize_name(str(row.get("name") or "")).lower(): row for row in rows if row.get("name")})
        except Exception as e:
            logger.warning("historical_company_id_lookup_failed", error=str(e))

    return by_name, by_id


async def sync_historical_contacts(limit: int = 1000, cutoff_days: int = HISTORICAL_CUTOFF_DAYS) -> dict[str, int]:
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=cutoff_days)
    tsa_db = TSADatabase()
    try:
        async with async_session() as db:
            config = await QualificationService(db).get_config()
        filters = _filters_from_config(config or QualificationService.default_config(), cutoff)

        awards = await tsa_db.query_awards(filters=filters, fields=HISTORICAL_AWARD_FIELDS, limit=limit)
        by_name, by_id = await _company_lookup(tsa_db, awards)

        imported = 0
        updated = 0
        company_ids_for_enrichment: set[str] = set()
        now = datetime.now(timezone.utc)

        async with async_session() as db:
            for raw in awards:
                supplier_name = _normalize_name(str(raw.get("supplier_name") or ""))
                if not supplier_name:
                    continue

                canonical_id = str(raw.get("supplier_canonical_id") or "") or None
                company_data = by_id.get(canonical_id or "") or by_name.get(supplier_name.lower()) or {}
                api_id = _stable_company_api_id(supplier_name, company_data.get("id") or canonical_id)

                result = await db.execute(select(Company).where(Company.api_id == api_id))
                company = result.scalar_one_or_none()
                if not company:
                    company = Company(api_id=api_id, name=company_data.get("name") or supplier_name)
                    db.add(company)
                    await db.flush()
                    imported += 1

                company.name = company_data.get("name") or company.name or supplier_name
                company.registration_number = company_data.get("registration_number") or company.registration_number
                company.bee_level = company_data.get("bbbee_level") or raw.get("bee_level") or company.bee_level
                company.raw_payload = {
                    "source": "historical_award",
                    "tsa_company_id": company_data.get("id") or canonical_id,
                    "last_award_id": raw.get("id"),
                    "contact_email": company_data.get("contact_email"),
                    "contact_phone": company_data.get("contact_phone"),
                    "website": company_data.get("website"),
                }
                company.last_refreshed_at = now

                result = await db.execute(select(HistoricalContact).where(HistoricalContact.company_id == company.id))
                historical = result.scalar_one_or_none()
                if not historical:
                    historical = HistoricalContact(company_id=company.id, source="tenders_api", award_ids=[])
                    db.add(historical)
                    await db.flush()

                seen = list(historical.award_ids or [])
                key = _award_key(raw)
                award_date = parse_datetime(raw.get("award_date"))
                amount = _as_decimal(raw.get("amount"))

                if key not in seen:
                    historical.award_ids = [*seen, key]
                    historical.total_award_count = int(historical.total_award_count or 0) + 1
                    if amount is not None:
                        current_total = _as_decimal(historical.total_award_value) or Decimal("0")
                        historical.total_award_value = current_total + amount
                    first_award_date = parse_datetime(historical.first_award_date)
                    last_award_date = parse_datetime(historical.last_award_date)
                    if award_date and (first_award_date is None or award_date < first_award_date):
                        historical.first_award_date = award_date
                    if award_date and (last_award_date is None or award_date > last_award_date):
                        historical.last_award_date = award_date
                        historical.last_award_id = str(raw.get("id") or key)[:64]
                    updated += 1

                historical.last_synced_at = now
                historical.updated_at = now
                company_ids_for_enrichment.add(str(company.id))

            await db.commit()

        contacts_added = 0
        for company_id in company_ids_for_enrichment:
            try:
                contacts_added += await enrich_company_contacts_by_id(company_id, tsa_db)
            except Exception as e:
                logger.warning("historical_contact_enrichment_failed", company_id=company_id, error=str(e))

        logger.info(
            "historical_contacts_sync_complete",
            awards_checked=len(awards),
            companies_imported=imported,
            history_updates=updated,
            contacts_added=contacts_added,
        )
        return {"awards_checked": len(awards), "companies_imported": imported, "history_updates": updated, "contacts_added": contacts_added}
    finally:
        await tsa_db.close()


