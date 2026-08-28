# Remediation 03 — Ingestion Correctness

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** H1, H2 (high), M4, M5, M10 (medium), L4 (hygiene)
**Depends on:** spec 01 §2 (the exception-handling rule applies here too)

---

## Objective

Make the two ingestion jobs produce complete and correct results. Every finding in this spec
is a *silent* failure — the job reports success, the row counts look plausible, and the data is
quietly wrong or missing. None of them would be noticed without reading the code.

---

## 1. Repair the award ingest cursor (H1)

### 1.1 Current state

`check_awards_for_watching` maintains an incremental cursor in `award_ingestion_state`:

```python
# backend/app/jobs/award_check.py:252-253
state = await db.get(AwardIngestionState, "tenders_sa")
since = now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS) if backfill else (
    state.latest_award_at if state and state.latest_award_at
    else now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS)
)
```

The cursor is advanced from the *resolved* award date:

```python
# :326-334
award.award_date = _resolve_award_date(
    raw.get("award_date"), award.source_created_at, award.discovered_at, now,
)
timestamp = award.award_date
if timestamp:
    ingested_award_timestamps.append(timestamp)

# :367-375
valid_timestamps = [ts for ts in ingested_award_timestamps if ts <= now]
latest_award_at = max(valid_timestamps)
```

`_resolve_award_date` is documented as never returning `None`, and its last two branches are
`source_created_at` and `discovered_at` — and `discovered_at` is `now` for a freshly ingested
row. So a **single** award whose source date is unparseable pushes the cursor to today.

The next run then asks Tenders-SA for `a.award_date >= <today>`. Awards that were published
after that point but carry an older `award_date` are never seen again. The 30-day lookback
only applies when the state row is missing entirely, so the gap is permanent once it opens.

### 1.2 Change — separate the resolved date from the cursor

The award date is a *business* value that must never be null (that requirement is real and
stays). The cursor is a *sync* value that must never move past a date we have actually
confirmed. They should not be the same number.

Make `_resolve_award_date` report whether it trusted the source:

```python
# backend/app/jobs/award_check.py

@dataclass(frozen=True)
class ResolvedAwardDate:
    value: datetime
    from_source: bool      # True only when the raw date parsed and passed validation


def _resolve_award_date(
    raw_date: Any,
    source_created_at: datetime | None,
    discovered_at: datetime,
    now: datetime,
) -> ResolvedAwardDate:
    """Resolve an award date. Never returns None.

    `from_source` distinguishes a date we read from Tenders-SA from one we
    synthesised. Only source-backed dates may advance the ingestion cursor —
    see spec remediation-03 section 1.
    """
    dt = parse_datetime(raw_date)
    if dt is not None and dt <= discovered_at:
        return ResolvedAwardDate(dt, from_source=True)

    if source_created_at is not None and source_created_at <= now:
        return ResolvedAwardDate(source_created_at, from_source=True)

    return ResolvedAwardDate(discovered_at if discovered_at <= now else now, from_source=False)
```

Only source-backed dates feed the cursor:

```diff
- timestamp = award.award_date
- if timestamp:
-     ingested_award_timestamps.append(timestamp)
+ resolved = _resolve_award_date(
+     raw.get("award_date"), award.source_created_at, award.discovered_at, now,
+ )
+ award.award_date = resolved.value
+ if resolved.from_source:
+     ingested_award_timestamps.append(resolved.value)
+ else:
+     synthesised_dates += 1
```

### 1.3 Change — always overlap

Even a correct cursor loses rows at the boundary when the source backfills. Re-read a fixed
window on every run; the upsert path is already idempotent by `api_id`.

```python
AWARD_INGEST_OVERLAP_DAYS = 3

if backfill or not (state and state.latest_award_at):
    since = now - timedelta(days=AWARD_INGEST_LOOKBACK_DAYS)
else:
    since = state.latest_award_at - timedelta(days=AWARD_INGEST_OVERLAP_DAYS)
```

### 1.4 Change — never let the cursor exceed the confirmed watermark

