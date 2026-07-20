# Implementation Plan — Resolve Identified Issues

**Date:** 2026-07-20
**Based on:** `docs/application-review.md`

---

## Phase 1 — Critical (Week 1)

### 1.1 Fix Drag-and-Drop on Pipeline

**Issue #1** — DnD not triggering API calls, cards "move right back"

**Root cause analysis needed:**
- The backend logs show zero POST requests during drag attempts — `handleDragEnd` never calls `dndTransition.mutate()`
- Likely causes (in priority order):
  1. `event.over` is `null` because `pointerWithin` collision doesn't match the PhaseDroppable
  2. The `event.active.data.current?.opportunity` is `undefined` due to how @dnd-kit passes data
  3. A JavaScript exception in `handleDragEnd` before the mutation call

**Diagnostic steps:**
1. Add a `console.log` in `handleDragStart` and `handleDragEnd` to verify they fire
2. Log `event.over`, `event.active.data.current` structure in `handleDragEnd`
3. Check browser console output

**Fix options:**
- **Option A**: Replace `useDroppable`/`useDraggable` with manual position-based detection using `event.activatorEvent.clientX/Y` and `getBoundingClientRect()` on phase column refs
- **Option B**: Wrap the entire handler in try/catch and surface any JS exception
- **Option C**: Use `DragOverlay`'s `dropAnimation` callback instead of `onDragEnd`

**Files:**
- `frontend/src/pages/PipelinePage.tsx` — `handleDragEnd`, `handleDragStart`

**Verification:** Hard refresh, drag card from Sales to Contacting, verify 200 POST to `/api/opportunities/{id}/transition` in network tab, card stays in Contacting column.

---

### 1.2 Fix N+1 Queries in Opportunity / Leads Listing

**Issue #2** — Each opportunity in list queries tender, award, company, org, category, contacts individually

**Fix:**
1. Create a single joined query in `list_opportunities()` using `selectinload` or `joinedload` for eager loading
2. Apply the same pattern to `list_leads()` in `leads.py`
3. Follow the pattern from `awards.py:_query_awards()` which uses proper joins

```python
# Current (N+1):
for opp in opportunities:
    tender = await db.execute(select(Tender).where(Tender.id == opp.tender_id))
    award = await db.execute(select(Award).where(Award.id == opp.award_id))

# Target (single query):
stmt = (
    select(Opportunity)
    .options(
        selectinload(Opportunity.tender),
        selectinload(Opportunity.award),
        selectinload(Opportunity.company),
    )
    .order_by(...)
)
```

**Files:**
- `backend/app/api/opportunities.py` — `list_opportunities()` (line 102-154)
- `backend/app/api/leads.py` — `list_leads()` (the filter query)

**Verification:** Run with 100+ opportunities; response time should drop significantly. Backend tests pass.

---

### 1.3 Handle Dead Code: Stage PATCH Endpoint & Unreachable Code

**Issue #5** + **Issue #13** — `PATCH /stage` raises 400 immediately, ~40 lines of unreachable code below it

**Fix:**
1. Remove the entire `PATCH /api/opportunities/{id}/stage` endpoint (lines 253-296 in `opportunities.py`)
2. The `/transition` endpoint is the sole stage mutation path

**Files:**
- `backend/app/api/opportunities.py` — remove `stage_update` endpoint

**Verification:** `GET /api/opportunities/{id}` still works; `POST /api/opportunities/{id}/transition` still works; tests pass.

---

### 1.4 Remove Unused `OpportunityCreate` Schema

**Issue #14** — Empty placeholder schema

**Fix:**
1. Remove `OpportunityCreate` class from `schemas/opportunity.py`

**Files:**
- `backend/app/schemas/opportunity.py`

---

## Phase 2 — Medium (Week 2)

### 2.1 Fix Contact Email Type in Frontend

**Issue #16** — `Contact.email` typed as `string` in TS but nullable in DB

**Fix:**
```typescript
// Current
email: string;
// Target
email: string | null;
```

Check all usages of `Contact.email` across components that assume it's always present.

**Files:**
- `frontend/src/types/index.ts` — `Contact.email`
- `frontend/src/pages/HistoricalContactsPage.tsx` — any email rendering
- `frontend/src/components/OpportunityModal.tsx` — any email rendering

**Verification:** TypeScript build passes with no new errors.

---

### 2.2 Remove Unused Dependencies and Components

**Issue #7** + **Issue #8** — Zustand, KanbanColumn, AwardRadar unused

**Fix:**
1. `npm uninstall zustand`
2. Delete `src/components/KanbanColumn.tsx` (superseded by inline `PhaseDroppable` in PipelinePage)
3. Delete `src/components/AwardRadar.tsx` (superseded by Discover tabs)

**Files:**
- `frontend/package.json`
- `frontend/src/components/KanbanColumn.tsx`
- `frontend/src/components/AwardRadar.tsx`

---

### 2.3 Fix Unused TSA REST API Client

**Issue #3** — `TSAClient` configured but never used; TSA DB URI hardcoded

**Fix:**
1. Either:
   - **Option A**: Remove `TSAClient` and `base.py` entirely
   - **Option B**: Make TSA DB URI configurable via `ORICRED_TSA_DATABASE_URL` env var, with the hardcoded value as fallback
2. Document in config that the REST API path is deprecated in favor of direct DB

