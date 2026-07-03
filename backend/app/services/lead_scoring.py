from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.award import Award
from app.models.company import Company
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.models.tender import Tender

TARGET_MIN_AWARD = Decimal("500000")
TARGET_MAX_AWARD = Decimal("20000000")
RECENT_AWARD_DAYS = 30
ENTERPRISE_SMALL_VALUES = {"eme", "qse", "small", "micro", "sme", "emerging"}


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def choose_primary_contact(contacts: list[Contact]) -> Contact | None:
    company_contacts = [c for c in contacts if c.company_id]
    candidates = company_contacts or contacts
    if not candidates:
        return None

    def score(contact: Contact) -> tuple[int, str]:
        contactable = bool(contact.email or contact.phone_direct or contact.phone_mobile)
        return (
            1 if contact.is_primary else 0,
            1 if contactable else 0,
            1 if contact.job_title else 0,
            contact.last_name or "",
        )

    return sorted(candidates, key=score, reverse=True)[0]


def classify_company_contacts(contacts: list[Contact]) -> str:
    company_contacts = [c for c in contacts if c.company_id]
    if any(c.email or c.phone_direct or c.phone_mobile for c in company_contacts):
        return "sufficient"
    if company_contacts:
        return "role_based"
    return "none"


def _enterprise_type(raw_payload: dict | None) -> str | None:
    if not raw_payload:
        return None
    for key in ("enterprise_type", "most_recent_enterprise_type", "supplier_enterprise_type"):
        value = raw_payload.get(key)
        if value:
            return str(value).strip().lower()
    return None


async def compute_lead_priority(
    opp: Opportunity,
    db: AsyncSession,
    tender: Tender | None = None,
    award: Award | None = None,
    company: Company | None = None,
    contacts: list[Contact] | None = None,
) -> tuple[float, list[str], str]:
    contacts = contacts or []
    reasons: list[str] = []
    score = 0.0

    if company and company.restricted_supplier:
        return 0.0, ["Restricted supplier"], "Review risk"

    contact_status = classify_company_contacts(contacts)
    if contact_status == "sufficient":
        score += 35
        reasons.append("Supplier contact found")
    elif contact_status == "role_based":
        score += 15
        reasons.append("Supplier contact needs verification")
    else:
        reasons.append("No supplier contact")

    if award and award.award_date:
        days_since = (datetime.now(timezone.utc) - award.award_date).days
        if days_since <= 7:
            score += 20
            reasons.append("Awarded this week")
        elif days_since <= RECENT_AWARD_DAYS:
            score += 14
            reasons.append("Recent award")
        elif days_since <= 90:
            score += 8
            reasons.append("Awarded within 90 days")

    award_amount = _as_decimal(award.amount if award else None)
    if award_amount is not None:
        if TARGET_MIN_AWARD <= award_amount <= TARGET_MAX_AWARD:
            score += 15
            reasons.append("Award value in target range")
        elif award_amount > 0:
            score += 8
            reasons.append("Award value available")

    enterprise_type = _enterprise_type(award.raw_payload if award else None)
    if enterprise_type and any(token in enterprise_type for token in ENTERPRISE_SMALL_VALUES):
        score += 20
        reasons.append(f"Small enterprise signal: {enterprise_type.upper()}")
    elif company:
        history = await db.execute(
            select(func.count(Award.id), func.coalesce(func.sum(Award.amount), 0))
            .where(Award.supplier_company_id == company.api_id)
        )
        award_count, total_value = history.one()
        total_value = Decimal(str(total_value or 0))
        if award_count <= 1 and total_value <= Decimal("5000000"):
            score += 15
            reasons.append("Low prior award history")
        elif award_count <= 3 and total_value <= Decimal("15000000"):
            score += 10
            reasons.append("Moderate prior award history")

    if company and company.bee_level is not None and company.bee_level <= 4:
        score += 7
        reasons.append(f"B-BBEE level {company.bee_level}")
    elif award and award.bee_level is not None and award.bee_level <= 4:
        score += 5
        reasons.append(f"Award B-BBEE level {award.bee_level}")

    if opp.buyer_preference_score is not None:
        score += min(float(opp.buyer_preference_score), 100.0) * 0.08

    if contact_status == "sufficient":
        next_action = "Contact company"
    elif contact_status == "role_based":
        next_action = "Review contact"
    else:
        next_action = "Find contact"

    return round(min(score, 100.0), 2), reasons[:6], next_action


async def refresh_lead_scoring(
    opp: Opportunity,
    db: AsyncSession,
    tender: Tender | None = None,
    award: Award | None = None,
    company: Company | None = None,
    contacts: list[Contact] | None = None,
) -> Opportunity:
    if tender is None and opp.tender_id:
        tender = await db.get(Tender, opp.tender_id)
    if award is None and opp.award_id:
        award = await db.get(Award, opp.award_id)
    if company is None and opp.company_id:
        company = await db.get(Company, opp.company_id)
    if contacts is None:
        if opp.company_id:
            result = await db.execute(
                select(Contact)
                .where(Contact.company_id == opp.company_id)
                .order_by(Contact.is_primary.desc(), Contact.last_name)
            )
            contacts = result.scalars().all()
        else:
            contacts = []

    score, reasons, next_action = await compute_lead_priority(opp, db, tender, award, company, contacts)
    opp.contact_sufficiency = classify_company_contacts(contacts)
    opp.lead_priority_score = score
    opp.lead_priority_reasons = reasons
    opp.next_action = next_action
    opp.updated_at = datetime.now(timezone.utc)
    return opp
