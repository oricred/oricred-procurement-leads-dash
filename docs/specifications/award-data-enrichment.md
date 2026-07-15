# Award Data Enrichment Specification

> **Status:** Historical spec document. The code is the source of truth. The fixes described here are **fully implemented** — see `backend/app/jobs/tender_backfill.py`, `backend/app/jobs/award_check.py`, and `backend/app/clients/tsa_db.py`.

## 1. Problem Statement

### 1.1 Symptoms
The following fields are missing or incorrect in the opportunity/award UI:

| Location | Missing Fields | Impact |
|----------|---------------|--------|
| Company Intelligence | Province, Category | Shows `—` |
| Award Detail | Buyer name | Shows `—` |
| Relationship panel | Everything (award_count_12m, total_value, win_rate, relevance_score) | Shows `—` or N/A |
| Scoring | buyer_preference_score | Uses defaults (incorrect) |
| Kanban cards | Province, Category badges | Shows `—` |

### 1.2 Root Cause Analysis

**Core Bug**: In the TSA DB, `tender_awards.tender_id` stores the **UUID primary key** (`t.id`, e.g. `cmpy4g21z026gknogkvor2wqu`) of the `tenders` table, NOT the business identifier (`t.tender_id`, numeric e.g. `162433`).

The award_check job reads `raw["tender_id"]` from the award record (which is the UUID PK `t.id`) and passes these values as `tender_ids` to `tsa_db.query_tenders(filters={"tender_ids": ...})`. But `_build_tender_where` filters on `t.tender_id = ANY(:tender_ids)` — the **business identifier** column. Since the award's `tender_id` is a UUID (not a numeric business ID), no tenders are ever matched, `tender_by_api_id` is always empty, and all tenders are created as stubs with NULL metadata.

**Consequence**: 156 stub tenders exist with `api_id` = UUID strings, all with NULL `province`, `category_id`, and `buyer_org_id`. These are linked to 296 opportunities and 296 awards. Meanwhile, 1,753 "real" tenders (numeric `api_id`, full data) from the discovery job sit completely disconnected — no opportunities or awards reference them.

### 1.3 Data Flow Traced

```
TSA DB tender_awards                    TSA DB tenders
┌─────────────────┐                    ┌──────────────────────┐
│ a.tender_id      │ ← UUID PK (t.id)  │ t.id (UUID PK)       │
│ a.supplier_name  │                    │ t.tender_id (numeric) │ ← biz ID
│ a.amount         │                    │ t.province            │
│ a.award_date     │                    │ t.source_organization │
└─────────────────┘                    │ t.category (via join) │
       │                               └──────────────────────┘
       │ a.tender_id = UUID PK               │ t.tender_id = numeric
       ▼                                      ▼
award_check                          discovery job
 stores "cmpy4g21z..."              stores "162433"
 as Tender.api_id                   as Tender.api_id
 (stub, no data)                    (full data)
       │                                    │
       ▼                                    ▼
156 tenders (cm... api_id)        1,753 tenders (numeric api_id)
linked to 296 ops/awds            linked to 0 ops/awds
```

### 1.4 Affected Tables & Services

| Table | Problem |
|-------|---------|
| `tenders` | 156 stub records with NULL province/category/buyer_org_id |
| `opportunities` | All 296 linked to stub tenders; `tender_id` FK points to stub |
| `awards` | `buyer_org_id` = NULL (copied from stub tender) |
| `buyer_relationships` | Only 6 rows exist; should be ~296 |
| Scored fields | `buyer_preference_score`, `funding_suitability` computed with defaults |

---

## 2. Fix Plan

### Phase 1 — Fix the award_check Ingestion Pipeline

This prevents new data from being broken going forward.

#### 1a. Add `ids` filter to `_build_tender_where` in `tsa_db.py`

**File**: `backend/app/clients/tsa_db.py`

Add support for filtering by `t.id` (UUID PK) in `_build_tender_where()`:

```python
ids = filters.get("ids")
if ids:
    clauses.append("t.id = ANY(:ids)")
    params["ids"] = ids if isinstance(ids, list) else [ids]
```

Note: This is needed because `t.tender_id` (business ID) differs from `t.id` (UUID PK). The award `query_tenders` method currently has no way to filter by `t.id`.

