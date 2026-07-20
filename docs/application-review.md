# Oricred — Full Application Review

**Date:** 2026-07-20
**Scope:** Ingestion pipeline, backend API, frontend

---

## 1. Overview

Oricred is a procurement intelligence platform that ingests tender and award data from South African government sources (Tenders-SA, municipal portals), enriches it with company and contact data, and presents a lead-management pipeline with scoring, CRM integration, and email alerts.

**Stack:**
- **Backend:** Python 3.12, FastAPI, SQLAlchemy 2.0 (async), APScheduler, Pydantic v2
- **Frontend:** React 18, TypeScript 5, Vite 5, Tailwind CSS 3, @dnd-kit, TanStack Query
- **Database:** PostgreSQL 16 (prod) / SQLite (dev)
- **External:** Tenders-SA PostgreSQL (read-only), Tenders-SA REST API, Monday.com GraphQL, SMTP email

---

## 2. Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        INGESTION LAYER                          │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────────┐  │
│  │ TSA DB   │  │ TSA REST │  │ Municipal│  │ Monday.com     │  │
│  │ (PG, RO) │  │ (API)    │  │ Scrapers │  │ (GraphQL)      │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └───────┬────────┘  │
│       │             │             │                 │           │
│       ▼             ▼             ▼                 ▼           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                 7 SCHEDULED JOBS                          │   │
│  │  discover_tenders  (*/15 min)   sync_crm  (hourly)       │   │
│  │  check_awards      (*/30 min)   contact_enrichment (M/Th)│   │
│  │  refresh_timing_model (Sun 2AM) historical_contacts(daily)│   │
│  │  fix_corrupted_award_dates (daily 4AM)                   │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ORICRED DATABASE                            │
│  18 tables: Tender, Award, Company, Opportunity, Contact, etc.   │
└──────────────┬──────────────────────────────────┬────────────────┘
               │                                  │
               ▼                                  ▼
┌────────────────────────────┐   ┌──────────────────────────────┐
│      BACKEND API (16 routers, 50+ endpoints)              │
│  /api/auth   /api/opportunities   /api/leads   /api/awards  │
│  /api/tenders  /api/watchlist  /api/radar  /api/dashboard  │
│  /api/admin (8 tabs)  /api/contacts  /api/organizations    │
│  /api/categories  /api/past-due  /api/historical-contacts  │
└──────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FRONTEND (React SPA)                        │
│  /discover (5 sub-tabs)  /leads  /pipeline  /admin  /help      │
│  TanStack Query ↔ Axios ↔ FastAPI                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Ingestion Pipeline

### 3.1 Data Sources

| Source | Type | Status | Used By |
|--------|------|--------|---------|
| Tenders-SA PostgreSQL | Direct DB (read-only) | ✅ Active | All ingestion jobs |
| Tenders-SA REST API | HTTP + Bearer token | ⚠️ Configured but unused | — |
| City of Cape Town | HTML scraping | ✅ Active | discover_tenders |
| City of Johannesburg | HTML scraping | ✅ Active | discover_tenders |
| OCPO | (not implemented) | ❌ Stub | — |
| e-Tenders | (not implemented) | ❌ Stub | — |
| TSA-OCP | (not implemented) | ❌ Stub | — |
| Monday.com | GraphQL API | ✅ Active | sync_crm, check_awards |

### 3.2 Scheduled Jobs

| Job | Schedule | What It Does | Key Function |
|-----|----------|-------------|--------------|
| `discover_tenders` | Every 15 min | Polls TSA DB for open tenders, runs municipal scrapers, qualifies tenders, creates watchlist items | `discovery.py:discover_new_tenders()` |
| `check_awards` | Every 30 min | Incremental award ingestion from TSA DB since last cursor, creates/upserts companies/awards/opportunities, runs contact enrichment, pushes to CRM, sends alerts | `award_check.py:check_awards_for_watching()` |
| `refresh_timing_model` | Sunday 2AM | Recomputes award-timing stats (mean/stddev/min/max days per org+category) | `model_refresh.py:refresh_timing_model()` |
| `sync_crm` | Hourly (:30) | Pulls Monday.com activity → updates local opportunities | `crm_sync.py:sync_crm()` |
| `contact_enrichment` | Mon/Thu 3AM | Enriches companies with directors/key_personnel from TSA DB | `contact_enrichment.py:run_contact_enrichment()` |
| `historical_contacts` | Daily 2:30AM | Imports awarded companies from TSA DB (90-day window) | `historical_contacts.py:sync_historical_contacts_job()` |
| `fix_corrupted_award_dates` | Daily 4AM | Repairs NULL/future-dated award_date using award_check resolution logic | `award_check.py:fix_corrupted_award_dates()` |

