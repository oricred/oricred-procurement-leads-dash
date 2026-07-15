# Phase 2b — UI Navigation, Awards Browser & Tenders Browser

> **Status:** Historical spec document. The code is the source of truth. This phase is **fully implemented** — see `backend/app/api/awards.py`, `backend/app/api/tenders.py`, `frontend/src/pages/DiscoverPage.tsx`, and related files.

**Status:** Approved for implementation
**Depends on:** Phase 2 (municipalities + CRM) — uses the same data models and API layer

---

## Objective

Address three gaps in the current frontend navigation and data visibility:

1. **No awards browser** — awards are only visible in the 7-day radar sidebar and per-opportunity modals. There is no way to browse, search, or filter all awards.
2. **No all-tenders view** — only watched tenders (Matching page) and tenders linked to opportunities (Pipeline) are visible. The full discovered tender set (49k records in TSA DB) has no dedicated UI.
3. **No cross-referencing between pages** — a tender in the Matching page has no link to its corresponding opportunity in the Pipeline (if an award was found). A user must manually search for it.

---

## 1. Navigation Restructure

### 1.1 Current Nav

| Label | Route | Purpose |
|-------|-------|---------|
| Pipeline | `/pipeline` | Kanban board for opportunity workflow |
| Watching | `/watching` | Tender award-timing tracking board |
| Past Due | `/past-due` | Past-due queue |
| Admin | `/admin` | Configuration (admin only) |

### 1.2 Proposed Nav

| Label | Route | Purpose | Change |
|-------|-------|---------|--------|
| Pipeline | `/pipeline` | Kanban board for opportunity workflow | No change |
| Matching | `/matching` | Qualified tenders with award-timing tracking + cross-links | Renamed from "Watching" |
| Awards | `/awards` | Browseable/filterable awards list | **New page** |
| Tenders | `/tenders` | Browseable/filterable tenders list | **New page** |
| Past Due | `/past-due` | Past-due queue | No change |
| Admin | `/admin` | Configuration (admin only) | No change |

### 1.3 Sidebar Visual

```
┌──────────────────────┐
│  Oricred             │
│  Procurement Intel   │
├──────────────────────┤
│  █ Pipeline          │  ← active state shown
│  ○ Matching          │
│  ○ Awards            │
│  ○ Tenders           │
│  ○ Past Due          │
│  ○ Admin             │  (admin only)
├──────────────────────┤
│  24 watching · 3 pd  │
│  142 opportunities   │
├──────────────────────┤
│  Sign out            │
└──────────────────────┘
```

### 1.4 Behavioral Change: Matching Page Scope

The Matching page query changes from `WatchlistItem.status IN ('watching', 'past_due')` to `WatchlistItem.status IN ('watching', 'awarded')`. Past-due items now appear **only** on the Past Due page (`/past-due`), not on Matching. This is intentional — Matching focuses on timeline tracking, Past Due is the resolution queue. The dashboard stats `total_watching` count in `dashboard.py` is unaffected (it already counts only `status == "watching"`).

---

## 2. Matching Page (rename + enhance from Watching)

### 2.1 What Changes

- Route renamed from `/watching` to `/matching`
- Page component renamed from `WatchingPage` to `MatchingPage`
- Nav label changes from "Watching" to "Matching"
- All existing Watching Board functionality preserved (timing windows, progress bars, status icons)
- **Addition:** cross-reference links to Pipeline opportunities
- **Addition:** "Awarded" subsection

### 2.2 Cross-Reference Link

When a tender in the Matching page has a corresponding opportunity in the Pipeline (i.e., an award was detected and an opportunity was created), the card gains a link.

**Multi-award tenders:** If a single tender has awards to multiple suppliers (each creating a separate opportunity), the link resolves to the first matching opportunity ordered by `created_at DESC`. This is acceptable because each award creates one opportunity per supplier company, and a Matching card represents one tender — the primary award (most recent) is the default link target. The tooltip can indicate "X opportunities available" when count > 1.

```
┌──────────────────────────────────────────────┐
│  R2.5M   Construction   GP                    │
│                                              │
│  Upgrade of National Road N2 Section           │
│  SANRAL                                      │
│                                              │
│  ████████████████░░░░  80%                    │
│  Awarded — Opened as opportunity              │
│  [→ Open in Pipeline]   ← NEW hyperlink      │
└──────────────────────────────────────────────┘
```

**Backend change:** The `GET /api/watchlist` response gets an `opportunity_id` field. If a `watchlist_item.tender_id` matches an `opportunity.tender_id`, include the most recent opportunity ID.

```python
# Addition to WatchlistItemRead schema
opportunity_id: str | None = None
opportunity_count: int = 0  # number of linked opportunities (for UI tooltip)
```

**Query change:**
```sql
SELECT w.*, o.id AS opportunity_id
FROM watchlist_items w
LEFT JOIN LATERAL (
    SELECT id FROM opportunities
    WHERE tender_id = w.tender_id AND company_id IS NOT NULL
    ORDER BY created_at DESC
    LIMIT 1
) o ON true
WHERE w.status IN ('watching', 'awarded')
```