```python
if ingested_award_timestamps:
    latest = max(ingested_award_timestamps)
    # Guard against a source date in the future relative to this run.
    latest = min(latest, now)
    if not state:
        state = AwardIngestionState(source="tenders_sa", latest_award_at=latest)
        db.add(state)
    elif not state.latest_award_at or latest > state.latest_award_at:
        state.latest_award_at = latest
elif raw_awards:
    logger.warning(
        "award_cursor_not_advanced",
        awards_seen=len(raw_awards), synthesised_dates=synthesised_dates,
    )
```

A run that ingests rows but advances nothing is now visible in the logs rather than silently
either stalling or leaping forward.

### 1.5 Tests

```python
def test_unparseable_date_does_not_advance_the_cursor():
    """The H1 regression: one bad row must not move the watermark to today."""

def test_cursor_uses_the_newest_source_backed_date():

def test_since_includes_the_overlap_window():

def test_resolve_award_date_never_returns_none():
    """Existing behaviour that must not regress — the business rule stands."""
```

---

## 2. Fix the bidder key mismatch (H2)

### 2.1 Current state

Bidders are indexed by the Tenders-SA row UUID:

```python
# backend/app/jobs/award_check.py:296-303
tender_api_ids = list({str(raw["tender_id"]) for raw in raw_awards if raw.get("tender_id")})
...
for bidder in await tsa_db.query_bidders(tender_ids=tender_api_ids):
    bidders_by_tender[str(bidder["tender_id"])].append(bidder["name"])
```

`a.tender_id` joins to `t.id` (see `_build_award_where`, which emits
`JOIN tenders t ON t.id = a.tender_id`), so these keys are TSA row UUIDs.

They are read back with a different key:

```python
# :354-357
opp.related_bidders = [
    {"name": name, "inferred": False, "reason": "confirmed bidder"}
    for name in bidders_by_tender.get(tender.api_id, []) if name.lower() != supplier.lower()
] or None
```

`tender.api_id` is set in `_upsert_tender_for_award:149` to `biz_tender_id or award_tender_id`,
where `biz_tender_id = metadata.get("tender_id")` — the human-readable business reference from
`t.tender_id`, not the UUID. Whenever tender metadata was fetched, which is the normal path,
the two key spaces do not intersect and the lookup always misses.

Result: `related_bidders` is `None` for essentially every lead, and the "confirmed bidders"
panel in the opportunity modal has been blank since it shipped.

### 2.2 Change — look up by the key the map was built with

The award's own `raw["tender_id"]` is the UUID and is in scope at the call site:

```diff
+ award_tender_uuid = str(raw.get("tender_id") or "")
  opp.related_bidders = [
      {"name": name, "inferred": False, "reason": "confirmed bidder"}
-     for name in bidders_by_tender.get(tender.api_id, []) if name.lower() != supplier.lower()
+     for name in bidders_by_tender.get(award_tender_uuid, []) if name.lower() != supplier.lower()
  ] or None
```

### 2.3 Change — make the two identifiers impossible to confuse

The underlying problem is that `tender_id` names two different things. Rename at the boundary
where the values enter our code, so the mismatch becomes a type-level obviousness rather than
a naming coincidence:

- In `TENDER_FIELD_MAP`, alias `t.id` as `tsa_row_id` and `t.tender_id` as `tsa_reference`.
- In `BIDDER_FIELD_MAP`, alias `b.tender_id` as `tsa_row_id`.
- Keep `Tender.api_id` as the local business key, and add a short comment recording that it
  holds the *reference*, not the row ID.

This is a mechanical rename confined to `tsa_db.py`, `award_check.py`, `discovery.py`, and
`tender_backfill.py`. Do it in the same change as §2.2 so the fix cannot silently regress.

### 2.4 Test

```python
async def test_related_bidders_are_attached_to_the_new_opportunity():
    """The H2 regression: bidder map keys and lookup keys must agree.

    Award carries tender_id = <uuid>; tender metadata carries tender_id = 'RFQ-123'.
    The created opportunity must still list the two competing bidders.
    """
    ...
    assert {b["name"] for b in opp.related_bidders} == {"Rival One", "Rival Two"}
    assert all(b["inferred"] is False for b in opp.related_bidders)
```