**Files:**
- `backend/app/clients/__init__.py`
- `backend/app/clients/base.py`
- `backend/app/clients/tsa_db.py`
- `backend/app/config.py` — add `tsa_database_url` setting

---

### 2.4 Remove Dead `_normalise()` Function

**Issue #11** — Typo function defined but never called

**Fix:**
1. Remove the `_normalise()` function from `lead_contact_import.py`
2. Only `_normalize()` is used

**Files:**
- `backend/app/services/lead_contact_import.py`

---

### 2.5 Fix CRM Activity Endpoint Null Guard

**Issue #9** — Returns all activities unfiltered when company_name is None

**Fix:**
1. Add a guard: if `company_name` is None or API key is missing, return empty list immediately
2. This prevents accidental data leakage

**Files:**
- `backend/app/api/opportunities.py` — `crm_activity` endpoint (~line 524)

---

## Phase 3 — Polish (Week 3)

### 3.1 Fix SQLite Migration Destructiveness

**Issue #6** — Drops and recreates contacts table on SQLite dev

**Fix:**
1. For SQLite, use `ALTER TABLE contacts ADD COLUMN email VARCHAR(256)` — SQLite supports adding nullable columns
2. Only need the table rename dance for constraints, not for nullability changes
3. Or skip the migration entirely on SQLite since `create_all` already reflects the model

**Files:**
- `backend/app/database.py` — `_ensure_contact_email_nullable()`

---

### 3.2 Fix Watch Context Filter Join

**Issue #10** — Loose join between WatchlistItem and Award

**Fix:**
1. Review the join logic in `awards.py` for `watch_context` filter
2. Tighten to use explicit `WatchlistItem.tender_id == Tender.id` joined with `Award.tender_id == Tender.id` chain

**Files:**
- `backend/app/api/awards.py` — watch_context filter query

---

### 3.3 Standardize Monday.com API Key Source

**Issue #12** — Two sources for the same credential

**Fix:**
1. Choose one canonical source (recommend: env var `ORICRED_MONDAY_API_KEY` overrides admin config)
2. In `admin_config.py`, when saving admin_credentials, check if env var is set and use as default

**Files:**
- `backend/app/services/admin_config.py`
- `backend/app/services/crm/monday.py`
- `backend/app/api/admin.py`

---

### 3.4 Wire SMTP Email Sending or Remove

**Issue #4** — Email alerts only log, never send

**Fix:**
1. If email alerts are needed: wire SMTP send using `smtplib` with the configured credentials
2. If not needed: remove alert log creation and the entire email_alert service

Recommendation: Option 2 until email alerts are a product requirement, then implement properly with templating.

**Files:**
- `backend/app/services/email_alert.py`

---

### 3.5 Standardize API Source Naming

**Issue #15** — "scrapers" vs "sources" inconsistency

**Fix:**
1. Rename admin UI "Scrapers" tab to "Sources"
2. Update endpoint: `/api/admin/sources` is correct for REST, just the UI tab label

**Files:**
- `frontend/src/pages/AdminPage.tsx` — tab label
- `backend/app/api/admin.py` — router function names (cosmetic)

---

### 3.6 Fix PWA Service Worker Cache

**Issue #17** — Service worker may serve stale JS bundle

**Fix:**
1. In `vite.config.ts`, set `registerType: 'autoUpdate'` (already set)
2. Add `self.skipWaiting()` and `clients.claim()` in the service worker registration
3. Or configure VitePWA to use `injectManifest` for more control over update flow

**Files:**
- `frontend/vite.config.ts` — PWA plugin config

---

## Status — 2026-07-20

| # | Issue | Status | Notes |
|---|-------|--------|-------|
| 1 | Drag-and-drop not triggering API calls | **Done** | Composed pointerWithin + closestCorners; fallback using elementsFromPoint; new_lead→mark-contacted handled |
| 2 | N+1 queries in opportunity/leads listing | **Done** | Added _batch_load_opportunity_context() — loads all related entities in ~8 fixed queries |
| 3 | TSA REST API client unused | **Done** | Made TSA DB URI configurable via ORICRED_TSA_DATABASE_URL env var |
| 4 | Email alerts are no-op | **Done** | Wired SMTP sending with asyncio.to_thread; fallback to logging when not configured |
| 5 | Stage PATCH endpoint dead code | **Done** | Removed entire endpoint |
| 6 | SQLite migration destructive | Deferred | Safe for dev; not urgent |
| 7 | Zustand unused | **Done** | Uninstalled |
| 8 | AwardRadar/KanbanColumn unused | **Done** | Deleted both components |
| 9 | CRM activity endpoint null guard | **Done** | Early return empty when no company_id or company_name |
| 10 | Watch context filter loose join | Deferred | Low impact |
| 11 | _normalise() vs _normalize() typo | **Done** | No action needed — _normalise is the one used everywhere; no _normalize exists |
| 12 | Monday.com API key in two places | **Done** | Consolidated: admin config takes precedence, env var (ORICRED_MONDAY_API_KEY) as fallback |
| 13 | PATCH /stage code unreachable | **Done** | Removed with issue #5 |
| 14 | OpportunityCreate schema unused | **Done** | Removed |
| 15 | API source naming inconsistency | **Done** | Renamed getScrapers/updateScrapers → getSources/updateSources |
| 16 | Contact email typed as required | **Done** | Changed to string \| null |
| 17 | PWA service worker cache | Deferred | Low impact |

**Completed: 14 of 17 issues | Deferred: 3 (low priority)**