SQLAlchemy equivalent using a correlated subquery:
```python
opportunity_subq = (
    select(Opportunity.id)
    .where(
        Opportunity.tender_id == WatchlistItem.tender_id,
        Opportunity.company_id.isnot(None),
    )
    .order_by(Opportunity.created_at.desc())
    .limit(1)
    .correlate(WatchlistItem)
    .scalar_subquery()
)
```

### 2.3 Awarded Tenders Section

Add a second section below the main grid showing **awarded** tenders (watched tenders where an award was found). Currently these disappear from the Watching Board once awarded. Instead, show them in a collapsible "Awarded" section at the bottom, with a badge linking to the Pipeline.

**Empty state:** If 0 awarded items exist, the section renders as `Awarded (0)` collapsed header with no list body.

### 2.4 Query Change for Matching Page

The current watchlist query in `app/api/watchlist.py` filters `WatchlistItem.status.in_(["watching", "past_due"])`. This changes to `WatchlistItem.status.in_(["watching", "awarded"])`.

The `opportunity_id` is resolved via the lateral/correlated subquery above. The `awarded` status items are separated at the frontend into their own "Awarded" section.

---

## 3. Awards Browser (new page)

### 3.1 Page Layout

```
┌──────────────────────────────────────────────────────────────┐
│  🏆 Awards                              [─] [filter bar]    │
│  56,085 total awards                                        │
├──────────────────────────────────────────────────────────────┤
│ ┌──────────┬──────────┬──────────┬──────────┬──────────────┐ │
│ │ Supplier │ Buyer    │ Value    │ Date     │ Link          │ │
│ ├──────────┼──────────┼──────────┼──────────┼──────────────┤ │
│ │ Acme     │ Eskom    │ R1.2M    │ 2026-06  │ → Opportunity │ │
│ │ BuildCo  │ Transnet │ R8.5M    │ 2026-06  │ → Opportunity │ │
│ │ ...      │ ...      │ ...      │ ...      │ ...           │ │
│ └──────────┴──────────┴──────────┴──────────┴──────────────┘ │
│ [< Prev] [1] [2] [3] ... [Next >]          [Page X of Y]   │
└──────────────────────────────────────────────────────────────┘
```

### 3.2 Filters

A collapsible filter bar above the table:

| Filter | Type | Source Column | Resolved To |
|--------|------|---------------|-------------|
| Supplier name | Text input (partial match) | `awards.supplier_name` | Full scan via ilike |
| Buyer org | Dropdown of `Organization.name` | `awards.buyer_org_id` | JOIN via FK |
| Date range (from/to) | Date picker range | `awards.award_date` | Indexed ✓ |
| Value range (min/max) | Number inputs | `awards.amount` | No index |
| Source | Dropdown (`tenders_api`, `municipal`) | `awards.source` | No index |
| Has opportunity | Toggle (yes/no) | EXISTS in opportunities | Subquery |

**Fallback for null buyer_org_id:** Display `"—"` in the table cell. When clicking the filter dropdown, null entries appear as `"(Unknown)"`.

### 3.3 Table Columns

| Column | Data Source | Behavior |
|--------|-------------|----------|
| Supplier name | `awards.supplier_name` | Clickable → sets supplier filter and re-queries |
| Buyer org | `Organization.name` (via LEFT JOIN `awards.buyer_org_id`) | Clickable → sets buyer filter and re-queries. Falls back to `"Unknown"` if null |
| Tender title | `tenders.title` (via LEFT JOIN `awards.tender_id`) | Truncated at 60 chars with tooltip |
| Value | `awards.amount` | Formatted as `R1.2M` / `R850K`, right-aligned, falls back to `"—"` if null |
| Award date | `awards.award_date` | Formatted as `14 Jun 2026`, falls back to `"—"` if null |
| BEE level | `awards.bee_level` | Badge, falls back to `"—"` if null |
| Link | Computed: `opportunity_id` | Icon link → `/pipeline?open={id}` if opportunity exists. Falls back to `"—"` if none |

### 3.4 API Endpoint

**New endpoint: `GET /api/awards`**

```python
@router.get("/awards")
async def list_awards(
    supplier: str | None = None,
    buyer_org_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    source: str | None = None,
    has_opportunity: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> AwardsList:
    ...
```

**Response schema:**

```python
class AwardItem(BaseModel):
    id: str
    supplier_name: str
    buyer_org_id: str | None = None
    buyer_org_name: str | None = None
    tender_title: str | None = None
    amount: float | None = None
    award_date: datetime | None = None
    bee_level: int | None = None
    source: str
    opportunity_id: str | None = None  # cross-link

class AwardsList(BaseModel):
    items: list[AwardItem]
    total: int
    page: int
    page_size: int
```

### 3.5 Backend Query