### 3.3 Client Layer

**TSADatabase** (`app/clients/tsa_db.py`):
- Direct PostgreSQL connection to Tenders-SA (hardcoded URI in code)
- Read-only enforced via `default_transaction_read_only=on`
- 10 query methods: tenders, awards, companies, organizations, bidders, directors, key_personnel, source_directors, categories
- Filter-driven: each method accepts filter parameters and builds WHERE clauses

**TSAClient** (`app/clients/base.py`):
- REST API client for Tenders-SA
- Retry with exponential backoff (3 attempts), dead-letter queue on final failure
- **Currently unused** — all data flows through TSADatabase directly

**Monday.com** (`app/services/crm/monday.py`):
- GraphQL adapter: create_item, update_column_value, get_recent_activity, search_items
- Push on opportunity creation + transition
- Pull on hourly schedule

### 3.4 Municipal Scrapers

| Scraper | Base URL | Tenders | Awards |
|---------|----------|---------|--------|
| City of Cape Town | `capetown.gov.za` | ✅ HTML table scraping | ❌ Stub (empty) |
| City of Johannesburg | `coj-prod-...azurefd.net` | ✅ HTML table scraping | ❌ Stub (empty) |

Both classify tenders via keyword match (construction, IT, consulting, security, cleaning, catering).

---

## 4. Backend API

### 4.1 Router Inventory (16 routers, 50+ endpoints)

| Router | Endpoints | Auth |
|--------|-----------|------|
| `auth` | POST login, GET me, GET assignees | None / JWT |
| `opportunities` | GET list, GET by id, PATCH update, POST transition, POST mark-contacted, POST find-contact, PATCH assign, GET audit, GET relationship, POST compute-funding, POST compute-preference, GET crm-activity | JWT |
| `leads` | GET list, GET export, POST contact-import/preview, POST contact-import/apply | JWT |
| `awards` | GET list, GET export, POST create-lead | JWT |
| `tenders` | GET list, GET provinces | JWT |
| `watchlist` | GET list, POST toggle | JWT |
| `radar` | GET (7-day feed + past-due count) | JWT |
| `dashboard` | GET stats | JWT |
| `admin` | CRUD for credentials, filter-config, sources, notifications, scoring, jobs, users, failed-api-calls | JWT + admin |
| `contacts` | CRUD by company/org/opportunity | JWT |
| `historical-contacts` | GET list | JWT |
| `past-due` | GET list | JWT |
| `organizations` | GET list | JWT |
| `categories` | GET list | JWT |
| `health` | GET status | None |

### 4.2 Stage Workflow

```
new_lead ──→ client_contacted ──→ qualified_lead ──→ won_opportunity
                                                            │
                                                            ▼
                                              credit_preparation
                                                    │
                                                    ▼
                                                credit_review
                                                    │
                                                    ▼
                                               pre_approved
                                                    │
                                                    ▼
                                           conditions_precedent
                                                    │
                                                    ▼
                                              term_sheet_sent
                                                    │
                                                    ▼
                                            term_sheet_received
                                                    │
                                                    ▼
                                              contracts_sent
                                                    │
                                                    ▼
                                           contracts_received
                                                    │
                                                    ▼
                                              ready_to_rff
                                                    │
                                                    ▼
                                                funded
```

`lost_lead` reachable from any stage via `decline`/`lose` action. `reopen` from `funded`/`lost_lead` returns to `new_lead`.

Transitions are handled exclusively through `POST /opportunities/{id}/transition` with semantic actions (`advance`, `back`, `reopen`, `decline`, `lose`). Version-based optimistic concurrency (409 on mismatch).

