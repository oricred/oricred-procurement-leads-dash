# Remediation 04 — Query Performance

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** M1, M2, M3, M6, M7 (medium)
**Depends on:** spec 03 (the ingest changes touch the same loop as §2 here)

---

## Objective

Remove the five query patterns whose cost grows with data volume rather than with page size.
None of them is wrong today. All of them will arrive at once when the awards table grows, and
they are far cheaper to fix deliberately now than under a production incident.

The platform already contains the right pattern —
`opportunities._batch_load_opportunity_context` is a clean batch loader written to fix exactly
this class of problem in the list endpoints. This spec applies the same discipline to the four
places it was not applied.

---

## 1. Compute tender status in SQL (M1)

### 1.1 Current state

`list_tenders` pages the main query correctly, then calls a helper inside the row loop:

```python
# backend/app/api/tenders.py:191-193
items = []
for row in rows:
    status_val, is_watching, opp_id = await _compute_status_for_tender(str(row.id), db)
```

`_compute_status_for_tender` (lines 19-49) issues three sequential `SELECT`s — opportunity,
watchlist, past-due queue. A default 50-row page costs up to 151 round trips, and the `?page`
control makes that repeatable at will.

The odd part is that the correct SQL already exists twenty lines below, in
`_apply_status_filter`, which expresses all four states as correlated `EXISTS` subqueries. The
filter path is efficient; the projection path is not.

### 1.2 Change

Project the same information as scalar subqueries in the main `SELECT`, and derive the status
label from them with a `CASE`. Precedence must match the current helper exactly:
opportunity → awarded → watching → past due → not watched.

```python
# backend/app/api/tenders.py

def _status_columns():
    opportunity_id = (
        select(Opportunity.id)
        .where(Opportunity.tender_id == Tender.id, Opportunity.company_id.isnot(None))
        .order_by(Opportunity.created_at.desc())
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    watch_status = (
        select(WatchlistItem.status)
        .where(WatchlistItem.tender_id == Tender.id)
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    past_due_id = (
        select(PastDueQueue.id)
        .where(PastDueQueue.tender_id == Tender.id)
        .limit(1)
        .correlate(Tender)
        .scalar_subquery()
    )
    status = case(
        (opportunity_id.isnot(None), literal("opportunity")),
        (watch_status == "awarded", literal("awarded")),
        (watch_status == "watching", literal("watching")),
        (past_due_id.isnot(None), literal("past_due")),
        else_=literal("not_watched"),
    )
    is_watching = case(
        (opportunity_id.isnot(None), literal(False)),
        (watch_status.in_(("awarded", "watching")), literal(True)),
        else_=literal(False),
    )
    return (
        opportunity_id.label("opportunity_id"),
        status.label("status"),
        is_watching.label("is_watching"),
    )
```

The row loop then does no I/O:

```diff
- for row in rows:
-     status_val, is_watching, opp_id = await _compute_status_for_tender(str(row.id), db)
-     items.append(TenderItem(..., status=status_val, is_watching=is_watching, opportunity_id=opp_id))
+ for row in rows:
+     items.append(TenderItem(
+         ...,
+         status=row.status,
+         is_watching=row.is_watching,
+         opportunity_id=str(row.opportunity_id) if row.opportunity_id else None,
+     ))
```

Delete `_compute_status_for_tender`. Add these indexes if they are not already present:

```sql
CREATE INDEX IF NOT EXISTS idx_opportunities_tender_id ON opportunities (tender_id);
CREATE INDEX IF NOT EXISTS idx_past_due_tender_id      ON past_due_queue (tender_id);
-- watchlist_items.tender_id already carries a unique constraint
```

### 1.3 Behaviour to preserve

`_compute_status_for_tender` returns `is_watching = False` for the `opportunity` and
`past_due` states even though a watchlist row may exist. The `CASE` above reproduces that
exactly. Assert it in a test rather than trusting the reading — the Tenders page watch toggle
depends on it.