```python
from sqlalchemy import select, func, and_, or_, exists

query = (
    select(
        Award.id,
        Award.supplier_name,
        Award.buyer_org_id,
        Organization.name.label("buyer_org_name"),
        Tender.title.label("tender_title"),
        Award.amount,
        Award.award_date,
        Award.bee_level,
        Award.source,
        Opportunity.id.label("opportunity_id"),
    )
    .outerjoin(Tender, Award.tender_id == Tender.id)
    .outerjoin(Organization, Award.buyer_org_id == Organization.id)
    .outerjoin(
        Opportunity,
        and_(
            Opportunity.award_id == Award.id,
            Opportunity.company_id.isnot(None),
        ),
    )
)

# Apply filters dynamically
if supplier:
    query = query.where(Award.supplier_name.ilike(f"%{supplier}%"))
if buyer_org_id:
    query = query.where(Award.buyer_org_id == buyer_org_id)
if date_from:
    query = query.where(Award.award_date >= date_from)
if date_to:
    query = query.where(Award.award_date <= date_to)
if value_min is not None:
    query = query.where(Award.amount >= value_min)
if value_max is not None:
    query = query.where(Award.amount <= value_max)
if source:
    query = query.where(Award.source == source)
if has_opportunity is True:
    query = query.where(Opportunity.id.isnot(None))
elif has_opportunity is False:
    query = query.where(Opportunity.id.is_(None))

# Count query (uses a simplified subquery — may scan all rows without indexes)
total_query = select(func.count()).select_from(query.subquery())
total = await db.scalar(total_query) or 0

# Pagination
query = query.order_by(Award.award_date.desc().nullslast())
query = query.offset((page - 1) * page_size).limit(page_size)
rows = await db.execute(query)
```

**Performance note:** The count query uses `SELECT count(*) FROM (full_query_with_joins)`. This is acceptable at <60k rows with single-word text filters. If performance degrades (>2s response), replace with a separate simplified count query (filter-only, no JOINs).

**Database indexes to add:**
```sql
CREATE INDEX IF NOT EXISTS idx_awards_supplier_name ON awards(supplier_name);
CREATE INDEX IF NOT EXISTS idx_awards_buyer_org_id ON awards(buyer_org_id);
CREATE INDEX IF NOT EXISTS idx_awards_amount ON awards(amount);
CREATE INDEX IF NOT EXISTS idx_awards_source ON awards(source);
CREATE INDEX IF NOT EXISTS idx_awards_bee_level ON awards(bee_level);
```

### 3.6 Sidebar Radar Update

The AwardRadar sidebar component on the Pipeline page changes:

1. **Header change:** "7-Day Award Feed" → "Recent Awards" with a `[View All]` link → `/awards`
2. **Compact mode:** Same 7-day feed with the same cards
3. **Clickable cards:** Clicking a radar award card navigates to `/awards?supplier={supplier_name}` pre-filtered for that supplier. The `supplier` query param is passed to the AwardsPage which initializes the filter bar.
4. **Past-due counter** stays but links to `/past-due` instead of being a standalone stat

### 3.7 Frontend Route

```tsx
<Route path="awards" element={<AwardsPage />} />
```

### 3.8 Empty, Loading, and Error States

| State | UI |
|-------|----|
| **Loading** | Skeleton: 5 rows of shimmer placeholders, filter bar disabled |
| **Empty (no results)** | "No awards match your filters" with a "Clear filters" button. Illustrative icon. |
| **Error (API failure)** | Red alert banner: "Failed to load awards. Retry?" with retry button. TanStack Query handles retry. |

---

## 4. Tenders Browser (new page)

### 4.1 Page Layout

```
┌──────────────────────────────────────────────────────────────┐
│  📄 Tenders                             [─] [filter bar]    │
│  49,190 total tenders                                        │
├──────────────────────────────────────────────────────────────┤
│ ┌──────────┬──────────┬──────────┬──────────┬──────────────┐ │
│ │ Title    │ Buyer    │ Value    │ Closing  │ Status        │ │
│ ├──────────┼──────────┼──────────┼──────────┼──────────────┤ │
│ │ Road N2  │ SANRAL   │ R2.5M    │ 2026-07  │ 🟢 Watching   │ │
│ │ ...      │ ...      │ ...      │ ...      │ ...           │ │
│ └──────────┴──────────┴──────────┴──────────┴──────────────┘ │
│ [< Prev] [1] [2] [3] ... [Next >]          [Page X of Y]   │
└──────────────────────────────────────────────────────────────┘
```

### 4.2 Filters

| Filter | Type | Source Column | Resolved To |
|--------|------|---------------|-------------|
| Text search | Text input | `tenders.title` | Full scan via ilike |
| Buyer org | Dropdown of `Organization.name` | `tenders.buyer_org_id` | JOIN via FK |
| Province | Dropdown of distinct `tenders.province` | `tenders.province` | No index |
| Category | Dropdown of `Category.name` | `tenders.category_id` | JOIN via FK |
| Value range (min/max) | Number inputs | `tenders.estimated_value` | No index |
| Closing date range (from/to) | Date picker range | `tenders.closing_date` | No index |
| Status | Dropdown: `any`, `watching`, `awarded`, `past_due`, `opportunity`, `not_watched` | Computed (see §4.4) | Subquery-based |
| Has opportunity | Toggle (yes/no) | EXISTS in `opportunities` | Subquery |

**Dropdown data sources:** The buyer org and category dropdowns are populated once on page mount via dedicated endpoint calls (see §8.7). `tenders.province` distinct values are fetched from the backend on mount.