#### 1b. Fix the Query in `award_check.py` — Use `ids` filter

**File**: `backend/app/jobs/award_check.py`

Change the tender metadata query from:
```python
raw_tenders = await tsa_db.query_tenders(
    filters={"tender_ids": tender_api_ids}, fields=TENDER_FIELDS,
    limit=max(len(tender_api_ids), 1),
)
```

To:
```python
raw_tenders = await tsa_db.query_tenders(
    filters={"ids": tender_api_ids}, fields=TENDER_FIELDS,
    limit=max(len(tender_api_ids), 1),
)
```

#### 1c. Add `id` to TENDER_FIELDS in `award_check.py`

```python
TENDER_FIELDS = [
    "id", "tender_id", "title", "description", "estimated_value", "province",
    "category_id", "closing_date", "source_organization_id",
    "source_organization", "type", "publication_date",
]
```

This ensures the result includes both `t.id` (UUID PK) and `t.tender_id` (business ID).

#### 1d. Fix `_upsert_tender_for_award` — Use Business ID as `api_id`

**File**: `backend/app/jobs/award_check.py`

The Tender's `api_id` should use the business identifier (`t.tender_id` from metadata), not the UUID PK from the award's `tender_id` field.

In `_upsert_tender_for_award`:

When creating a new tender, use `metadata.get("tender_id")` (numeric business ID) as the `api_id` rather than `raw.get("tender_id")` (UUID PK):

```python
api_id = metadata.get("tender_id") if metadata else None
if not api_id:
    api_id = raw.get("tender_id")  # fallback: use UUID as before
```

And in the tender lookup:
```python
tender = None
if api_id:
    tender = (await db.execute(select(Tender).where(Tender.api_id == api_id))).scalar_one_or_none()
```

Also ensure that when the tender already exists (created by discovery job), the `elif metadata:` condition actually executes (currently `metadata = metadata or {}` makes it falsy when metadata is empty, but with the fix metadata will contain real data so this will work).

Consider also storing `t.id` (UUID PK) somewhere for cross-reference, perhaps in `raw_payload`:
```python
tender.raw_payload = _sanitize({**metadata, "source_tender_uuid": raw.get("tender_id")})
```

This prevents future UUID→business ID mapping loss.

### Phase 2 — Backfill Existing Data

Quote: "Only the oricred database can be modified, the source database tenders-sa database is only read only."

Since we already have the stub tenders in oricred DB, we need to fix them in place.

#### 2a. Create a Backfill Script/Job

**File**: `backend/app/jobs/backfill_tender_data.py`

```python
"""
Backfills province, category_id, and buyer_org_id for stub tenders
created by the award_check job before the Phase 1 fix.
"""

async def backfill_stub_tenders():
    """
    1. Collect all tenders where province IS NULL (stub tenders).
       These have api_id = TSA DB UUID (cm...).
    
    2. Use TSADatabase to query the TSA DB tenders table filtered by
       t.id = ANY(stub_tender_api_ids).
    
    3. For each result:
       a. Find the matching stub tender in oricred DB.
       b. Update province, category_id, buyer_org_id from TSA DB data.
       c. Also store t.tender_id (business ID) in raw_payload for reference.
    
    4. For tenders that the TSA DB no longer has data for:
       Check if a "real" tender exists with matching title in oricred DB.
       If so, copy province/category/buyer_org from it.
    """
```

#### 2b. Lookup Strategy for Backfill

For each stub tender's `api_id` (= TSA DB `t.id` UUID):

1. Query TSA DB: `tsa_db.query_tenders(filters={"ids": [api_id]}, fields=TENDER_FIELDS)`
2. If found: copy `province`, `category_id` (via `tc.canonical_name`), `source_organization_id` (→ `buyer_org_id`)
3. If NOT found in TSA DB:
   - Check if any tender in oricred DB has matching title (fuzzy match)
   - If found, copy the data
4. After updating tender data, re-fetch organization from TSA DB via `_upsert_buyer_organization()`

#### 2c. Award buyer_org_id Fix

After backfilling tenders, update `awards.buyer_org_id` from the now-populated `tender.buyer_org_id`:

```python
# For each award linked to a backfilled tender:
award.buyer_org_id = tender.buyer_org_id
```