### 4.3 Database Models (18 tables)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tenders` | Tender/opportunity source data | title, estimated_value, province, closing_date, buyer_org_id |
| `awards` | Award records (core business value) | supplier_name, amount, award_date, publication_date, supplier_company_id |
| `award_ingestion_state` | Per-source ingestion cursor | source, latest_award_at |
| `companies` | Supplier companies | name, registration_number, bee_level |
| `organizations` | Buyer organizations | name, organization_type (national/provincial/soe/municipal) |
| `categories` | Tender categories (hierarchical) | name, parent_id |
| `opportunities` | Lead/Deal records (central model) | kanban_stage, company_id, award_id, version (optimistic lock) |
| `opportunity_audit` | Stage transition audit log | opportunity_id, from_stage, to_stage, changed_by |
| `watchlist_items` | Watched tenders with timing windows | tender_id, status, expected_window_start/end |
| `award_timing_model` | Computed timing statistics | organization_id, category_id, avg_days_to_award, stddev |
| `past_due_queue` | Overdue tender tracking | tender_id, resolution, poll_count_since_due |
| `contacts` | Company/buyer contacts | first_name, last_name, email (nullable), phone, source |
| `historical_contacts` | Company award history | company_id, total_award_count, total_award_value |
| `buyer_relationships` | Buyer-company relationship analytics | company_id, organization_id, award_count_12m, win_rate |
| `filter_config` | Admin configuration blobs (JSON) | key (unique), value (JSON), enabled |
| `users` | Application users | email, hashed_password, role (admin/operator) |
| `job_runs` | Job execution log | job_name, status, error, items_processed |
| `failed_api_calls` | Dead-letter queue | endpoint, method, error, attempts, resolved |
| `alert_log` | Email alert history | event_type, recipient, subject, delivery_status |

### 4.4 Key Services

| Service | Purpose |
|---------|---------|
| `qualification.py` | Config-driven tender filter engine (value, sector, province, entity, BEE, risk) |
| `lead_scoring.py` | 0-100 priority scoring: contact sufficiency, award recency/value, B-BBEE, buyer preference |
| `funding_suitability.py` | 0-100 funding score: B-BBEE level, 12-month award value, forensic risk |
| `buyer_relationship.py` | Relationship analytics: award count/value, win rate, response days |
| `buyer_preference.py` | Province weight + preferred buyer + SOE bonus scoring |
| `contact_enrichment.py` | Pull directors/key_personnel from TSA DB, upsert contacts |
| `competitor_intel.py` | Speculative/confirmed bidder identification |
| `contact_sufficiency.py` | Classifies contact quality (sufficient/role_based/none) |
| `crm/sync.py` | Bidirectional Monday.com sync (push on create/transition, pull hourly) |
| `email_alert.py` | Template-based alerts (currently only logs, no actual SMTP send) |
| `lead_contact_import.py` | CSV/XLSX import with column aliases, company matching |
| `award_timing.py` | Award window computation from historical data |

### 4.5 Scoring Architecture

```
Lead Priority Score (0-100)
  ├── Contact sufficiency (0-30 pts)
  ├── Award recency (0-20 pts)
  ├── Award value (0-20 pts)
  ├── Enterprise type (0-10 pts)
  ├── Award history (0-10 pts)
  ├── B-BBEE level (0-5 pts)
  └── Buyer preference (0-5 pts)

Funding Suitability (0-100)
  ├── B-BBEE level
  ├── 12-month award value
  ├── Forensic risk score
  └── Track record age

Buyer Preference (0-100)
  ├── Province weights (from config)
  ├── Preferred buyers bonus
  └── SOE bonus
```

---

## 5. Frontend

### 5.1 Routes

| Path | Page | Description |
|------|------|-------------|
| `/login` | LoginPage | Sign-in form |
| `/discover` | DiscoverPage | Tabbed: Awards, Tenders, Watching, Past Due, Supplier History |
| `/leads` | LeadsPage | Lead inbox with filters, export, contact import |
| `/pipeline` | PipelinePage | Kanban with DnD, decline, opportunity modal |
| `/admin` | AdminPage | 8-tab admin panel |
| `/help` | HelpPage | Searchable operating guide |

Legacy routes (`/awards`, `/tenders`, `/matching`, `/historical-contacts`, `/past-due`) redirect to `/discover?tab=...`.

### 5.2 Components

| Component | Used In | Description |
|-----------|---------|-------------|
| `Layout` | App wrapper | Sidebar nav, header, offline banner |
| `OpportunityCard` | PipelinePage, terminal trays | Draggable card with badges (sufficiency, risk, value, funding, preference) |
| `OpportunityModal` | PipelinePage, LeadsPage | Full detail: award info, contacts, buyer relationship, scoring, bidders, audit, CRM, notes |
| `WorkflowActions` | OpportunityModal | Transition dropdown: Find Contact, Advance, Back, Decline |
| `PhaseDroppable` | PipelinePage (inline) | Droppable phase column with card list + hover decline button |
| `DecliningDialog` | PipelinePage (inline) | Decline reason prompt |
| `KanbanColumn` | (unused) | Single-stage droppable column (superseded by PhaseDroppable) |
| `AwardRadar` | (unused) | Sidebar award feed (superseded by Discover tabs) |
| `FilterBar` | AwardsPage, TendersPage | Reusable filter controls |
| `DataTable` | AwardsPage, TendersPage | Reusable paginated table |
| `LeadContactImport` | LeadsPage | 4-step CSV/XLSX import wizard |
| `HelpLink` | Multiple | Link to help section |

