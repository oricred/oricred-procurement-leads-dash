# Phase 1B — SOE / Gazette Gap-Fill

**Status:** Approved specification (sequenced after Phase 1, not parallel)

**Activation condition:** Sustained, material rate of past-due tenders in the Past-Due Queue (§2/§6 of Phase 1). Operations team to monitor and signal go-ahead.

---

## Objective

When the Award-Timing Model produces a material rate of past-due tenders (tenders past their expected award window with no award found), Phase 1B investigates and bridges the gap: SOEs publish awards on their internal portals before those awards appear in the Tenders-SA / OCPO data. This phase builds the targeted checks and OCPO Gazette parsing pipeline to recover those "missing" awards.

---

## 1. Research Phase (pre-engineering)

Before any code is written, map per SOE:

| SOE | Internal Portal URL | Award Publication Format | Typical Internal→OCPO Lag | Notes |
|---|---|---|---|---|
| Transnet | (TBD) | PDF / HTML table | (TBD) | Likely the highest-volume gap |
| Eskom | (TBD) | PDF / HTML table | (TBD) | |
| SANRAL | (TBD) | PDF / HTML table | (TBD) | |
| Prasa | (TBD) | PDF / HTML table | (TBD) | |
| Denel | (TBD) | PDF / HTML table | (TBD) | |

**Deliverable:** A per-SOE research brief document covering URL, format, update cadence, and any access restrictions (CAPTCHA, login wall, etc.).

---

## 2. Architecture

Phase 1B runs as a **physically separate microservice** from the Phase 1 dashboard. Rationale:

- Batch nature and parsing fragility can't affect live pipeline uptime.
- PDF/HTML parsing is a different operational profile (error-prone, needs manual QA).
- Can be scaled independently or paused if SOE portals change format.

```
Past-Due Queue (Phase 1 DB)
        │
        ▼
SOE Portal Checker (microservice)
        │
   ┌────┴────┐
   ▼         ▼
Award      No award
found      found on portal
   │         │
   ▼         ▼
Write award  Flag for OCPO Gazette check
record to   (if OCPO pipeline is running)
Phase 1 DB  │
            ▼
         OCPO Gazette
         Microservice
            │
       ┌────┴────┐
       ▼         ▼
    Award      No match
    found      → manual review queue
```

---

## 3. SOE Portal Checker

### 3.1 Input

Tenders from the Past-Due Queue where the buyer organization is a known SOE.

### 3.2 Per-SOE Adapter

Each SOE gets a dedicated adapter module:

```python
class SOEPortalAdapter(ABC):
    @abstractmethod
    def search_by_tender_reference(self, ref: str) -> list[AwardResult]: ...
    @abstractmethod
    def search_by_organization(self, org: str, date_range: tuple[date, date]) -> list[AwardResult]: ...
```

**Example adapters:**
- `TransnetAdapter` — scrape HTML table from Transnet's procurement portal
- `EskomAdapter` — scrape PDF listing from Eskom's tender bulletin
- `GenericHtmlTableAdapter` — fallback for portals with a common HTML-table layout

### 3.3 Output

`AwardResult` schema:

| Field | Type | Description |
|---|---|---|
| `source` | string | e.g. `"transnet_portal"` |
| `tender_reference` | string | SOE's reference number |
| `award_date` | date | Date award was published on portal |
| `supplier_name` | string | Awarded supplier |
| `amount` | number \| null | Award value if published |
| `description` | string | Brief description |
| `source_url` | string | Direct URL to the award page |
| `confidence` | float | 0.0–1.0 (1.0 = exact match, lower = fuzzy) |

### 3.4 Scheduling

Run daily. Process all SOE-linked past-due tenders that haven't been checked in the last 24 hours.

### 3.5 Error Handling

- Portal down → retry next cycle, no alert (expected for SOE sites).
- Format change → log, alert admin, pause adapter for manual fix.
- CAPTCHA → skip, log as "requires manual check".

---

## 4. OCPO Gazette Microservice