**Fallback for null buyer_org_id / category_id:** Display `"—"`. In dropdown filter, null entries appear as `"(Unknown)"`.

### 4.3 Table Columns

| Column | Data Source | Behavior |
|--------|-------------|----------|
| Tender title | `tenders.title` | Truncated at 60 chars. Hover shows full title in tooltip. No detail popover (deferred). |
| Buyer org | `Organization.name` (via LEFT JOIN) | Clickable → sets buyer filter. Falls back to `"—"` |
| Category | `Category.name` (via LEFT JOIN) | Clickable → sets category filter. Falls back to `"—"` |
| Province | `tenders.province` | Falls back to `"—"` |
| Estimated value | `tenders.estimated_value` | Formatted as `R2.5M` / `R850K`. Falls back to `"—"` |
| Closing date | `tenders.closing_date` | Formatted as date. Falls back to `"—"` |
| Status | Computed badge | Colored badge with icon (see §4.4) |
| Watch toggle | Button | Calls `POST /api/watchlist/toggle` optimistically |
| Link | Computed: `opportunity_id` or `is_watching` | Icon → `/pipeline?open={id}` or `→ Matching` |

### 4.4 Status Derivation

```python
# Priority order — first match wins:
async def _compute_status(tender_id: str, db) -> tuple[str, bool, str | None]:
    # Check opportunities (most authoritative — award found, in pipeline)
    opp = await db.execute(
        select(Opportunity.id).where(
            Opportunity.tender_id == tender_id,
            Opportunity.company_id.isnot(None),
        ).limit(1)
    )
    opp_id = opp.scalar_one_or_none()
    if opp_id:
        return ("opportunity", False, str(opp_id))

    # Check watchlist
    wl = await db.execute(
        select(WatchlistItem.status).where(
            WatchlistItem.tender_id == tender_id
        ).limit(1)
    )
    wl_row = wl.scalar_one_or_none()
    if wl_row == "awarded":
        return ("awarded", True, None)  # still is_watching
    elif wl_row == "watching":
        return ("watching", True, None)

    # Check past-due queue
    pd = await db.execute(
        select(PastDueQueue.id).where(
            PastDueQueue.tender_id == tender_id
        ).limit(1)
    )
    if pd.scalar_one_or_none():
        return ("past_due", False, None)

    return ("not_watched", False, None)
```

**Performance optimization for bulk:** For the full list query, status is computed in SQL via LEFT JOINs + subqueries rather than Python-per-row:

```python
status_opp_subq = (
    select(Opportunity.id)
    .where(
        Opportunity.tender_id == Tender.id,
        Opportunity.company_id.isnot(None),
    )
    .limit(1)
    .correlate(Tender)
    .scalar_subquery()
)

status_wl_subq = (
    select(WatchlistItem.status)
    .where(WatchlistItem.tender_id == Tender.id)
    .limit(1)
    .correlate(Tender)
    .scalar_subquery()
)

status_pd_subq = (
    select(PastDueQueue.id)
    .where(PastDueQueue.tender_id == Tender.id)
    .limit(1)
    .correlate(Tender)
    .scalar_subquery()
)
```

These subqueries are added to the SELECT list, then status is determined in Python by checking priority order. This avoids N+1 while keeping the logic explicit.

### 4.5 API Endpoint

**New endpoint: `GET /api/tenders`**

```python
@router.get("/tenders")
async def list_tenders(
    search: str | None = None,
    buyer_org_id: str | None = None,
    province: str | None = None,
    category_id: str | None = None,
    value_min: float | None = None,
    value_max: float | None = None,
    closing_from: date | None = None,
    closing_to: date | None = None,
    status: str | None = None,  # watching, awarded, past_due, not_watched, opportunity
    has_opportunity: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> TendersList:
    ...
```

**Status filter implementation** — uses WHERE EXISTS subqueries:

```python
if status == "watching":
    query = query.where(
        exists(
            select(WatchlistItem.id).where(
                WatchlistItem.tender_id == Tender.id,
                WatchlistItem.status == "watching",
            )
        )
    )
elif status == "opportunity":
    query = query.where(
        exists(
            select(Opportunity.id).where(
                Opportunity.tender_id == Tender.id,
                Opportunity.company_id.isnot(None),
            )
        )
    )
elif status == "awarded":
    query = query.where(
        exists(
            select(WatchlistItem.id).where(
                WatchlistItem.tender_id == Tender.id,
                WatchlistItem.status == "awarded",
            )
        )
    )
elif status == "past_due":
    query = query.where(
        exists(
            select(PastDueQueue.id).where(
                PastDueQueue.tender_id == Tender.id
            )
        )
    )
elif status == "not_watched":
    query = query.where(
        ~exists(
            select(WatchlistItem.id).where(
                WatchlistItem.tender_id == Tender.id
            )
        )
        . & ~exists(
            select(PastDueQueue.id).where(
                PastDueQueue.tender_id == Tender.id
            )
        )
        . & ~exists(
            select(Opportunity.id).where(
                Opportunity.tender_id == Tender.id,
                Opportunity.company_id.isnot(None),
            )
        )
    )
```