---

## 3. Make offset pagination deterministic (M4)

### 3.1 Current state

Both ingestion loops page with `OFFSET` over a non-unique sort column.

| Query | Order by | Paged from |
|-------|----------|------------|
| `query_tenders` (`tsa_db.py:433`) | `t.created_at DESC` | `discovery.py:179-188`, 20 pages × 1,000 |
| `query_awards` (`tsa_db.py:524`) | `a.award_date ASC NULLS LAST` | `award_check.py:256-266`, 20 pages × 5,000 |

Neither column is unique. PostgreSQL is free to order tied rows differently between the
statements that fetch page 1 and page 2, so rows shift across the boundary and are read twice
or skipped entirely. With thousands of awards sharing an `award_date` — normal for bulk
publication — this is not a theoretical risk.

### 3.2 Change

Add the primary key as a final sort term in both queries:

```diff
- ORDER BY t.created_at DESC
+ ORDER BY t.created_at DESC, t.id DESC
```

```diff
- ORDER BY a.award_date {direction} NULLS LAST
+ ORDER BY a.award_date {direction} NULLS LAST, a.id {direction}
```

### 3.3 Follow-up — keyset pagination

A stable sort makes `OFFSET` correct but not cheap; `OFFSET 19000` still scans and discards
19,000 rows. Once §3.2 is in, switch both loops to keyset pagination:

```sql
WHERE (a.award_date, a.id) > (:last_award_date, :last_id)
ORDER BY a.award_date ASC, a.id ASC
LIMIT :limit
```

This is a behaviour-preserving change given a stable sort, and removes the `MAX_PAGES` ceiling
that currently silently truncates ingestion at 20,000 tenders / 100,000 awards with only a
`logger.warning`.

---

## 4. Stop the category join multiplying tender rows (M5)

### 4.1 Current state

```sql
-- tsa_db.py:426-435
SELECT {select_cols}
FROM tenders t
LEFT JOIN tender_category_relations tcr ON tcr.tender_id = t.id
LEFT JOIN tender_categories tc ON tc.id = tcr.category_id
LEFT JOIN source_organizations o ON o.id = t.source_organization_id
{where}
ORDER BY t.created_at DESC
LIMIT :limit OFFSET :offset
```

A tender in three categories yields three rows and consumes three slots of the page limit.
`count_tenders`, twelve lines below, correctly uses `COUNT(DISTINCT t.id)` — so the count and
the rows disagree with each other.

`discovery._process_tender` is idempotent (it returns 0 for an existing `api_id`), so the
duplicates do not corrupt data. They do silently reduce ingestion throughput by the average
category multiplicity, and they interact badly with §3's offset pagination.

### 4.2 Change — filter with `EXISTS`, project with a scalar subquery

Neither the category filter nor the category display value needs a row-multiplying join.

```sql
SELECT
  {select_cols},
  (SELECT tc.canonical_name
     FROM tender_category_relations tcr
     JOIN tender_categories tc ON tc.id = tcr.category_id
    WHERE tcr.tender_id = t.id
    ORDER BY tc.canonical_name
    LIMIT 1)                                   AS category_id
FROM tenders t
LEFT JOIN source_organizations o ON o.id = t.source_organization_id
{where}
ORDER BY t.created_at DESC, t.id DESC
LIMIT :limit OFFSET :offset
```

And in `_build_tender_where`, the category clauses become:

```python
categories = filters.get("category")
if categories:
    values = categories if isinstance(categories, list) else [categories]
    clauses.append(
        "EXISTS (SELECT 1 FROM tender_category_relations tcr "
        "JOIN tender_categories tc ON tc.id = tcr.category_id "
        "WHERE tcr.tender_id = t.id AND LOWER(tc.canonical_name) = ANY(:category))"
    )
    params["category"] = [c.lower() for c in values]

exclude_cats = filters.get("_exclude_categories")
if exclude_cats:
    values = exclude_cats if isinstance(exclude_cats, list) else [exclude_cats]
    clauses.append(
        "NOT EXISTS (SELECT 1 FROM tender_category_relations tcr "
        "JOIN tender_categories tc ON tc.id = tcr.category_id "
        "WHERE tcr.tender_id = t.id AND LOWER(tc.canonical_name) = ANY(:_exclude_cats))"
    )
    params["_exclude_cats"] = [c.lower() for c in values]
```

> **Behaviour change worth noting.** The current `!= ALL(...)` exclusion, evaluated against a
> joined row, excludes a *category row* rather than a *tender*. A tender in both
> `construction` and `cleaning` currently survives an exclude on `cleaning` via its other row.
> The `NOT EXISTS` form excludes the tender. The latter matches what the Admin filter UI says
> it does, and is the intended reading — flag it to the operator before deploying, because
> qualified-tender volume will drop slightly.

`count_tenders` keeps `COUNT(DISTINCT t.id)`, which is now redundant but harmless.

---

## 5. Make the sector filter treat missing data like its siblings (M10)

### 5.1 Current state

```python
# backend/app/services/qualification.py:44-54
class SectorFilter(FilterHandler):
    async def evaluate(self, tender, rules, db=None) -> FilterResult:
        cats = [tender.category_id] if tender.category_id else []
        for rule in rules:
            if rule.get("type") == "include":
                if not any(c in rule.get("values", []) for c in cats):
                    return FilterResult(passed=False, ...)
```

For a tender with no category, `cats` is `[]`, `any(...)` is `False`, and the tender is
rejected. Every sibling filter does the opposite:

| Filter | Missing field | Result |
|--------|---------------|--------|
| `ValueRangeFilter` | `estimated_value is None` | **passes** (line 32-33) |
| `ProvinceFilter` | `not tender.province` | **passes** (line 59-60) |
| `EntityTypeFilter` | no resolvable `org_type` | **passes** (line 79-80) |
| `SectorFilter` | no `category_id` | **fails** |

Given how often `category_id` is absent in source data, this quietly narrows discovery in a
way no operator asked for and none of them can see.

### 5.2 Change

Match the sibling convention, and make the choice configurable per rule so the strict reading
is still available:

```python
class SectorFilter(FilterHandler):
    async def evaluate(self, tender, rules, db=None) -> FilterResult:
        if not tender.category_id:
            # Missing data is not disqualifying, matching ValueRangeFilter and
            # ProvinceFilter. Set "on_missing": "fail" on the rule to opt out.
            if any(r.get("on_missing") == "fail" for r in rules):
                return FilterResult(
                    passed=False, failed_filter="sector", reason="Tender has no category",
                )
            return FilterResult(passed=True)

        cats = [tender.category_id]
        for rule in rules:
            if rule.get("type") == "include":
                if not any(c in rule.get("values", []) for c in cats):
                    return FilterResult(
                        passed=False, failed_filter="sector",
                        reason="Category not in include list",
                    )
            elif rule.get("type") == "exclude":
                if any(c in rule.get("values", []) for c in cats):
                    return FilterResult(
                        passed=False, failed_filter="sector",
                        reason="Category in exclude list",
                    )
        return FilterResult(passed=True)
```

`QualificationService.default_config()` is unchanged; the new key is optional and absent means
"pass".

### 5.3 Note on the two dead filters

`BEEFilter` and `RiskExclusionFilter` both return `passed=True` unconditionally while
`default_config()` ships rules for them (`min_level`, `max_forensic_score`,
`exclude_if_restricted`). The Admin filter UI therefore presents settings that do nothing.
Either implement them or remove their default rules — tracked in spec 07 §3 as dead
configuration rather than dead code.

---

## 6. Fix the `since` operator precedence (L4)

### 6.1 Current state

```python
# backend/app/clients/tsa_db.py:181-184
since = filters.get("since")
if since:
    clauses.append("t.publication_date >= :since OR t.created_at >= :since")
```

