from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.contact import Contact
from app.models.company import Company
from app.models.organization import Organization
from app.models.opportunity import Opportunity
from app.models.tender import Tender
from app.schemas.contact import ContactRead, ContactCreate, ContactUpdate

router = APIRouter()


async def _get_contact(contact_id: str, db: AsyncSession) -> Contact:
    result = await db.execute(select(Contact).where(Contact.id == contact_id))
    contact = result.scalar_one_or_none()
    if not contact:
        raise HTTPException(status_code=404, detail="Contact not found")
    return contact


@router.get("/companies/{company_id}/contacts", response_model=list[ContactRead])
async def list_company_contacts(company_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Contact).where(Contact.company_id == company_id).order_by(Contact.is_primary.desc(), Contact.last_name)
    )
    return result.scalars().all()


@router.post("/companies/{company_id}/contacts", response_model=ContactRead, status_code=201)
async def create_company_contact(company_id: str, body: ContactCreate, db: AsyncSession = Depends(get_db)):
    c_result = await db.execute(select(Company).where(Company.id == company_id))
    if not c_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Company not found")

    contact = Contact(
        company_id=company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        job_title=body.job_title,
        email=body.email,
        phone_direct=body.phone_direct,
        phone_mobile=body.phone_mobile,
        linkedin_url=body.linkedin_url,
        is_primary=body.is_primary,
        notes=body.notes,
    )
    if contact.is_primary:
        await _clear_primary_company_contacts(company_id, db)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


@router.get("/organizations/{org_id}/contacts", response_model=list[ContactRead])
async def list_organization_contacts(org_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Contact).where(Contact.organization_id == org_id).order_by(Contact.is_primary.desc(), Contact.last_name)
    )
    return result.scalars().all()


@router.post("/organizations/{org_id}/contacts", response_model=ContactRead, status_code=201)
async def create_organization_contact(org_id: str, body: ContactCreate, db: AsyncSession = Depends(get_db)):
    o_result = await db.execute(select(Organization).where(Organization.id == org_id))
    if not o_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Organization not found")

    contact = Contact(
        organization_id=org_id,
        first_name=body.first_name,
        last_name=body.last_name,
        job_title=body.job_title,
        email=body.email,
        phone_direct=body.phone_direct,
        phone_mobile=body.phone_mobile,
        linkedin_url=body.linkedin_url,
        is_primary=body.is_primary,
        notes=body.notes,
    )
    if contact.is_primary:
        await _clear_primary_org_contacts(org_id, db)
    db.add(contact)
    await db.commit()
    await db.refresh(contact)
    return contact


@router.get("/contacts/{contact_id}", response_model=ContactRead)
async def get_contact(contact_id: str, db: AsyncSession = Depends(get_db)):
    return await _get_contact(contact_id, db)


@router.patch("/contacts/{contact_id}", response_model=ContactRead)
async def update_contact(contact_id: str, body: ContactUpdate, db: AsyncSession = Depends(get_db)):
    contact = await _get_contact(contact_id, db)

    if body.first_name is not None:
        contact.first_name = body.first_name
    if body.last_name is not None:
        contact.last_name = body.last_name
    if body.job_title is not None:
        contact.job_title = body.job_title
    if body.email is not None:
        contact.email = body.email
    if body.phone_direct is not None:
        contact.phone_direct = body.phone_direct
    if body.phone_mobile is not None:
        contact.phone_mobile = body.phone_mobile
    if body.linkedin_url is not None:
        contact.linkedin_url = body.linkedin_url
    if body.is_primary is not None:
        contact.is_primary = body.is_primary
        if body.is_primary:
            if contact.company_id:
                await _clear_primary_company_contacts(contact.company_id, db, exclude_id=contact.id)
            if contact.organization_id:
                await _clear_primary_org_contacts(contact.organization_id, db, exclude_id=contact.id)
    if body.notes is not None:
        contact.notes = body.notes

    await db.commit()
    await db.refresh(contact)
    return contact


@router.delete("/contacts/{contact_id}", status_code=204)
async def delete_contact(contact_id: str, db: AsyncSession = Depends(get_db)):
    contact = await _get_contact(contact_id, db)
    await db.delete(contact)
    await db.commit()


@router.get("/opportunities/{opportunity_id}/contacts", response_model=list[ContactRead])
async def list_opportunity_contacts(opportunity_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Opportunity).where(Opportunity.id == opportunity_id))
    opp = result.scalar_one_or_none()
    if not opp:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    contacts = []

    if opp.company_id:
        c_result = await db.execute(
            select(Contact).where(Contact.company_id == opp.company_id).order_by(Contact.is_primary.desc(), Contact.last_name)
        )
        contacts.extend(c_result.scalars().all())

    if opp.tender_id:
        t_result = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
        tender = t_result.scalar_one_or_none()
        if tender and tender.buyer_org_id:
            o_result = await db.execute(
                select(Contact).where(Contact.organization_id == tender.buyer_org_id).order_by(Contact.is_primary.desc(), Contact.last_name)
            )
            org_contacts = o_result.scalars().all()
            seen_ids = {c.id for c in contacts}
            for c in org_contacts:
                if c.id not in seen_ids:
                    contacts.append(c)

    return contacts


async def _clear_primary_company_contacts(company_id: str, db: AsyncSession, exclude_id: str | None = None):
    q = select(Contact).where(Contact.company_id == company_id, Contact.is_primary == True)
    if exclude_id:
        q = q.where(Contact.id != exclude_id)
    result = await db.execute(q)
    for c in result.scalars().all():
        c.is_primary = False


async def _clear_primary_org_contacts(org_id: str, db: AsyncSession, exclude_id: str | None = None):
    q = select(Contact).where(Contact.organization_id == org_id, Contact.is_primary == True)
    if exclude_id:
        q = q.where(Contact.id != exclude_id)
    result = await db.execute(q)
    for c in result.scalars().all():
        c.is_primary = False
