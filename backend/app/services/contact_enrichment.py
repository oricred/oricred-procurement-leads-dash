"""Pull supplier and buyer contacts from the Tenders-SA database.

Three rules govern this module, all of them learned the hard way:

1. **Only recoverable errors are swallowed.** Every handler here used to be
   `except Exception`, which turned a `NameError` in the query layer into
   "no contacts found in Tenders-SA" for the operator. Handlers now catch
   `RECOVERABLE` only and count what they caught, so a systemic failure is
   visible in the job run instead of looking like an empty result set.

2. **"No email" is NULL, never the empty string.** The unique index on
   (company_id, email) is partial, so any number of phone-only contacts can
   coexist for one company.

3. **A company match must be unambiguous.** Substring matching once accepted
   the first of up to 10,000 candidates in arbitrary order, which writes one
   company's directors onto another company's lead. An uncertain match is
   worse than no match, because an operator acts on it.

See docs/specifications/remediation-01-contact-enrichment-restoration.md.
"""

from collections import defaultdict
from dataclasses import dataclass

import structlog
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.clients.tsa_db import TSADatabase
from app.database import async_session
from app.models.company import Company
from app.models.contact import Contact
from app.models.organization import Organization
from app.services.text_utils import normalise_company_name

logger = structlog.get_logger()

# Errors that mean "this one company could not be enriched right now". Anything
# else is a bug in our own code and must reach the job runner, which records it
# as status=failed. Never widen this to bare Exception.
RECOVERABLE = (SQLAlchemyError, TimeoutError, OSError)


@dataclass
class EnrichmentResult:
    """Outcome of an enrichment pass.

    `errors` is what distinguishes "Tenders-SA holds no contact for this
    supplier" from "we could not reach Tenders-SA". Both produce added=0.
    """

    added: int = 0
    errors: int = 0
    companies_attempted: int = 0

    def __add__(self, other: "EnrichmentResult") -> "EnrichmentResult":
        return EnrichmentResult(
            self.added + other.added,
            self.errors + other.errors,
            self.companies_attempted + other.companies_attempted,
        )

    @property
    def error_rate(self) -> float:
        if not self.companies_attempted:
            return 0.0
        return self.errors / self.companies_attempted


def _is_synthetic_company_api_id(api_id: str | None) -> bool:
    return bool(api_id and (api_id.startswith("award:") or api_id.startswith("historical:")))


def _split_name(full_name: str) -> tuple[str, str]:
    stripped = full_name.strip()
    if not stripped:
        return "", ""
    parts = stripped.split(None, 1)
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], parts[1]


def _entity_filters(company_id: str | None, organization_id: str | None) -> list:
    filters = []
    if company_id:
        filters.append(Contact.company_id == company_id)
    if organization_id:
        filters.append(Contact.organization_id == organization_id)
    return filters


def _apply_contact_backfill(contact: Contact, phone: str | None, job_title: str | None) -> bool:
    changed = False
    if job_title and not contact.job_title:
        contact.job_title = job_title
        changed = True
    if phone and not contact.phone_direct and not contact.phone_mobile:
        contact.phone_direct = phone
        changed = True
    return changed


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
    entity_filters = _entity_filters(company_id, organization_id)
    if not entity_filters:
        # Without an owning entity a "duplicate" check would match globally.
        logger.warning("upsert_contact_without_entity", full_name=full_name)
        return False

    async with async_session() as db:
        if email:
            result = await db.execute(
                select(Contact).where(Contact.email == email, *entity_filters).limit(1)
            )
            existing = result.scalars().first()
            if existing:
                if _apply_contact_backfill(existing, phone, job_title):
                    await db.commit()
                return False
        elif phone:
            result = await db.execute(
                select(Contact)
                .where(
                    *entity_filters,
                    or_(Contact.phone_direct == phone, Contact.phone_mobile == phone),
                )
                .limit(1)
            )
            existing = result.scalars().first()
            if existing:
                if _apply_contact_backfill(existing, phone, job_title):
                    await db.commit()
                return False

            # Deliberately no "any contact with no email" lookup here. That
            # matches the first email-less contact for the entity regardless of
            # who it is, so a company could still only ever hold one phone-only
            # person — the H3 defect. The name match below is the precise
            # version of the same dedup.

        # Match by name for contacts already imported without a stable email.
        # .first() rather than scalar_one_or_none(): duplicates exist in practice
        # and raising MultipleResultsFound here just loses the contact.
        result = await db.execute(
            select(Contact)
            .where(
                *entity_filters,
                Contact.first_name == first_name,
                Contact.last_name == last_name,
            )
            .limit(1)
        )
        existing = result.scalars().first()
        if existing:
            if _apply_contact_backfill(existing, phone, job_title):
                await db.commit()
            return False

        contact = Contact(
            company_id=company_id,
            organization_id=organization_id,
            first_name=first_name,
            last_name=last_name,
            job_title=job_title,
            # NULL, never "". The partial unique index on (company_id, email)
            # only constrains rows with an email, so any number of phone-only
            # contacts can coexist.
            email=email or None,
            phone_direct=phone,
            phone_mobile=None,
            source=source,
        )
        db.add(contact)
        await db.commit()
        return True