---

## 2. Batch the award ingest loop (M2)

### 2.1 Current state

`check_awards_for_watching` already batch-fetches tenders, companies, and bidders from
Tenders-SA before the loop. Inside the loop it then issues, per award:

| Line | Query | Target |
|------|-------|--------|
| 143 / 146 | tender lookup by `api_id` (up to two) | local |
| 110 | company lookup by `api_id` | local |
| 314 | award lookup by `api_id` | local |
| 337 | watchlist lookup by `tender_id` | local |
| 342 | opportunity lookup by `award_id` | local |
| 185 (via `_upsert_buyer_organization`) | organisation fetch | **Tenders-SA** |

At the 5,000-award page limit that is roughly 30,000 local queries and 5,000 round trips to
the external read-only database per run — for an organisation set that is usually a few dozen
distinct values repeated over and over.

### 2.2 Change — hoist the organisation fetch

`_upsert_buyer_organization` is called per award but depends only on `tender.buyer_org_id`.
Resolve the distinct set once, after the tenders are upserted and before opportunities are
created:

```python
async def _sync_buyer_organizations(db, tsa_db: TSADatabase, org_ids: set[str], now) -> None:
    """Fetch every buyer organisation for this batch in one query."""
    if not org_ids:
        return
    try:
        rows = await tsa_db.query_organizations(
            filters={"ids": sorted(org_ids)},
            fields=ORGANIZATION_FIELDS,
            limit=max(len(org_ids), 1),
        )
    except RECOVERABLE as exc:
        logger.warning("buyer_org_batch_failed", count=len(org_ids), error=str(exc))
        return
    for org in rows:
        await db.merge(Organization(
            id=org["id"],
            name=org.get("name") or org["id"],
            organization_type=org.get("organization_type"),
            contact_email=org.get("contact_email"),
            contact_phone=org.get("contact_phone"),
            contact_website=org.get("website"),
            contact_email_is_role_based=org.get("contact_email_is_role_based"),
            confidence_score=org.get("confidence_score"),
            raw_payload=_sanitize(org),
            last_refreshed_at=now,
        ))
```

5,000 remote queries become one.

### 2.3 Change — preload the four local tables

Before the loop, load every row the batch could touch, keyed for O(1) lookup:

```python
@dataclass
class IngestCache:
    tenders_by_api_id: dict[str, Tender]
    companies_by_api_id: dict[str, Company]
    awards_by_api_id: dict[str, Award]
    watches_by_tender_id: dict[str, WatchlistItem]
    opportunity_award_ids: set[str]


async def _preload(db, raw_awards: list[dict], tender_by_api_id: dict) -> IngestCache:
    award_api_ids = {_award_api_id(raw) for raw in raw_awards}
    tender_keys = {
        key
        for raw in raw_awards
        for key in (
            str(raw.get("tender_id") or ""),
            str((tender_by_api_id.get(str(raw.get("tender_id"))) or {}).get("tsa_reference") or ""),
        )
        if key
    }
    ...
```

Each lookup inside the loop then reads the cache and falls back to an insert, and newly
created rows are written back into the cache so later awards in the same batch see them. The
`await db.flush()` calls that currently exist to make new rows visible to the next query stay,
because the cache is authoritative only for rows this run has seen.

> **Ordering note.** `_preload` must run *after* the Tenders-SA metadata fetch, because tender
> keys depend on it, and *before* the first insert. Guard against the batch containing two
> awards for the same new tender — the cache write-back is what prevents the duplicate insert
> that a naive preload would allow.

### 2.4 Target

A 5,000-award run should issue roughly 10 local queries plus one insert/update batch, and 4
remote queries. Add a counting assertion to the test so a regression is visible:

```python
async def test_ingest_query_count_is_independent_of_batch_size(query_counter):
    await check_awards_for_watching()          # 10 awards
    small = query_counter.total
    query_counter.reset()
    await check_awards_for_watching()          # 500 awards
    assert query_counter.total < small * 3     # not 50x
```