**Response schema:**

```python
class TenderItem(BaseModel):
    id: str
    title: str | None = None
    estimated_value: float | None = None
    province: str | None = None
    category_id: str | None = None
    category_name: str | None = None
    buyer_org_id: str | None = None
    buyer_org_name: str | None = None
    closing_date: datetime | None = None
    published_at: datetime | None = None
    tender_type: str | None = None  # national, provincial, municipal
    discovered_at: datetime | None = None
    status: str  # computed: not_watched, watching, awarded, past_due, opportunity
    is_watching: bool
    opportunity_id: str | None = None

class TendersList(BaseModel):
    items: list[TenderItem]
    total: int
    page: int
    page_size: int
```

**Note:** `description` is intentionally excluded from the schema. The table does not display it, and it's only needed for text search filtering (which already queries `tenders.description` server-side if search param is present). Adding it to the response would bloat payloads for no visible benefit.

**Database indexes to add:**
```sql
CREATE INDEX IF NOT EXISTS idx_tenders_title ON tenders(title);
CREATE INDEX IF NOT EXISTS idx_tenders_buyer_org_id ON tenders(buyer_org_id);
CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province);
CREATE INDEX IF NOT EXISTS idx_tenders_category_id ON tenders(category_id);
CREATE INDEX IF NOT EXISTS idx_tenders_estimated_value ON tenders(estimated_value);
CREATE INDEX IF NOT EXISTS idx_tenders_closing_date ON tenders(closing_date);
CREATE INDEX IF NOT EXISTS idx_tenders_tender_type ON tenders(tender_type);
```

### 4.6 Watch Toggle

Each row has a watch/unwatch button. Clicking calls:

```python
POST /api/watchlist/toggle
Authorization: Bearer <token>  # Requires JWT auth (same as all other endpoints)
Body: { "tender_id": "uuid-string" }
Response: { "is_watching": true }
```

**Backend behavior:**
- Requires JWT authentication (standard `Depends(get_current_user)`)
- Validates `tender_id` exists in `tenders` table → 404 if not
- If a `WatchlistItem` exists for this `tender_id`: delete it, return `is_watching: false`
- If no `WatchlistItem` exists: create one (status="watching", started_watching_at=now), compute expected award window via `AwardTimingService`, return `is_watching: true`
- **Past-due queue side effect:** If toggling ON a tender that is already in `past_due_queue`, the past-due entry is NOT removed (it represents historical past-due state). If toggling OFF, the `past_due_queue` entry IS removed (user is explicitly abandoning tracking).
- **Idempotent:** Toggling ON when already watching returns `is_watching: true` (no-op). Toggling OFF when not watching returns `is_watching: false` (no-op).

```python
@router.post("/toggle", response_model=WatchToggleResponse)
async def toggle_watchlist(
    body: WatchToggleRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate tender exists
    tender = await db.execute(select(Tender).where(Tender.id == body.tender_id))
    tender = tender.scalar_one_or_none()
    if not tender:
        raise HTTPException(status_code=404, detail="Tender not found")

    # Check existing watchlist item
    existing = await db.execute(
        select(WatchlistItem).where(WatchlistItem.tender_id == body.tender_id)
    )
    wl = existing.scalar_one_or_none()

    if wl:
        # Toggle OFF
        await db.delete(wl)
        # Also clean up past_due_queue
        pd = await db.execute(
            select(PastDueQueue).where(PastDueQueue.tender_id == body.tender_id)
        )
        pd_item = pd.scalar_one_or_none()
        if pd_item:
            await db.delete(pd_item)
        await db.commit()
        return WatchToggleResponse(is_watching=False)
    else:
        # Toggle ON
        timing = AwardTimingService(db)
        start, end = await timing.get_expected_window(
            tender.buyer_org_id, tender.category_id, tender.closing_date
        )
        db.add(WatchlistItem(
            tender_id=body.tender_id,
            status="watching",
            expected_window_start=start,
            expected_window_end=end,
            started_watching_at=datetime.now(timezone.utc),
        ))
        await db.commit()
        return WatchToggleResponse(is_watching=True)
```

### 4.7 Frontend Route

```tsx
<Route path="tenders" element={<TendersPage />} />
```

### 4.8 Empty, Loading, and Error States

| State | UI |
|-------|----|
| **Loading** | Skeleton: 5 rows of shimmer placeholders, filter bar disabled |
| **Empty (no results)** | "No tenders match your filters" with "Clear filters" button |
| **Empty (no tenders at all)** | "No tenders discovered yet. Run the discovery job from Admin > Jobs." with link |
| **Error (API failure)** | Red alert: "Failed to load tenders. Retry?" with retry button |

---

## 5. Cross-Referencing Links

### 5.1 Link Types

