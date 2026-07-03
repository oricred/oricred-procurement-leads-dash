from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.company import Company
from app.models.contact import Contact
from app.models.historical_contact import HistoricalContact
from app.schemas.contact import ContactRead
from app.schemas.historical_contact import HistoricalContactList, HistoricalContactRead
from app.services.lead_scoring import choose_primary_contact, classify_company_contacts

router = APIRouter(prefix="/historical-contacts", tags=["historical-contacts"])


def _contact_to_read(contact: Contact) -> ContactRead:
    return ContactRead.model_validate(contact)


def _amount(value) -> float | None:
    if value is None:
        return None
    return float(value)


@router.get("", response_model=HistoricalContactList)
async def list_historical_contacts(
    search: str | None = Query(None),
    contactability: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(HistoricalContact, Company)
        .join(Company, Company.id == HistoricalContact.company_id)
        .order_by(HistoricalContact.last_award_date.desc().nulls_last(), Company.name)
        .limit(limit)
    )
    if search:
        pattern = f"%{search.lower()}%"
        q = q.where(or_(func.lower(Company.name).like(pattern), func.lower(Company.registration_number).like(pattern)))

    result = await db.execute(q)
    rows = result.all()

    items: list[HistoricalContactRead] = []
    for historical, company in rows:
        contact_result = await db.execute(
            select(Contact)
            .where(Contact.company_id == company.id)
            .order_by(Contact.is_primary.desc(), Contact.last_name, Contact.first_name)
        )
        contacts = contact_result.scalars().all()
        sufficiency = classify_company_contacts(contacts)
        if contactability == "contactable" and sufficiency != "sufficient":
            continue
        if contactability == "needs_contact" and sufficiency == "sufficient":
            continue

        primary = choose_primary_contact(contacts)
        items.append(HistoricalContactRead(
            id=str(historical.id),
            company_id=str(company.id),
            company_name=company.name,
            registration_number=company.registration_number,
            bee_level=company.bee_level,
            first_award_date=historical.first_award_date,
            last_award_date=historical.last_award_date,
            total_award_count=historical.total_award_count,
            total_award_value=_amount(historical.total_award_value),
            last_award_id=historical.last_award_id,
            contact_sufficiency=sufficiency,
            primary_contact=_contact_to_read(primary) if primary else None,
            contacts=[_contact_to_read(c) for c in contacts],
            source=historical.source,
            last_synced_at=historical.last_synced_at,
        ))

    return HistoricalContactList(items=items, total=len(items))