#### 2d. Recompute Relationships

After backfill, recompute `buyer_relationships` for all companies linked to opportunities:

```python
# For each opportunity with a backfilled tender:
rel = await compute_relationship(opp.company_id, org_id, db)
```

#### 2e. Recompute Scores

Recompute `buyer_preference_score` and `funding_suitability` for all opportunities:

```python
opp.buyer_preference_score = await compute_buyer_preference(opp.id, db)
opp.funding_suitability = await compute_funding_suitability(company.id, db)
await refresh_lead_scoring(opp, db, tender=tender, award=award, company=company, contacts=[])
```

### Phase 3 — Data Integrity Fixes

#### 3a. Handle Category ID → Name Resolution

Currently `_opportunity_to_read()` passes `tender.category_id` directly. After the fix, this will contain canonical names from TSA DB (e.g. "construction", "services: general") since `TENDER_FIELD_MAP` maps `category_id` to `tc.canonical_name`.

No changes needed if the canonical name is human-readable. If IDs are stored instead, add a resolution step:

In `_opportunity_to_read()`, resolve category name:
```python
category = None
if tender and tender.category_id:
    if tender.category_id in CATEGORY_NAMES:
        category = CATEGORY_NAMES[tender.category_id]
    else:
        cat_result = await db.execute(select(Category).where(Category.id == tender.category_id))
        cat = cat_result.scalar_one_or_none()
        category = cat.name if cat else tender.category_id
```

#### 3b. Buyer Organization Fallback

In `_opportunity_to_read()`, when `buyer_org_name` is still None but we have `tender.buyer_org_id`, log a warning. This is acceptable as the data should be populated after the backfill.

### Phase 4 — Relationship Endpoint Resilience

**File**: `backend/app/api/opportunities.py`, `GET /opportunities/{id}/relationship`

The current endpoint returns `None` when `tender.buyer_org_id` is None:

```python
if not tender or not tender.buyer_org_id:
    return None
```

After the backfill, this should rarely happen. But add a fallback for edge cases:

```python
if not tender or not tender.buyer_org_id:
    # Try to get buyer_org from the award's raw_payload or tender's raw_payload
    # as a last resort
    return None  # still return None, but log attempt
```

### Phase 5 — Verification & Testing

#### 5a. Unit Tests

- Test `_build_tender_where` with new `ids` filter key
- Test `_upsert_tender_for_award` with proper metadata
- Test `_opportunity_to_read` with fully populated tender data

#### 5b. Integration Test

- Run backfill on a subset of stub tenders
- Verify province, category, buyer_org appear in API response
- Verify relationship endpoint returns data with proper scores

#### 5c. Manual Verification

After deploying:
1. Open any opportunity modal
2. Verify Company Intelligence shows Province and Category
3. Verify Award Detail shows Buyer name
4. Verify Relationship panel shows award counts and relevance score
5. Verify kanban cards show province, category badges

---

## 3. Implementation Order

| Step | Description | Dependencies | Effort |
|------|-------------|-------------|--------|
| P1a | Add `ids` filter to `_build_tender_where` | None | Small |
| P1b | Change `award_check` to use `ids` filter | P1a | Small |
| P1c | Add `id` to TENDER_FIELDS | None | Trivial |
| P1d | Fix `_upsert_tender_for_award` api_id | P1b, P1c | Medium |
| P2a | Backfill stub tenders from TSA DB | P1a, P1c | Medium |
| P2b-c | Copy data, update awards | P2a | Medium |
| P2d-e | Recompute relationships & scores | P2b-c | Medium |
| P3 | Category resolution (if needed) | P2 | Small |
| P4 | Relationship endpoint resilience | P2 | Small |
| P5 | Tests & verification | All above | Medium |

Total estimated effort: **2-3 days** for a single developer.

## 4. Rollout Plan

1. **Deploy Phase 1** (pipeline fix) to prevent new broken data
2. **Run backfill script** (Phase 2) to fix existing data
3. **Deploy Phase 3-4** (frontend resilience)
4. **Verify** all fields populate correctly

### Rollback

If issues arise:
- Phase 1 change is additive (new filter key) — existing behavior unchanged
- Backfill is a one-time script — can be reverted by re-running with nulls
- Category resolution and relationship changes are backward-compatible
