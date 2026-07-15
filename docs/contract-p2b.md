# Spec Contract — Phase 2b: UI Navigation, Awards & Tenders

> **Status:** Historical document. This contract is **fully implemented** and closed. The code is the source of truth.

**Contract ID:** ORI-P2B-001
**Status:** Closed — Implemented
**Date:** 2026-07-01
**Specification:** `docs/specifications/phase-2b-ui-navigation-awards-tenders.md`

---

## Parties & Acceptance

This contract defines the agreed scope, deliverables, and quality bar for the Phase 2b implementation. Any deviation from the terms below must be documented and approved before proceeding.

| Role | Acceptance |
|------|-----------|
| Specification author | ✓ Approved |
| Implementer | ✓ Accepted |

---

## 1. Scope of Work

### 1.1 In Scope

The following work items are within scope and must be completed:

| # | Item | Spec Section | Effort |
|---|------|-------------|--------|
| 1 | Navigation restructure (rename Watching→Matching, add Awards/Tenders) | §1 | Small |
| 2 | Matching page with cross-links + awarded section | §2 | Medium |
| 3 | Awards browser page with filters + pagination | §3 | Large |
| 4 | Tenders browser page with filters + pagination + watch toggle | §4 | Large |
| 5 | AwardRadar sidebar update (view-all link, clickable cards) | §6 | Small |
| 6 | Reference endpoints (orgs, categories, provinces) | §7 | Small |
| 7 | `POST /api/watchlist/toggle` endpoint | §4.6 | Medium |
| 8 | Database indexes (14 new indexes) | §9.5 | Small |
| 9 | Watchlist schema: `opportunity_id` + `opportunity_count` | §9.4 | Small |
| 10 | Pipeline page `?open=` query param support | §5.2 | Small |
| 11 | FilterBar + DataTable reusable components | §8.6, §8.7 | Medium |

### 1.2 Out of Scope

The following are explicitly excluded from this contract:

- Sorting by column headers (fixed sort by date desc only)
- CSV/PDF export from Awards/Tenders pages
- Saved filter presets
- Inline editing of tender metadata
- Batch watch/unwatch operations
- Tender detail popover on click
- Award chart visualization (deferred to Phase 3)

---

## 2. Implementation Order

The implementation MUST follow this strict sequence. Each phase must be completed (including tests) before the next begins.

| Phase | Tasks | Verification |
|-------|-------|-------------|
| **1. Backend foundation** | Indexes, schemas, reference endpoints, watch-toggle endpoint | `pytest` passes |
| **2. Backend new APIs** | GET /api/awards, GET /api/tenders, watchlist update | `pytest` + manual curl |
| **3. Frontend types + services** | TS types, API service additions | `tsc --noEmit` passes |
| **4. Frontend components** | FilterBar, DataTable | Render check |
| **5. Frontend pages** | AwardsPage, TendersPage, MatchingPage | `tsc --noEmit` passes |
| **6. Frontend integration** | Layout, App, AwardRadar updates, Pipeline ?open= | Manual E2E check |
| **7. Final verification** | All acceptance criteria retested | Full regression |

---

## 3. Quality Bar

### 3.1 Backend
- All new API endpoints return correct HTTP status codes (200, 404, 400, 401, 422)
- Pagination works correctly (page=1, page=-1, page_size above max, below min)
- Filter combinations work (empty filters, all filters combined, contradictory filters)
- Nullable fields handled gracefully (no `AttributeError: 'NoneType' object has no attribute`)
- Auth required on all new endpoints
- Database transactions committed on success, rolled back on failure
- Existing `pytest` suite must pass

### 3.2 Frontend
- TypeScript compiles with `tsc --noEmit` — zero errors
- All pages render without console errors
- Loading states show (no blank screen while data loads)
- Empty states show correct messages
- Error states show with retry option
- Filter values sync with URL params (back/forward navigation works)
- Pagination controls disabled at boundaries (no page < 1, no page beyond max)
- Mobile-responsive (sidebar collapses, filter bar wraps)

### 3.3 Data Integrity
- No duplicate watchlist items created
- No opportunities lost or corrupted
- Past-due queue entries cleaned up when unwatching

---

## 4. Deviations & Approvals

Any deviation from this contract or the specification document requires:

1. The deviation documented in writing
2. Reason for the deviation
3. Impact assessment (what breaks, what's deferred)
4. Explicit approval from the spec author

**Urgent fixes** (bugs found during implementation) may be applied immediately but must be documented within 24 hours.

---

## 5. Sign-off

Implementation may proceed after this contract is acknowledged. Sign-off on the completed work requires:

1. All acceptance criteria in §12 of the spec are met
2. All items in §3 (Quality Bar) above are verified
3. No regressions in existing functionality

---

## 6. Appendix: Implementation Checklist

- [ ] Phase 1: Create 14 DB indexes
- [ ] Phase 1: Create schema files (award.py, tender.py + watchlist update)
- [ ] Phase 1: Create api/awards.py with GET /api/awards
- [ ] Phase 1: Create api/tenders.py with GET /api/tenders + GET /api/tenders/provinces
- [ ] Phase 1: Create api/organizations.py with GET /api/organizations
- [ ] Phase 1: Create api/categories.py with GET /api/categories
- [ ] Phase 1: Update api/watchlist.py with POST /toggle endpoint
- [ ] Phase 1: Update api/watchlist.py query for opportunity_id
- [ ] Phase 1: Mount all new routers in api/__init__.py
- [ ] Phase 1: Run pytest (existing tests must pass)
- [ ] Phase 2: Add TS types (AwardItem, TenderItem, WatchlistItem update)
- [ ] Phase 2: Add API services (awards, tenders, orgs, categories)
- [ ] Phase 2: Build FilterBar component
- [ ] Phase 2: Build DataTable component
- [ ] Phase 2: Build AwardsPage
- [ ] Phase 2: Build TendersPage
- [ ] Phase 2: Rename WatchingPage → MatchingPage, add cross-links + awarded section
- [ ] Phase 2: Update Layout (nav items, route changes)
- [ ] Phase 2: Update App.tsx (routes)
- [ ] Phase 2: Update AwardRadar (view-all, clickable cards)
- [ ] Phase 2: Update PipelinePage (?open= param)
- [ ] Phase 2: Run tsc --noEmit
