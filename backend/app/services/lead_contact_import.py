import csv
import re
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.company import Company
from app.models.contact import Contact
from app.models.opportunity import Opportunity
from app.services.lead_scoring import refresh_lead_scoring

IMPORT_SOURCE = "lead_import"
EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IMPORT_METADATA_FIELDS = (
    ("contact_source_url", "Source URL"),
    ("contact_confidence", "Confidence"),
    ("enrichment_date", "Enrichment date"),
    ("research_notes", "Research notes"),
)

COLUMN_ALIASES = {
    "email": "contact_email",
    "e-mail": "contact_email",
    "mail": "contact_email",
    "phone": "contact_phone",
    "telephone": "contact_phone",
    "tel": "contact_phone",
    "cell": "contact_phone",
    "cellphone": "contact_phone",
    "mobile": "contact_phone",
    "phone_direct": "contact_phone",
    "phone_mobile": "contact_phone",
    "name": "contact_name",
    "contact_person": "contact_name",
    "full_name": "contact_name",
    "person": "contact_name",
    "job_title": "contact_job_title",
    "title": "contact_job_title",
    "position": "contact_job_title",
    "designation": "contact_job_title",
    "company_name": "company",
    "supplier": "company",
    "supplier_name": "company",
}


@dataclass
class ImportRow:
    row_number: int
    values: dict[str, str]


@dataclass
class ImportDecision:
    row: ImportRow
    action: str
    message: str
    opportunity: Opportunity | None = None
    contact: Contact | None = None
    company_id: str | None = None


def _clean(value: object | None) -> str:
    return str(value).strip() if value is not None else ""


def _normalise(value: str) -> str:
    return " ".join(value.lower().split())


def _normalise_phone(value: str) -> str:
    return re.sub(r"\D", "", value)


def _split_name(name: str) -> tuple[str, str]:
    parts = name.split(None, 1)
    return (parts[0], parts[1] if len(parts) > 1 else "")


def _canonicalise_row(row: ImportRow) -> ImportRow:
    mapped = row.values.copy()
    for alias, canonical in COLUMN_ALIASES.items():
        if alias in mapped and canonical not in mapped:
            mapped[canonical] = mapped[alias]
    return ImportRow(row_number=row.row_number, values=mapped)


async def _find_company_and_opportunity(
    company_name: str, db: AsyncSession
) -> tuple[Company | None, Opportunity | None]:
    result = await db.execute(
        select(Company).where(Company.name.ilike(company_name.strip()))
    )
    company = result.scalar_one_or_none()
    if not company:
        return None, None
    result = await db.execute(
        select(Opportunity).where(Opportunity.company_id == company.id).limit(1)
    )
    opportunity = result.scalars().first()
    return company, opportunity


def parse_import_file(filename: str | None, content: bytes) -> list[ImportRow]:
    suffix = Path(filename or "").suffix.lower()
    if suffix == ".csv":
        try:
            reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
            rows = [
                ImportRow(index, {_clean(key): _clean(value) for key, value in raw.items() if key})
                for index, raw in enumerate(reader, start=2)
            ]
        except UnicodeDecodeError as exc:
            raise ValueError("CSV files must be UTF-8 encoded") from exc
    elif suffix == ".xlsx":
        try:
            worksheet = load_workbook(BytesIO(content), read_only=True, data_only=True).active
            rows_iter = worksheet.iter_rows(values_only=True)
            headers = [_clean(value) for value in next(rows_iter, ())]
            rows = [
                ImportRow(
                    index,
                    {
                        headers[column]: _clean(value)
                        for column, value in enumerate(raw)
                        if column < len(headers) and headers[column]
                    },
                )
                for index, raw in enumerate(rows_iter, start=2)
            ]
        except Exception as exc:
            raise ValueError("The XLSX file could not be read") from exc
    else:
        raise ValueError("Only .csv and .xlsx files are supported")
    return [_canonicalise_row(row) for row in rows]


def _metadata_notes(row: ImportRow) -> str | None:
    details = [
        f"{label}: {row.values[field]}"
        for field, label in IMPORT_METADATA_FIELDS
        if row.values.get(field)
    ]
    return "[Lead import enrichment]\n" + "\n".join(details) if details else None