| Source Page | Target | Visual | Condition |
|-------------|--------|--------|-----------|
| Matching card (awarded) | Pipeline opportunity | `→ Open in Pipeline` link on card | `opportunity_id` is not null |
| Matching card (watching) | Tenders page | `→ View in Tenders` link on card | Always (link to /tenders) |
| Awards row (has opportunity) | Pipeline opportunity | Link icon in "Opportunity" column | `opportunity_id` is not null |
| Awards row (no opportunity, is_watching) | Matching page | `→ Matching` link | Tender is in watchlist with status "watching" |
| Tenders row (has opportunity) | Pipeline opportunity | Link icon in "Opportunity" column | `opportunity_id` is not null |
| Tenders row (watching) | Matching page | `→ Matching` link | `is_watching` is true |
| Pipeline opportunity | Tenders page (source tender) | "View Tender" link in OpportunityModal | `tender_id` is not null |

### 5.2 Navigation Helper

All cross-reference links navigate via React Router. To open a specific Pipeline opportunity from an external page, the Pipeline page accepts a query parameter:

```
/pipeline?open=opportunity_id_123
```

When this param is present, the OpportunityModal is opened automatically on page load. This same mechanism is used when clicking `→ Open in Pipeline` from any other page.

**Implementation in PipelinePage.tsx:**

```tsx
const searchParams = new URLSearchParams(location.search);
const openOppId = searchParams.get('open');

if (openOppId && data?.items) {
  const opp = data.items.find(o => o.id === openOppId);
  if (opp) setSelectedOpp(opp);
}
```

---

## 6. AwardRadar Sidebar Update

The existing AwardRadar sidebar on the Pipeline page is updated:

1. **Header change:** "7-Day Award Feed" → "Recent Awards" with a `[View All]` link → `/awards`
2. **Compact mode:** Same 7-day feed with the same cards
3. **Clickable cards:** Clicking a radar award card navigates to `/awards?supplier={supplier_name}` pre-filtered. The pathname changes but the sidebar filters on AwardsPage initialize from URL params.
4. **Past-due counter** stays but the count becomes a link to `/past-due`

---

## 7. Backend: Reference Data Endpoints

The Awards and Tenders filter dropdowns need reference data for buyer organizations and categories. Two lightweight endpoints are added:

### 7.1 GET /api/organizations

Returns all buyer organizations for the filter dropdown:

```python
class OrgRef(BaseModel):
    id: str
    name: str

@router.get("/organizations")
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Organization.id, Organization.name)
        .order_by(Organization.name)
    )
    return [OrgRef(id=r.id, name=r.name) for r in result.all()]
```

### 7.2 GET /api/categories

Returns all categories for the filter dropdown:

```python
class CategoryRef(BaseModel):
    id: str
    name: str

@router.get("/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Category.id, Category.name)
        .order_by(Category.name)
    )
    return [CategoryRef(id=r.id, name=r.name) for r in result.all()]
```

### 7.3 GET /api/tenders/provinces

Returns distinct province values for the filter dropdown:

```python
@router.get("/tenders/provinces")
async def list_tender_provinces(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Tender.province).distinct().where(Tender.province.isnot(None)).order_by(Tender.province)
    )
    return [r[0] for r in result.all()]
```

---

## 8. Frontend Implementation Plan

### 8.1 New Components

| Component | File | Purpose |
|-----------|------|---------|
| `AwardsPage` | `frontend/src/pages/AwardsPage.tsx` | Full awards browser with filters + paginated table |
| `TendersPage` | `frontend/src/pages/TendersPage.tsx` | Full tenders browser with filters + paginated table |
| `MatchingPage` | `frontend/src/pages/MatchingPage.tsx` | Renamed from `WatchingPage`, adds cross-links, awarded section |
| `FilterBar` | `frontend/src/components/FilterBar.tsx` | Reusable collapsible filter bar (used by Awards + Tenders) |
| `DataTable` | `frontend/src/components/DataTable.tsx` | Reusable paginated table with sortable columns |

### 8.2 Modified Components

| Component | Changes |
|-----------|---------|
| `WatchingPage` → `MatchingPage` | Rename; add `opportunity_id` link; add awarded section |
| `AwardRadar` | Add "View All" link to `/awards`; make cards clickable |
| `PipelinePage` | Accept `?open=` query param to auto-open modal |
| `Layout` | Add Awards + Tenders nav items; update Watching → Matching |
| `App` | Add `/awards` and `/tenders` routes; update `/matching` |

### 8.3 API Service Additions

```typescript
export const awards = {
  list: (params: Record<string, unknown>) =>
    api.get<{ items: AwardItem[]; total: number; page: number; page_size: number }>('/awards', { params }),
};

export const tenders = {
  list: (params: Record<string, unknown>) =>
    api.get<{ items: TenderItem[]; total: number; page: number; page_size: number }>('/tenders', { params }),
  toggleWatch: (tenderId: string) =>
    api.post<{ is_watching: boolean }>('/watchlist/toggle', { tender_id: tenderId }),
  provinces: () =>
    api.get<string[]>('/tenders/provinces'),
};

export const organizations = {
  list: () =>
    api.get<{ id: string; name: string }[]>('/organizations'),
};

export const categories = {
  list: () =>
    api.get<{ id: string; name: string }[]>('/categories'),
};
```

### 8.4 TypeScript Type Additions

Add to `frontend/src/types/index.ts`:

```typescript
export interface AwardItem {
  id: string;
  supplier_name: string;
  buyer_org_id: string | null;
  buyer_org_name: string | null;
  tender_title: string | null;
  amount: number | null;
  award_date: string | null;
  bee_level: number | null;
  source: string;
  opportunity_id: string | null;
}

export interface TenderItem {
  id: string;
  title: string | null;
  estimated_value: number | null;
  province: string | null;
  category_id: string | null;
  category_name: string | null;
  buyer_org_id: string | null;
  buyer_org_name: string | null;
  closing_date: string | null;
  published_at: string | null;
  tender_type: string | null;
  discovered_at: string | null;
  status: 'not_watched' | 'watching' | 'awarded' | 'past_due' | 'opportunity';
  is_watching: boolean;
  opportunity_id: string | null;
}

export interface WatchlistItem {
  // ... existing fields
  opportunity_id: string | null;
  opportunity_count: number;
}
```

### 8.5 Query Param Navigation

Add `useSearchParams` to `PipelinePage.tsx`:

```tsx
import { useSearchParams } from 'react-router-dom';

// Inside component:
const [searchParams] = useSearchParams();
const openOppId = searchParams.get('open');
```

### 8.6 FilterBar Component Interface

```tsx
interface FilterBarProps {
  fields: FilterField[];
  values: Record<string, string>;
  onChange: (key: string, value: string) => void;
  onClear: () => void;
}

interface FilterField {
  key: string;
  label: string;
  type: 'text' | 'number' | 'date' | 'select' | 'toggle';
  options?: { label: string; value: string }[];  // for select type
  placeholder?: string;
}
```

### 8.7 DataTable Component Interface

```tsx
interface DataTableProps {
  columns: ColumnDef[];
  data: Record<string, unknown>[];
  page: number;
  pageSize: number;
  total: number;
  onPageChange: (page: number) => void;
  isLoading: boolean;
  emptyMessage?: string;
}

interface ColumnDef {
  key: string;
  label: string;
  render?: (value: unknown, row: Record<string, unknown>) => React.ReactNode;
  className?: string;
  width?: string;
}
```

---

## 9. Backend Implementation Plan

### 9.1 New API Endpoints

| Method | Path | Purpose | File |
|--------|------|---------|------|
| `GET` | `/api/awards` | Filterable, paginated awards list | `backend/app/api/awards.py` (new) |
| `GET` | `/api/tenders` | Filterable, paginated tenders list | `backend/app/api/tenders.py` (new) |
| `GET` | `/api/organizations` | Reference list for filter dropdown | `backend/app/api/organizations.py` (new) |
| `GET` | `/api/categories` | Reference list for filter dropdown | `backend/app/api/categories.py` (new) |
| `POST` | `/api/watchlist/toggle` | Add/remove a tender from watchlist | `backend/app/api/watchlist.py` (update) |

### 9.2 Schema Additions

| Schema | File | Fields |
|--------|------|--------|
| `AwardItem` | `backend/app/schemas/award.py` (new) | id, supplier_name, buyer_org_id, buyer_org_name, tender_title, amount, award_date, bee_level, source, opportunity_id |
| `AwardsList` | same | items, total, page, page_size |
| `TenderItem` | `backend/app/schemas/tender.py` (new) | id, title, estimated_value, province, category_id, category_name, buyer_org_id, buyer_org_name, closing_date, published_at, tender_type, discovered_at, status, is_watching, opportunity_id |
| `TendersList` | same | items, total, page, page_size |
| `WatchToggleRequest` | `backend/app/schemas/watchlist.py` | tender_id |
| `WatchToggleResponse` | same | is_watching |

### 9.3 Router Mounting

In `backend/app/api/__init__.py`:

```python
from app.api.awards import router as awards_router
from app.api.tenders import router as tenders_router
from app.api.organizations import router as org_router
from app.api.categories import router as cat_router

api_router.include_router(awards_router, tags=["awards"])
api_router.include_router(tenders_router, tags=["tenders"])
api_router.include_router(org_router, tags=["organizations"])
api_router.include_router(cat_router, tags=["categories"])
```

### 9.4 Watchlist Schema Update

Add `opportunity_id` and `opportunity_count` to `WatchlistItemRead`:

```python
class WatchlistItemRead(BaseModel):
    # ... existing fields
    opportunity_id: str | None = None
    opportunity_count: int = 0
```

### 9.5 Database Indexes

```sql
-- Awards table
CREATE INDEX IF NOT EXISTS idx_awards_supplier_name ON awards(supplier_name);
CREATE INDEX IF NOT EXISTS idx_awards_buyer_org_id ON awards(buyer_org_id);
CREATE INDEX IF NOT EXISTS idx_awards_amount ON awards(amount);
CREATE INDEX IF NOT EXISTS idx_awards_source ON awards(source);
CREATE INDEX IF NOT EXISTS idx_awards_bee_level ON awards(bee_level);

-- Tenders table
CREATE INDEX IF NOT EXISTS idx_tenders_title ON tenders(title);
CREATE INDEX IF NOT EXISTS idx_tenders_buyer_org_id ON tenders(buyer_org_id);
CREATE INDEX IF NOT EXISTS idx_tenders_province ON tenders(province);
CREATE INDEX IF NOT EXISTS idx_tenders_category_id ON tenders(category_id);
CREATE INDEX IF NOT EXISTS idx_tenders_estimated_value ON tenders(estimated_value);
CREATE INDEX IF NOT EXISTS idx_tenders_closing_date ON tenders(closing_date);
CREATE INDEX IF NOT EXISTS idx_tenders_tender_type ON tenders(tender_type);
```

