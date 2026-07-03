import structlog
from sqlalchemy import select

from app.clients.tsa_db import TSADatabase
from app.database import async_session
from app.models.contact import Contact
from app.models.company import Company
from app.models.organization import Organization

logger = structlog.get_logger()


def _split_name(full_name: str) -> tuple[str, str]:
    stripped = full_name.strip()
    if not stripped:
        return "", ""
    parts = stripped.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


async def _upsert_contact(
    company_id: str | None,
    organization_id: str | None,
    full_name: str,
    email: str | None,
    phone: str | None,
    job_title: str | None,
    source: str,
) -> bool:
    if not full_name:
        return False
    if not email and not phone:
        return False

    first_name, last_name = _split_name(full_name)

    async with async_session() as db:
        # Check if a contact with this email already exists for this entity
        if email:
            filters = [Contact.email == email]
            if company_id:
                filters.append(Contact.company_id == company_id)
            if organization_id:
                filters.append(Contact.organization_id == organization_id)
            result = await db.execute(select(Contact).where(*filters))
            existing = result.scalar_one_or_none()
            if existing:
                changed = False
                if job_title and not existing.job_title:
                    existing.job_title = job_title
                    changed = True
                if phone and not existing.phone_direct and not existing.phone_mobile:
                    existing.phone_direct = phone
                    changed = True
                if changed:
                    await db.commit()
                return False

        # Check by name if no email
        if company_id:
            result = await db.execute(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.first_name == first_name,
                    Contact.last_name == last_name,
                )
            )
            if result.scalar_one_or_none():
                return False

        contact = Contact(
            company_id=company_id,
            organization_id=organization_id,
            first_name=first_name,
            last_name=last_name,
            job_title=job_title,
            email=email or "",
            phone_direct=phone,
            phone_mobile=None,
            source=source,
        )
        db.add(contact)
        await db.commit()
        return True


async def _match_orgs_to_tsa(tsa_db: TSADatabase, local_orgs: list[Organization]) -> dict[str, str]:
    """Match local orgs to TSA DB org IDs by name (exact case-insensitive, then contains fallback)."""
    tsa_orgs = await tsa_db.query_organizations(limit=5000)
    tsa_by_name: dict[str, str] = {}
    for o in tsa_orgs:
        name = o.get("name", "").strip().lower()
        if name:
            tsa_by_name[name] = o["id"]

    mapping: dict[str, str] = {}
    for local in local_orgs:
        if not local.id:
            continue
        local_lower = local.name.strip().lower()
        if local_lower in tsa_by_name:
            mapping[local.id] = tsa_by_name[local_lower]
            continue
        for tsa_name, tsa_id in tsa_by_name.items():
            if local_lower in tsa_name or tsa_name in local_lower:
                mapping[local.id] = tsa_id
                logger.info("org_name_fuzzy_match", local=local.name, tsa=tsa_name)
                break

    return mapping


async def _match_companies_to_tsa(tsa_db: TSADatabase, local_companies: list[Company]) -> dict[str, str]:
    """Match local companies to TSA DB company IDs. Prefers api_id, falls back to name match."""
    mapping: dict[str, str] = {}

    # First pass: use api_id
    no_api_id = []
    for c in local_companies:
        if c.api_id:
            mapping[c.id] = c.api_id
        else:
            no_api_id.append(c)

    if not no_api_id:
        return mapping

    # Second pass: name search for companies without api_id
    tsa_companies = await tsa_db.query_companies(limit=10000)
    tsa_by_name: dict[str, str] = {}
    for c in tsa_companies:
        name = c.get("name", "").strip().lower()
        if name:
            tsa_by_name[name] = c["id"]

    for local in no_api_id:
        local_lower = local.name.strip().lower()
        if local_lower in tsa_by_name:
            mapping[local.id] = tsa_by_name[local_lower]
            continue
        for tsa_name, tsa_id in tsa_by_name.items():
            if local_lower in tsa_name or tsa_name in local_lower:
                mapping[local.id] = tsa_id
                logger.info("company_name_fuzzy_match", local=local.name, tsa=tsa_name)
                break

    return mapping