---

## 3. Bound the corrupted-date scan (M3)

### 3.1 Current state

```python
# backend/app/jobs/award_check.py:419-425
extras = await db.execute(
    select(Award).where(
        Award.raw_payload.isnot(None),
        Award.award_date.isnot(None),
        Award.award_date <= now,
    )
)
for award in extras.scalars().all():
    payload = award.raw_payload or {}
    raw_date = payload.get("award_date") if isinstance(payload, dict) else None
    ...
    if raw_year > MAX_VALID_YEAR:
        result.append(award)
```

This selects **every** healthy award, materialises all of them, and filters in Python by
re-parsing the raw JSON year. It runs at 04:00 daily and grows linearly and permanently.

`fix_corrupted_award_dates` then issues a per-row tender query (line 460) whose result is
assigned and never used — `ruff F841` flags it.

### 3.2 Change — record the resolution, then scan only what changed

Add a column recording how each award's date was resolved. Spec 03 §1.2 already computes it.

```python
# backend/app/models/award.py
date_source: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
# one of: "source" | "created_at" | "discovered_at" | "now"
```

```python
# backend/app/database.py — AWARD_COLUMNS
"date_source": "VARCHAR(16)",
```

The daily job then has a cheap predicate:

```python
async def find_corrupted_award_dates(db=None) -> list[Award]:
    """Awards whose date is missing, in the future, or was synthesised."""
    ...
    result = await db.execute(
        select(Award).where(
            or_(
                Award.award_date.is_(None),
                Award.award_date > now,
                Award.date_source.notin_(("source",)),
                Award.date_source.is_(None),      # pre-migration rows, backfilled once
            )
        )
        .order_by(Award.discovered_at.desc())
        .limit(REPAIR_BATCH_SIZE)
    )
    return list(result.scalars().all())
```

`REPAIR_BATCH_SIZE = 5_000` bounds each run. Rows repaired to a source-backed date get
`date_source = "source"` and drop out of the scan permanently, so the working set shrinks
rather than grows.

### 3.3 Change — delete the unused query

```diff
  for award in rows:
      original = award.award_date
-
-     t_result = await db.execute(select(Tender).where(Tender.id == award.tender_id))
-     tender = t_result.scalar_one_or_none()
-
      recovered = _resolve_award_date(...)
```

### 3.4 One-off backfill

Existing rows have `date_source = NULL`. A single management command sets it by re-running the
resolver against `raw_payload`, in batches, so the first scheduled run after deploy is not
unbounded:

```bash
python -m app.cli backfill-date-source --batch-size 5000
```

---

## 4. Paginate the list endpoints (M6)

### 4.1 Current state

| Endpoint | Pagination | Polled by |
|----------|-----------|-----------|
| `GET /opportunities` (`opportunities.py:176`) | none | `PipelinePage` every 15 s (`PipelinePage.tsx:115`) |
| `GET /leads` (`leads.py:23`) | none | `LeadsPage` on filter change |
| `GET /leads/export` (`leads.py:96`) | none — by design | on demand |
| `GET /past-due` (`past_due.py:15`) | none | `PastDuePage` |
| `GET /watchlist` (`watchlist.py:20`) | none | Discover → Watching tab |

Every one returns all matching rows with full nested context — contacts included. The awards
and tenders browsers already do this correctly with `page` / `page_size`; the pipeline and
lead endpoints were never given the same treatment.

### 4.2 Change — server side

Adopt the existing convention from `awards.py:117` verbatim so the frontend helpers are shared:

```python
page: int = Query(1, ge=1),
page_size: int = Query(100, ge=1, le=500),
...
total = await db.scalar(select(func.count()).select_from(q.subquery())) or 0
rows = (await db.execute(q.offset((page - 1) * page_size).limit(page_size))).scalars().all()
return OpportunityList(items=items, total=total, page=page, page_size=page_size)
```