### 4.1 Source

Office of the Chief Procurement Officer (OCPO) Gazette — published as ZIP archives containing PDF files on the National Treasury website.

### 4.2 Pipeline

```
Download latest ZIP
        │
        ▼
Extract PDF files
        │
        ▼
Parse each PDF:
  - OCR if scanned (Tesseract / AWS Textract)
  - Extract award entries (entity, ref, supplier, amount, date)
        │
        ▼
Match extracted entries against:
  a) Past-Due Queue tenders (by reference / org + date)
  b) Phase 1 known tenders (by fuzzy reference match)
        │
        ▼
Output matched awards → Phase 1 DB
        ▼
Unmatched entries → "Unmatched Gazette Awards" review queue
```

### 4.3 PDF Parsing Strategy

| Document Type | Strategy |
|---|---|
| Born-digital PDF (text layer) | Direct text extraction (PyMuPDF / pdfplumber) |
| Scanned PDF (image) | OCR via Tesseract or AWS Textract |
| Mixed | Try text extraction first, fall back to OCR |

### 4.4 Entity Extraction

Regex + NLP approach:
1. Extract raw text blocks
2. Match against known entity names (SOEs, departments, municipalities) using fuzzy matching
3. Extract structured fields: reference number, supplier name, amount, date

### 4.5 Quality Gates

- Every batch run produces a report: total entries found, matched, unmatched.
- Unmatched entries reviewed by operations before next batch is processed.
- Precision target: >95% on matched entries (low recall acceptable — better to miss than to mismatch).

---

## 5. Data Integration with Phase 1

### 5.1 Award Records

Awards discovered by Phase 1B are written to the same `awards` table used by Phase 1, with an additional `source` field:
- `"tenders_api"` — normal Phase 1 path
- `"soe_portal"` — discovered via SOE portal checker
- `"ocpo_gazette"` — discovered via Gazette pipeline

### 5.2 Dedup

Before inserting, check for existing award by `(tender_reference, supplier_name, award_date)` to avoid duplicates when the same award is later published on Tenders-SA.

### 5.3 Feedback Loop

Awards found by Phase 1B are used to improve the Award-Timing Model:
- If award found on SOE portal before Tenders-SA, the actual `award_date` is used in model retraining.
- Track `soe_portal_lag` = days between SOE portal publication and Tenders-SA publication.

---

## 6. UI Changes

### 6.1 Award Source Indicator

On the kanban card and award detail panel, show the source badge:
- **TSA** — via Tenders-SA API
- **SOE** — via SOE portal check
- **Gazette** — via OCPO Gazette

### 6.2 Past-Due Queue View

Add a column showing which past-due tenders are being checked by Phase 1B:
- Pending SOE check
- Checked — no award on portal
- Checked — award found (linked)
- Flagged for Gazette review

---

## 7. Deliverables

1. Per-SOE research briefs (research deliverable)
2. SOE Portal Checker microservice with extensible adapter architecture
3. At least two concrete SOE adapters (Transnet + one other)
4. OCPO Gazette PDF pipeline (download → extract → parse → match)
5. Gazette parser with >95% precision on matched entries
6. Award dedup logic
7. Feedback loop integration with Phase 1 Award-Timing Model
8. Past-Due Queue status indicators in Phase 1 dashboard

---

## 8. Acceptance Criteria

- [ ] SOE Portal Checker correctly identifies awards published on target SOE portals for past-due tenders
- [ ] OCPO Gazette pipeline extracts structured award entries from Gazette PDFs
- [ ] Matched entries are inserted into Phase 1 `awards` table with correct `source` tag
- [ ] No duplicate award records created when same award later appears on Tenders-SA
- [ ] Award-Timing Model incorporates SOE/Gazette-discovered awards in next weekly refresh
- [ ] Past-Due Queue volume measurably decreases after Phase 1B goes live
- [ ] Precision on Gazette-matched entries meets >95% threshold
- [ ] Adapter architecture allows adding a new SOE in <2 days of research + implementation
