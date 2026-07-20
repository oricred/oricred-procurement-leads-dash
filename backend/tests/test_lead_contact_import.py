from io import BytesIO

from openpyxl import Workbook

from app.schemas.contact import ContactCreate
from app.services.lead_contact_import import _metadata_notes, parse_import_file


def test_parse_csv_enriched_lead() -> None:
    rows = parse_import_file(
        "enriched.csv",
        b"lead_id,company,contact_email,contact_phone\n"
        b"lead-1,Example Ltd,person@example.com,012 345 6789\n",
    )
    assert len(rows) == 1
    assert rows[0].row_number == 2
    assert rows[0].values["lead_id"] == "lead-1"
    assert rows[0].values["contact_email"] == "person@example.com"


def test_parse_xlsx_enriched_lead() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["lead_id", "company", "contact_phone"])
    sheet.append(["lead-2", "Example Ltd", "021 555 0000"])
    content = BytesIO()
    workbook.save(content)
    rows = parse_import_file("enriched.xlsx", content.getvalue())
    assert rows[0].values["lead_id"] == "lead-2"
    assert rows[0].values["contact_phone"] == "021 555 0000"


def test_import_metadata_is_saved_in_notes() -> None:
    row = parse_import_file(
        "enriched.csv",
        b"lead_id,contact_source_url,contact_confidence,enrichment_date,research_notes\n"
        b"lead-1,https://example.com,High,2026-07-18,Public contact\n",
    )[0]
    notes = _metadata_notes(row)
    assert notes and "Source URL: https://example.com" in notes
    assert "Research notes: Public contact" in notes


def test_phone_only_contact_schema_is_supported() -> None:
    contact = ContactCreate(first_name="Example", last_name="Ltd", phone_direct="021 555 0000")
    assert contact.email is None