Clauses are joined with `" AND "`, and `OR` binds less tightly than `AND`, so the whole
predicate splits in half. Verified output:

```
WHERE LOWER(t.province) = ANY(:province)
  AND t.estimated_value >= :value_min
  AND t.publication_date >= :since
   OR t.created_at >= :since          <- every filter above is bypassed on this branch
```

The `until` clause immediately below is correctly parenthesised, which is what makes this
look like an oversight rather than a decision.

This is currently unreachable: the only callers that pass `since` for tenders are
`query_tenders_from_config`, which has no callers, and `discovery.py`, which passes
`closing_from` instead. It is a landmine, not an active bug.

### 6.2 Change

```diff
- clauses.append("t.publication_date >= :since OR t.created_at >= :since")
+ clauses.append("(t.publication_date >= :since OR t.created_at >= :since)")
```

### 6.3 Test

`test_tsa_db.py` already asserts on generated SQL, so this is a one-line addition — and the
test is worth writing for every multi-term clause in the builder, not just this one:

```python
@pytest.mark.parametrize("filters", [
    {"since": "2026-01-01"},
    {"until": "2026-01-01"},
    {"search": "road"},
    {"category": ["construction"], "province": ["gp"], "since": "2026-01-01"},
])
def test_every_or_clause_is_parenthesised(filters):
    where, _ = _build_tender_where(filters)
    # An OR at the top level of an AND-joined WHERE is always a precedence bug.
    depth = 0
    for token in where.split():
        depth += token.count("(") - token.count(")")
        if token == "OR":
            assert depth > 0, f"unparenthesised OR in: {where}"
```

---

## 7. Files to change

| File | Change |
|------|--------|
| `backend/app/jobs/award_check.py` | §1.2 `ResolvedAwardDate`; §1.3 overlap; §1.4 watermark guard; §2.2 bidder key |
| `backend/app/clients/tsa_db.py` | §2.3 field aliases; §3.2 sort tiebreaks; §4.2 category `EXISTS`; §6.2 parentheses |
| `backend/app/jobs/discovery.py` | §2.3 renamed fields; §3.2 pagination |
| `backend/app/jobs/tender_backfill.py` | §2.3 renamed fields |
| `backend/app/services/qualification.py` | §5.2 `SectorFilter` missing-data behaviour |
| `backend/tests/test_award_check.py` | §1.5, §2.4 |
| `backend/tests/test_tsa_db.py` | §4, §6.3 |
| `AGENTS.md` | Rewrite the "Award Date Domain Rules" section against §1.2 (see spec 07 §2) |

---

## 8. Acceptance criteria

- [ ] An award batch containing one unparseable date leaves the cursor at the newest source-backed date
- [ ] `_resolve_award_date` still never returns `None` for any input
- [ ] Two consecutive ingest runs with no new source data produce no new rows and no cursor movement
- [ ] A run that ingests rows but advances no cursor logs `award_cursor_not_advanced`
- [ ] A newly created opportunity lists the tender's other bidders in `related_bidders`
- [ ] The opportunity modal's competitor panel renders bidder names for a tender that has them
- [ ] `query_tenders` returns one row per tender regardless of how many categories it has
- [ ] `count_tenders` and `len(query_tenders(...))` agree for the same filters on a small fixture
- [ ] Paging through a fixture where every row shares a sort value returns each row exactly once
- [ ] A tender with no category passes the sector filter by default and fails only with `"on_missing": "fail"`
- [ ] No `OR` appears at the top level of any generated `WHERE` clause

---

## 9. Deferred scope

- Keyset pagination (§3.3). Ships after §3.2 proves the sort is stable.
- Implementing `BEEFilter` and `RiskExclusionFilter` (§5.3).
- Reconciling `Award.buyer_org_id` against the tender's organisation when the two disagree.
- A reconciliation job that compares local award counts against Tenders-SA totals per month
  and reports gaps. This is the control that would have surfaced H1 from the outside; worth
  its own spec once the cursor is trustworthy.