def _index_by_normalised_name(rows: list[dict]) -> dict[str, list[str]]:
    """Group Tenders-SA rows by normalised name. A key with more than one id is
    ambiguous and must not be matched."""
    index: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        name = (row.get("name") or "").strip()
        row_id = row.get("id")
        if name and row_id:
            index[normalise_company_name(name)].append(str(row_id))
    return index


def _resolve_unique(index: dict[str, list[str]], name: str, kind: str) -> str | None:
    """Return the single Tenders-SA id matching `name`, or None.

    Refuses to guess: zero candidates and two-or-more candidates both return
    None, and both are logged so the normaliser can be tuned against real data.
    """
    candidates = index.get(normalise_company_name(name), [])
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        logger.info(f"{kind}_match_ambiguous", local=name, candidate_count=len(candidates))
    else:
        logger.info(f"{kind}_match_none", local=name)
    return None


async def _match_orgs_to_tsa(
    tsa_db: TSADatabase,
    local_orgs: list[Organization],
) -> dict[str, str]:
    """Match local organisations to Tenders-SA organisation IDs by exact
    normalised name."""
    index = _index_by_normalised_name(await tsa_db.query_organizations(limit=5000))
    mapping: dict[str, str] = {}
    for local in local_orgs:
        if not local.id:
            continue
        match = _resolve_unique(index, local.name, "org")
        if match:
            mapping[local.id] = match
    return mapping


async def _match_companies_to_tsa(
    tsa_db: TSADatabase,
    local_companies: list[Company],
) -> dict[str, str]:
    """Match local companies to Tenders-SA company IDs.

    Prefers the stored api_id; falls back to an exact normalised-name match.
    """
    mapping: dict[str, str] = {}
    unmatched: list[Company] = []
    for company in local_companies:
        if company.api_id and not _is_synthetic_company_api_id(company.api_id):
            mapping[company.id] = company.api_id
        else:
            unmatched.append(company)
    if not unmatched:
        return mapping

    index = _index_by_normalised_name(await tsa_db.query_companies(limit=10000))
    for local in unmatched:
        match = _resolve_unique(index, local.name, "company")
        if match:
            mapping[local.id] = match
    return mapping


async def _pull_company_people(
    tsa_db: TSADatabase, company: Company, tsa_id: str
) -> EnrichmentResult:
    """Fetch directors and key personnel for one Tenders-SA company id."""
    result = EnrichmentResult(companies_attempted=1)

    try:
        directors = await tsa_db.query_directors(company_ids=[tsa_id])
    except RECOVERABLE as exc:
        logger.warning("director_fetch_failed", company=company.name, error=str(exc))
        result.errors += 1
    else:
        for director in directors:
            if await _upsert_contact(
                company_id=company.id,
                organization_id=None,
                full_name=director.get("full_name", ""),
                email=director.get("email"),
                phone=director.get("phone"),
                job_title="Director",
                source="tsa_db_enrichment",
            ):
                result.added += 1

    try:
        personnel = await tsa_db.query_key_personnel(company_ids=[tsa_id])
    except RECOVERABLE as exc:
        logger.warning("personnel_fetch_failed", company=company.name, error=str(exc))
        result.errors += 1
    else:
        for person in personnel:
            if await _upsert_contact(
                company_id=company.id,
                organization_id=None,
                full_name=person.get("full_name", ""),
                email=person.get("email"),
                phone=person.get("phone"),
                job_title=person.get("role") or person.get("department"),
                source="tsa_db_enrichment",
            ):
                result.added += 1

    return result