async def _decide(row: ImportRow, db: AsyncSession) -> ImportDecision:
    lead_id = row.values.get("lead_id", "")
    company_name = row.values.get("company", "")

    opportunity = None
    company_id = None

    if lead_id:
        opportunity = await db.get(Opportunity, lead_id)
        if not opportunity:
            return ImportDecision(row, "skip", "Unknown lead_id")
        if not opportunity.company_id:
            return ImportDecision(row, "skip", "Lead has no linked company", opportunity)
        company_id = opportunity.company_id
    elif company_name:
        company, opportunity = await _find_company_and_opportunity(company_name, db)
        if not company:
            return ImportDecision(row, "skip", f"Unknown company: {company_name}")
        company_id = company.id
        if not company_id:
            return ImportDecision(row, "skip", "Company has no id")
    else:
        return ImportDecision(row, "skip", "Missing lead_id or company")

    email = row.values.get("contact_email", "").lower()
    phone = row.values.get("contact_phone", "")
    if not email and not phone:
        return ImportDecision(
            row, "skip", "No email or phone to import", opportunity, None, company_id
        )
    if email and not EMAIL_PATTERN.match(email):
        return ImportDecision(row, "skip", "Invalid contact_email", opportunity, None, company_id)

    contacts = (
        (await db.execute(select(Contact).where(Contact.company_id == company_id)))
        .scalars()
        .all()
    )
    imported_contacts = [contact for contact in contacts if contact.source == IMPORT_SOURCE]
    if email:
        matching = next(
            (
                contact
                for contact in imported_contacts
                if _normalise(contact.email or "") == _normalise(email)
            ),
            None,
        )
        protected = next(
            (
                contact
                for contact in contacts
                if contact.source != IMPORT_SOURCE
                and _normalise(contact.email or "") == _normalise(email)
            ),
            None,
        )
        if protected:
            return ImportDecision(
                row, "skip", "Email belongs to a protected existing contact", opportunity, None, company_id
            )
        if matching:
            return ImportDecision(row, "update", "Update imported contact", opportunity, matching, company_id)
    if phone:
        matching = next(
            (
                contact
                for contact in imported_contacts
                if _normalise_phone(contact.phone_direct or contact.phone_mobile or "")
                == _normalise_phone(phone)
            ),
            None,
        )
        if matching:
            return ImportDecision(row, "update", "Update imported contact", opportunity, matching, company_id)
    name = row.values.get("contact_name", "")
    if name:
        first_name, last_name = _split_name(name)
        matching = next(
            (
                contact
                for contact in imported_contacts
                if _normalise(contact.first_name) == _normalise(first_name)
                and _normalise(contact.last_name) == _normalise(last_name)
            ),
            None,
        )
        if matching:
            return ImportDecision(row, "update", "Update imported contact", opportunity, matching, company_id)
    return ImportDecision(row, "create", "Create imported contact", opportunity, None, company_id)


def _result(decision: ImportDecision) -> dict[str, object]:
    return {
        "row": decision.row.row_number,
        "lead_id": decision.row.values.get("lead_id") or None,
        "company": decision.row.values.get("company") or None,
        "action": decision.action,
        "message": decision.message,
    }


async def preview_import(rows: list[ImportRow], db: AsyncSession) -> dict[str, object]:
    if not rows:
        raise ValueError("The import file contains no data rows")
    has_lead_id = any("lead_id" in row.values for row in rows)
    has_company = any("company" in row.values for row in rows)
    if not has_lead_id and not has_company:
        raise ValueError("The import file must include a lead_id or company column")
    decisions = [await _decide(row, db) for row in rows]
    return {
        "total_rows": len(decisions),
        "creates": sum(decision.action == "create" for decision in decisions),
        "updates": sum(decision.action == "update" for decision in decisions),
        "skips": sum(decision.action == "skip" for decision in decisions),
        "rows": [_result(decision) for decision in decisions],
    }


async def apply_import(rows: list[ImportRow], db: AsyncSession) -> dict[str, object]:
    preview = await preview_import(rows, db)
    affected_company_ids: set[str] = set()
    applied = 0
    for row in rows:
        decision = await _decide(row, db)
        if decision.action == "skip":
            continue
        company_id = decision.company_id or (
            decision.opportunity.company_id if decision.opportunity else None
        )
        if not company_id:
            continue
        values = row.values
        contact_name = values.get("contact_name", "")
        job_title = values.get("contact_job_title", "")
        email = values.get("contact_email", "").lower()
        phone = values.get("contact_phone", "")
        notes = _metadata_notes(row)
        if decision.action == "create":
            first_name, last_name = _split_name(
                contact_name or values.get("company", "") or "Unknown contact"
            )
            has_primary = bool(
                (
                    await db.execute(
                        select(Contact.id)
                        .where(
                            Contact.company_id == company_id,
                            Contact.is_primary.is_(True),
                        )
                        .limit(1)
                    )
                ).scalar_one_or_none()
            )
            decision.contact = Contact(
                company_id=company_id,
                first_name=first_name,
                last_name=last_name,
                job_title=job_title or None,
                email=email or None,
                phone_direct=phone or None,
                is_primary=not has_primary,
                notes=notes,
                source=IMPORT_SOURCE,
            )
            db.add(decision.contact)
        elif decision.contact:
            if contact_name:
                decision.contact.first_name, decision.contact.last_name = _split_name(contact_name)
            if job_title:
                decision.contact.job_title = job_title
            if email:
                decision.contact.email = email
            if phone:
                decision.contact.phone_direct = phone
            if notes:
                decision.contact.notes = notes
        affected_company_ids.add(company_id)
        applied += 1

    await db.flush()
    for company_id in affected_company_ids:
        opportunities = (
            (await db.execute(select(Opportunity).where(Opportunity.company_id == company_id)))
            .scalars()
            .all()
        )
        for opportunity in opportunities:
            await refresh_lead_scoring(opportunity, db)
    await db.commit()
    return {**preview, "applied": applied}
