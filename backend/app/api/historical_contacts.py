from collections import defaultdict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import exists, func, or_, select
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


def _has_reachable_contact():
    """SQL form of "this company has at least one contactable person".

    Must agree with classify_company_contacts, which returns "sufficient" when
    any company contact has an email or either phone number. A test asserts the
    two agree over every combination — if they drift, the filter and the badge
    shown beside it contradict each other.
    """
    return exists(
        select(Contact.id).where(
            Contact.company_id == Company.id,
            or_(
                Contact.email.isnot(None),
                Contact.phone_direct.isnot(None),
                Contact.phone_mobile.isnot(None),
            ),
        )
    )


@router.get("", response_model=HistoricalContactList)
async def list_historical_contacts(
    search: str | None = Query(None),
    contactability: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Companies with historical award activity.

    Contactability is filtered in SQL. It used to be applied in Python after
    the row limit, so asking for 100 contactable companies could return four
    with no indication the list had been truncated before filtering. Contacts
    are batch-loaded for the page rather than queried per row.
    """
    base = select(HistoricalContact, Company).join(
        Company, Company.id == HistoricalContact.company_id
    )

    if search:
        pattern = f"%{search.lower()}%"
        base = base.where(
            or_(
                func.lower(Company.name).like(pattern),
                func.lower(Company.registration_number).like(pattern),
            )
        )

    if contactability == "contactable":
        base = base.where(_has_reachable_contact())
    elif contactability == "needs_contact":
        base = base.where(~_has_reachable_contact())

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0

    rows = (
        await db.execute(
            base.order_by(
                HistoricalContact.last_award_date.desc().nulls_last(), Company.name
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()

    company_ids = [company.id for _historical, company in rows]
    contacts_by_company: dict[str, list[Contact]] = defaultdict(list)
    if company_ids:
        for contact in (
            await db.execute(
                select(Contact)
                .where(Contact.company_id.in_(company_ids))
                .order_by(Contact.is_primary.desc(), Contact.last_name, Contact.first_name)
            )
        ).scalars():
            contacts_by_company[contact.company_id].append(contact)

    items = [
        HistoricalContactRead(
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
            contact_sufficiency=classify_company_contacts(contacts_by_company[company.id]),
            primary_contact=(
                _contact_to_read(primary)
                if (primary := choose_primary_contact(contacts_by_company[company.id]))
                else None
            ),
            contacts=[_contact_to_read(c) for c in contacts_by_company[company.id]],
            source=historical.source,
            last_synced_at=historical.last_synced_at,
        )
        for historical, company in rows
    ]

    return HistoricalContactList(
        items=items, total=total, page=page, page_size=page_size
    )