`OpportunityList` gains `page` and `page_size`, matching `AwardsList` and `TendersList`.
`total` changes meaning from "number of items returned" to "number of matching rows" — which
is what the header count in `Layout.tsx:117` was already trying to show.

`GET /leads/export` deliberately keeps no page limit; it is a deliberate full extract. Bound it
by row count instead and refuse politely past the ceiling:

```python
EXPORT_ROW_LIMIT = 50_000
if total > EXPORT_ROW_LIMIT:
    raise HTTPException(
        status_code=413,
        detail=f"That filter matches {total:,} leads. Narrow it to {EXPORT_ROW_LIMIT:,} or fewer.",
    )
```

### 4.3 Change — the pipeline board

The board is the reason this matters: it re-requests every opportunity in the system on a
15-second timer. Two changes:

1. **Fetch per column.** Each kanban column already knows its stage set. Request
   `?stage=<stage>&page_size=50` per column with its own query key, so a busy `new_lead`
   column does not force the whole board to re-download.
2. **Slow the poll and pause it when hidden.**

```typescript
const { data } = useQuery({
  queryKey: ['opportunities', stage],
  queryFn: async () => (await opportunities.list({ stage, page_size: 50 })).data,
  refetchInterval: () => (document.visibilityState === 'visible' ? 60_000 : false),
  refetchOnWindowFocus: true,
});
```

15 seconds was never a product requirement — award ingest runs every 30 minutes. A 60-second
poll plus refetch-on-focus is strictly more responsive to the operator's actual attention.

> **Optimistic-update note.** `dndTransition.onMutate` writes to `queryClient` under the key
> `['opportunities']`. When the key gains a stage segment, the optimistic update must move the
> card between two caches — remove from the source stage's list, add to the target's. Keep the
> existing snapshot-and-rollback shape; only the number of caches touched changes.

### 4.4 Change — the remaining three

`/past-due` and `/watchlist` take the same `page` / `page_size` treatment. `/past-due`
additionally needs its `Opportunity` join fixed: it outer-joins on `tender_id`, which is not
unique, so a tender with two opportunities yields two rows for one past-due entry. Replace the
join with the same correlated scalar subquery used in `watchlist.py:24-34`.

---

## 5. Fix historical contacts (M7)

### 5.1 Current state

```python
# backend/app/api/historical_contacts.py:33-58
q = (
    select(HistoricalContact, Company)
    .join(Company, Company.id == HistoricalContact.company_id)
    .order_by(...)
    .limit(limit)          # <- limit applied here
)
...
for historical, company in rows:
    contact_result = await db.execute(          # <- N+1, up to 500 deep
        select(Contact).where(Contact.company_id == company.id)...
    )
    contacts = contact_result.scalars().all()
    sufficiency = classify_company_contacts(contacts)
    if contactability == "contactable" and sufficiency != "sufficient":
        continue                                 # <- filter applied here
```

Two problems in one loop: a per-row contact query, and the main filter applied *after* the row
limit. Asking for 100 contactable companies can return four, with no indication that the list
was truncated before filtering.

### 5.2 Change — batch the contacts, filter in SQL

Contact sufficiency is derived from whether any company contact has an email or a phone —
which is expressible as an `EXISTS`:

```python
has_contactable = exists(
    select(Contact.id).where(
        Contact.company_id == Company.id,
        or_(
            Contact.email.isnot(None),
            Contact.phone_direct.isnot(None),
            Contact.phone_mobile.isnot(None),
        ),
    )
)
has_any_contact = exists(
    select(Contact.id).where(Contact.company_id == Company.id)
)

if contactability == "contactable":
    q = q.where(has_contactable)
elif contactability == "needs_contact":
    q = q.where(~has_contactable)
```

with the limit applied after the filter. The contacts themselves are then batch-loaded for the
page's companies only:

```python
company_ids = [c.id for _, c in rows]
contacts_by_company: dict[str, list[Contact]] = defaultdict(list)
for c in (await db.execute(
    select(Contact).where(Contact.company_id.in_(company_ids))
    .order_by(Contact.is_primary.desc(), Contact.last_name, Contact.first_name)
)).scalars():
    contacts_by_company[c.company_id].append(c)
```

`classify_company_contacts` and `choose_primary_contact` then run in Python against the
preloaded lists, unchanged.

> **Consistency requirement.** The `EXISTS` predicate and `classify_company_contacts` must
> agree on what "contactable" means, or the filter and the badge will contradict each other.
> Both currently reduce to "has email or phone_direct or phone_mobile, on a company contact".
> Add a test that asserts the two agree over a fixture covering all four combinations.

### 5.3 Also add `page` / `page_size`

`limit` alone gives no way to reach page two. Follow the `awards.py` convention here as well.

---

## 6. Files to change

| File | Change |
|------|--------|
| `backend/app/api/tenders.py` | §1.2 — status columns in SQL, delete `_compute_status_for_tender` |
| `backend/app/jobs/award_check.py` | §2.2 `_sync_buyer_organizations`; §2.3 `_preload`; §3.2 `date_source`; §3.3 delete dead query |
| `backend/app/models/award.py` | §3.2 — `date_source` column |
| `backend/app/database.py` | §1.2 indexes; §3.2 `AWARD_COLUMNS` entry |
| `backend/app/api/opportunities.py` | §4.2 — pagination |
| `backend/app/api/leads.py` | §4.2 — pagination, export ceiling |
| `backend/app/api/past_due.py` | §4.4 — pagination, fix the duplicating join |
| `backend/app/api/watchlist.py` | §4.4 — pagination |
| `backend/app/api/historical_contacts.py` | §5.2 — `EXISTS` filter, batch contacts; §5.3 pagination |
| `backend/app/schemas/opportunity.py` | §4.2 — `page`, `page_size` on `OpportunityList` |
| `backend/app/cli.py` | §3.4 — `backfill-date-source` |
| `frontend/src/pages/PipelinePage.tsx` | §4.3 — per-stage queries, poll interval, optimistic update |
| `frontend/src/pages/LeadsPage.tsx` | §4.2 — pagination controls |
| `frontend/src/services/api.ts` | §4 — page params on `opportunities.list`, `leads.list` |

---

## 7. Acceptance criteria

- [ ] `GET /tenders?page_size=50` issues a constant number of queries regardless of page size
- [ ] Tender status values are byte-identical to the current implementation across a fixture covering all five states
- [ ] `is_watching` is `false` for a tender in the `opportunity` and `past_due` states, as today
- [ ] A 500-award ingest issues fewer than three times the queries of a 10-award ingest
- [ ] A batch containing two awards for the same new tender creates one tender row
- [ ] Buyer organisations are fetched from Tenders-SA once per run, not once per award
- [ ] `find_corrupted_award_dates` no longer selects healthy awards
- [ ] An award repaired to a source-backed date does not reappear in the next run's scan
- [ ] `GET /opportunities` and `GET /leads` accept `page` and `page_size` and report a true `total`
- [ ] The pipeline board stops polling while the tab is hidden and refetches on focus
- [ ] Dragging a card between columns still updates optimistically and rolls back on a 409
- [ ] `GET /historical-contacts?contactability=contactable&page_size=100` returns 100 rows when 100 exist
- [ ] The contactability filter and the displayed sufficiency badge never disagree

---

## 8. Deferred scope

- Caching the dashboard stats query. It is three aggregates on a 30-second poll; measure
  before adding Redis, which is configured (`ORICRED_REDIS_URL`) but unused.
- Materialising lead priority score as a sorted index rather than recomputing on write.
- Cursor-based pagination for the frontend tables. Offset is adequate at these page sizes and
  the UI has no infinite scroll.
- Server-side aggregation for kanban column counts, so the board can show a total per column
  without fetching every card.