---

## 10. Data Flow Summary

```
┌──────────────┐     ┌───────────────────┐     ┌────────────────────┐
│  TSA DB      │────>│  Discovery Job     │────>│  tenders table      │
│  (49k tend.  │     │  (every 15 min)    │     │  (all discovered)   │
│   56k awards)│     └───────────────────┘     └──────┬─────────────┘
└──────────────┘                                      │
                                                      ▼
                                              ┌──────────────────┐
                                              │  Tenders Browser  │ ← NEW
                                              │  /tenders          │
                                              │  (filterable,     │
                                              │   watch toggle)   │
                                              └────────┬─────────┘
                                                       │
                                              watches a subset
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Matching Board   │ ← RENAMED
                                              │  /matching        │
                                              │  (timing windows) │
                                              └────────┬─────────┘
                                                       │
                                              award detected
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │  Awards table     │
                                              └──────┬───────────┘
                                                      │
                                              ┌───────┴────────┐
                                              │                │
                                              ▼                ▼
                                      ┌────────────┐   ┌──────────────┐
                                      │ Awards      │   │ Pipeline     │
                                      │ Browser     │   │ Kanban       │
                                      │ /awards     │   │ /pipeline    │
                                      │ (filterable)│   │ (opportunity │
                                      └────────────┘   │  workflow)   │
                                                        └──────────────┘
```

---

## 11. Deliverables

1. Navigation restructure: rename "Watching" → "Matching", add Award/Tender nav items
2. Matching page: cross-reference links to Pipeline opportunities, awarded section
3. Awards browser page: filterable table with all award fields, pagination, opportunity cross-links
4. Tenders browser page: filterable table with all tender fields, pagination, watch toggle, status badges
5. Radar sidebar update: "View All" link, clickable cards
6. `GET /api/awards` endpoint with filtering + pagination
7. `GET /api/tenders` endpoint with filtering + pagination + computed status
8. `GET /api/organizations` and `GET /api/categories` reference endpoints
9. `GET /api/tenders/provinces` endpoint
10. `POST /api/watchlist/toggle` endpoint with auth, validation, past-due cleanup
11. Database indexes for search and filter columns (14 new indexes)
12. Watchlist schema update with `opportunity_id` and `opportunity_count`
13. Pipeline page query-param support (`?open=id`) for external deep-linking
14. Reusable `FilterBar` and `DataTable` components

---

## 12. Acceptance Criteria

- [ ] Sidebar shows 6 nav items: Pipeline, Matching, Awards, Tenders, Past Due, Admin
- [ ] Matching page shows `watching` tenders with timing windows AND an "Awarded" collapsible subsection with `→ Open in Pipeline` links
- [ ] Matching page no longer shows `past_due` items (they are on Past Due page only)
- [ ] Awards page loads and displays all awards with correct filtering and pagination
- [ ] Awards page filters (supplier, buyer, date range, value range, source, has_opportunity) all work correctly
- [ ] Awards page handles null `buyer_org_name` and `tender_title` gracefully
- [ ] Tenders page loads and displays all tenders with correct status badges
- [ ] Tenders page filters (text search, buyer, province, category, value, closing date, status, has_opportunity) all work
- [ ] Status badges on Tenders page correctly distinguish: `watching`, `awarded`, `past_due`, `opportunity`, `not_watched`
- [ ] Watch toggle on Tenders page adds/removes from watchlist, updates status badge optimistically
- [ ] Watch toggle also cleans up `past_due_queue` when removing from watchlist
- [ ] Radar sidebar shows "[View All]" link navigating to `/awards`
- [ ] Radar sidebar cards are clickable and navigate to `/awards?supplier=...`
- [ ] `GET /api/organizations` and `GET /api/categories` return correct reference data
- [ ] `GET /api/tenders/provinces` returns distinct province list
- [ ] Clicking `?open=opportunity_id` from any page opens the correct OpportunityModal on Pipeline page
- [ ] Matching → Pipeline cross-link navigates to correct opportunity
- [ ] Tenders → Matching cross-link works for watched tenders
- [ ] Tenders → Pipeline cross-link works for opportunities
- [ ] No regressions in existing Pipeline kanban, Past Due queue, or Admin functionality
- [ ] All pages handle loading, empty, and error states gracefully
- [ ] 14 new database indexes are created

---

## 13. Deferred Scope

- Export to CSV/PDF from Awards/Tenders pages
- Saved filters / filter presets
- Column sorting on table headers (initial: fixed sort by date desc)
- Inline editing of tender metadata from Tenders page
- Batch watch/unwatch operations
- Tender detail popover on title click
- Award radar chart visualization (Recharts) — deferred to Phase 3