### 5.3 Data Fetching Pattern

All data flows through TanStack Query:

```
Component → useQuery/useMutation → api.ts (Axios) → FastAPI backend
```

- Polling: `refetchInterval` of 15-60s on most pages
- Optimistic updates: PipelinePage DnD via `onMutate` + rollback on error
- Auth: JWT in localStorage, Axios interceptor adds Bearer token, 401 redirects to /login
- Reference data (orgs, categories, provinces): 5min staleTime

### 5.4 Key Types

| Type | Fields |
|------|--------|
| `Opportunity` | 35 fields: kanban_stage, company_name, award_value, contact_sufficiency, risk_flag, scoring fields, contacts, version (optimistic lock) |
| `Stage` | 15 union values: new_lead through funded + lost_lead |
| `Contact` | 14 fields: names, email (required in type, nullable in DB), phones, source |
| `AwardItem` | 18 fields: supplier, buyer, amount, award_date, bee_level, lead_state |
| `TenderItem` | 16 fields: title, value, province, category, closing_date, status |

---

## 6. Issues & Recommendations

### 6.1 Critical Issues

| # | Issue | Location | Impact | Recommendation |
|---|-------|----------|--------|---------------|
| 1 | **Drag-and-drop not triggering API calls** | `PipelinePage.tsx:handleDragEnd` | DnD doesn't work — user reports cards "move right back" | Debug `event.over` detection; verify `pointerWithin` collision strategy works with current @dnd-kit version |
| 2 | **N+1 queries in opportunity listing** | `opportunities.py:list_opportunities()`, `leads.py:list_leads()` | Slow page loads with many opportunities | Add eager loading / joined queries; follow pattern from `awards.py:_query_awards()` |
| 3 | **TSA REST API client unused** | `clients/base.py` | Dead code, but TSA DB URI is hardcoded | Either remove or document as fallback; make TSA DB URI configurable via env var |
| 4 | **Email alerts are no-op** | `services/email_alert.py` | AlertLog records are created but SMTP send only logs | Wire SMTP send or remove alert generation if emails are not needed |
| 5 | **Stage PATCH endpoint is dead code** | `opportunities.py:253-296` | Raises 400 immediately, code below is unreachable | Remove the endpoint entirely |

### 6.2 Medium Issues

| # | Issue | Location | Impact | Recommendation |
|---|-------|----------|--------|---------------|
| 6 | **SQLite migration is destructive** | `database.py:_ensure_contact_email_nullable()` | On SQLite dev, drops and recreates contacts table | Use safe ALTER TABLE for SQLite or skip on dev |
| 7 | **Zustand installed but unused** | `package.json` | 1.6KB bundle waste | Remove dependency |
| 8 | **`AwardRadar` and `KanbanColumn` components unused** | Various | Dead code confusion | Remove or add to a cleanup backlog |
| 9 | **CRM activity endpoint returns all data unfiltered** | `opportunities.py:crm-activity` | Without API key returns empty; with key returns everything when company is null | Add null guard |
| 10 | **`watch_context` filter uses loose join** | `awards.py` | WatchlistItem.tender_id vs Award.tender_id may not match 1:1 | Review and tighten the join logic |
| 11 | **`_normalise()` vs `_normalize()` typo** | `lead_contact_import.py` | Dead function (`_normalise` defined, `_normalize` used) | Remove dead function |
| 12 | **Monday.com API key in env vs admin config** | Multiple | Two places to configure the same credential (env var and admin_credentials config) | Consolidate to single source |

### 6.3 Minor Issues