async def enrich_company_contacts_by_id(
    company_id: str, tsa_db: TSADatabase
) -> EnrichmentResult:
    """Pull directors and key personnel from Tenders-SA for one local company."""
    async with async_session() as db:
        company = await db.get(Company, company_id)
        if not company:
            return EnrichmentResult()

    tsa_ids: list[str] = []
    if company.api_id and not _is_synthetic_company_api_id(company.api_id):
        tsa_ids.append(company.api_id)

    try:
        index = _index_by_normalised_name(
            await tsa_db.query_companies(
                filters={"names": [company.name]}, fields=["id", "name"], limit=10
            )
        )
    except RECOVERABLE as exc:
        logger.warning("company_contact_match_failed", company=company.name, error=str(exc))
        return EnrichmentResult(errors=1, companies_attempted=1)

    match = _resolve_unique(index, company.name, "company")
    if match and match not in tsa_ids:
        tsa_ids.append(match)

    if not tsa_ids:
        return EnrichmentResult(companies_attempted=1)

    total = EnrichmentResult()
    for tsa_id in tsa_ids:
        total = total + await _pull_company_people(tsa_db, company, tsa_id)
    # One local company, however many Tenders-SA ids it resolved to.
    total.companies_attempted = 1
    return total


async def enrich_company_contacts(tsa_db: TSADatabase) -> EnrichmentResult:
    """Pull directors and key personnel from Tenders-SA for all tracked companies."""
    async with async_session() as db:
        companies = (await db.execute(select(Company))).scalars().all()

    if not companies:
        return EnrichmentResult()

    try:
        id_map = await _match_companies_to_tsa(tsa_db, list(companies))
    except RECOVERABLE as exc:
        logger.warning("company_match_query_failed", error=str(exc))
        return EnrichmentResult(errors=1, companies_attempted=len(companies))

    by_local_id = {c.id: c for c in companies}
    total = EnrichmentResult()
    for local_id, tsa_id in id_map.items():
        total = total + await _pull_company_people(tsa_db, by_local_id[local_id], tsa_id)
    return total


async def enrich_organization_contacts(tsa_db: TSADatabase) -> EnrichmentResult:
    """Pull source directors from Tenders-SA for all tracked organisations."""
    async with async_session() as db:
        orgs = (await db.execute(select(Organization))).scalars().all()

    if not orgs:
        return EnrichmentResult()

    try:
        id_map = await _match_orgs_to_tsa(tsa_db, list(orgs))
    except RECOVERABLE as exc:
        logger.warning("org_match_query_failed", error=str(exc))
        return EnrichmentResult(errors=1, companies_attempted=len(orgs))

    tsa_org_ids = list(id_map.values())
    if not tsa_org_ids:
        return EnrichmentResult(companies_attempted=len(orgs))

    local_by_tsa_id = {tsa_id: local_id for local_id, tsa_id in id_map.items()}
    result = EnrichmentResult(companies_attempted=len(tsa_org_ids))

    try:
        directors = await tsa_db.query_source_directors(organization_ids=tsa_org_ids)
    except RECOVERABLE as exc:
        logger.warning("source_director_fetch_failed", error=str(exc))
        result.errors += len(tsa_org_ids)
        return result

    for director in directors:
        local_org_id = local_by_tsa_id.get(str(director.get("organization_id")))
        if not local_org_id:
            continue
        if await _upsert_contact(
            company_id=None,
            organization_id=local_org_id,
            full_name=director.get("full_name", ""),
            email=director.get("email"),
            phone=director.get("phone"),
            job_title=director.get("position") or "Director",
            source="tsa_db_enrichment",
        ):
            result.added += 1

    return result


async def enrich_all_contacts() -> EnrichmentResult:
    """Full contact enrichment from the Tenders-SA database."""
    tsa_db = TSADatabase()
    try:
        company_result = await enrich_company_contacts(tsa_db)
        org_result = await enrich_organization_contacts(tsa_db)
        total = company_result + org_result
        logger.info(
            "contact_enrichment_complete",
            added=total.added,
            errors=total.errors,
            attempted=total.companies_attempted,
            from_companies=company_result.added,
            from_organizations=org_result.added,
        )
        return total
    finally:
        await tsa_db.close()