async def enrich_company_contacts_by_id(company_id: str, tsa_db: TSADatabase) -> int:
    """Pull directors and key personnel from TSA DB for one local company."""
    async with async_session() as db:
        company = await db.get(Company, company_id)
        if not company:
            return 0

    tsa_id = company.api_id
    if not tsa_id:
        try:
            matches = await tsa_db.query_companies(filters={"names": [company.name]}, fields=["id"], limit=1)
            if matches:
                tsa_id = matches[0].get("id")
        except Exception as e:
            logger.warning("company_contact_match_failed", company=company.name, error=str(e))
            tsa_id = None

    if not tsa_id:
        return 0

    added = 0
    try:
        directors = await tsa_db.query_directors(company_ids=[tsa_id])
        for d in directors:
            if await _upsert_contact(
                company_id=company.id,
                organization_id=None,
                full_name=d.get("full_name", ""),
                email=d.get("email"),
                phone=d.get("phone"),
                job_title="Director",
                source="tsa_db_enrichment",
            ):
                added += 1
    except Exception as e:
        logger.warning("director_fetch_failed", company=company.name, error=str(e))

    try:
        personnel = await tsa_db.query_key_personnel(company_ids=[tsa_id])
        for p in personnel:
            if await _upsert_contact(
                company_id=company.id,
                organization_id=None,
                full_name=p.get("full_name", ""),
                email=p.get("email"),
                phone=p.get("phone"),
                job_title=p.get("role") or p.get("department"),
                source="tsa_db_enrichment",
            ):
                added += 1
    except Exception as e:
        logger.warning("personnel_fetch_failed", company=company.name, error=str(e))

    return added

async def enrich_company_contacts(tsa_db: TSADatabase) -> int:
    """Pull directors and key personnel from TSA DB for all tracked companies."""
    added = 0

    async with async_session() as db:
        result = await db.execute(select(Company))
        companies = result.scalars().all()

    if not companies:
        return 0

    id_map = await _match_companies_to_tsa(tsa_db, companies)

    for local_id, tsa_id in id_map.items():
        company = next(c for c in companies if c.id == local_id)

        try:
            directors = await tsa_db.query_directors(company_ids=[tsa_id])
            for d in directors:
                if await _upsert_contact(
                    company_id=company.id,
                    organization_id=None,
                    full_name=d.get("full_name", ""),
                    email=d.get("email"),
                    phone=d.get("phone"),
                    job_title="Director",
                    source="tsa_db_enrichment",
                ):
                    added += 1
        except Exception as e:
            logger.warning("director_fetch_failed", company=company.name, error=str(e))

        try:
            personnel = await tsa_db.query_key_personnel(company_ids=[tsa_id])
            for p in personnel:
                if await _upsert_contact(
                    company_id=company.id,
                    organization_id=None,
                    full_name=p.get("full_name", ""),
                    email=p.get("email"),
                    phone=p.get("phone"),
                    job_title=p.get("role") or p.get("department"),
                    source="tsa_db_enrichment",
                ):
                    added += 1
        except Exception as e:
            logger.warning("personnel_fetch_failed", company=company.name, error=str(e))

    return added


async def enrich_organization_contacts(tsa_db: TSADatabase) -> int:
    """Pull source directors from TSA DB for all tracked organizations."""
    added = 0

    async with async_session() as db:
        result = await db.execute(select(Organization))
        orgs = result.scalars().all()

    if not orgs:
        return 0

    id_map = await _match_orgs_to_tsa(tsa_db, orgs)
    tsa_org_ids = list(id_map.values())
    if not tsa_org_ids:
        return 0

    try:
        directors = await tsa_db.query_source_directors(organization_ids=tsa_org_ids)
        for d in directors:
            tsa_org_id = d.get("organization_id")
            local_org_id = next((lid for lid, tid in id_map.items() if tid == tsa_org_id), None)
            if not local_org_id:
                continue
            if await _upsert_contact(
                company_id=None,
                organization_id=local_org_id,
                full_name=d.get("full_name", ""),
                email=d.get("email"),
                phone=d.get("phone"),
                job_title=d.get("position", "Director"),
                source="tsa_db_enrichment",
            ):
                added += 1
    except Exception as e:
        logger.warning("source_director_fetch_failed", error=str(e))

    return added


async def enrich_all_contacts() -> dict[str, int]:
    """Full contact enrichment from TSA DB."""
    tsa_db = TSADatabase()
    try:
        company_added = await enrich_company_contacts(tsa_db)
        org_added = await enrich_organization_contacts(tsa_db)
        total = company_added + org_added
        logger.info("contact_enrichment_complete", added=total, companies=company_added, organizations=org_added)
        return {"added": total, "from_companies": company_added, "from_organizations": org_added}
    finally:
        await tsa_db.close()