| # | Issue | Location | Impact | Recommendation |
|---|-------|----------|--------|---------------|
| 13 | **PATCH /stage code below raise is unreachable** | `opportunities.py` | ~40 lines of dead code | Remove |
| 14 | **`OpportunityCreate` schema unused** | `schemas/opportunity.py` | Empty placeholder schema | Remove |
| 15 | **`API Base URL fields named `scrapers`` vs `sources`** | Admin UI | Inconsistency between endpoint names and UI labels | Standardize naming |
| 16 | **Contact `email` field typed as required in TS** | `types/index.ts:Contact.email` | `string` (not `string \| null`) despite DB being nullable | Update to match DB |
| 17 | **Service worker cache may serve stale bundle** | PWA config | Users may need hard refresh after deployments | Add versioning or skip-waiting |

### 6.4 Architecture Observations

1. **Schema management is ad-hoc**: `Base.metadata.create_all` + `ALTER TABLE IF NOT EXISTS` in `init_db()` — no formal migration tooling despite Alembic being configured. Production deploys rely on startup-time schema mutations.

2. **Optimistic concurrency is well-designed**: Version field on Opportunity with 409 Conflict on stale updates is solid.

3. **Config-driven scoring is flexible**: All scoring weights stored in `filter_config` table, editable via admin UI without redeployment.

4. **Dead-letter queue for API failures**: Failed external calls are persisted for retry via admin UI — good operational practice.

5. **Legacy stage mapping**: `LEGACY_STAGE_MAP` bridges old and new stage names — necessary for data migration but adds complexity.

6. **Phase grouping on pipeline**: User-facing columns group multiple workflow stages (e.g., "Sales" = `qualified_lead` + `won_opportunity`). DnD transitions only between adjacent phases, not individual stages. This is simpler than true kanban but may feel limiting.

---

## 7. Data Flow Summary

### Lead Creation Flow
```
TSA DB Award → check_awards job → upsert Award + Company → create Opportunity (new_lead)
                                                              │
                                                              ▼
                                                    contact_enrichment (TSA DB directors)
                                                              │
                                                              ▼
                                                    lead_scoring compute → priority score
                                                              │
                                                              ▼
                                                    CRM push → Monday.com item created
```

### Lead Progression Flow
```
new_lead → mark-contacted → client_contacted → advance → qualified_lead
  │                                                          │
  │                                                          ▼
  │                                                   won_opportunity → Credit → Deal Execution → funded
  │                                                          │
  └──→ decline → lost_lead ←── (decline from any stage) ←───┘
```

### Frontend Data Dependencies

```
Page              Queries                          Mutations
─────────────────────────────────────────────────────────────
/pipeline         opportunities.list()             opportunities.transition()
/leads            leads.list()                     leads.export(), contact-import
/discover/awards  awards.list(), orgs, provinces   awards.createLead()
/discover/tenders tenders.list(), orgs, categories tenders.toggleWatch()
/admin/*          admin.get*(8 tabs)               admin.update*(8 tabs)
/help             (static content)                 —
```

---

## 8. Test Coverage

- **Backend:** 121 pytest tests (test_lead_contact_import, test_contacts, test_tsa_database, test_competitor_intel)
- **Frontend:** No test suite configured
- **Integration:** No integration tests
- **E2E:** None

Test gaps: workflow transitions, scoring algorithms, DnD interactions, job execution, CRM sync, admin operations.

---

## 9. Configuration Reference

| Env Variable | Default | Required | Used In |
|-------------|---------|----------|---------|
| `ORICRED_DATABASE_URL` | `sqlite+aiosqlite:///./oricred.db` | Yes (prod) | database.py |
| `ORICRED_TSA_API_KEY` | `""` | No (unused) | clients/base.py |
| `ORICRED_TSA_BASE_URL` | `https://api.tenders-sa.org` | No | clients/base.py |
| `ORICRED_JWT_SECRET` | dev-secret | Yes (prod) | services/auth.py |
| `ORICRED_SMTP_HOST` | `""` | No (no-op) | services/email_alert.py |
| `ORICRED_SMTP_USER` | `""` | No | services/email_alert.py |
| `ORICRED_SMTP_PASSWORD` | `""` | No | services/email_alert.py |
| `ORICRED_EMAIL_FROM` | `noreply@oricred.com` | No | services/email_alert.py |
| `ORICRED_MONDAY_API_KEY` | `""` | No | services/crm/monday.py |
| `ORICRED_REDIS_URL` | `""` | No | (optional cache) |
| `ORICRED_DEBUG` | `True` | No | config.py |

**Hardcoded values:**
- TSA DB connection: `postgresql+asyncpg://tendersa_app:11111111@10.0.1.175:5432/tendersa_prod` in `clients/tsa_db.py`
- JWT algorithm: HS256
- JWT expiry: 1440 minutes (24 hours)
