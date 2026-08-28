# Oricred Project Guide

> **The code is the source of truth.** The `phase-*` specification documents under `docs/specifications/` are historical artifacts describing what was originally intended. The actual implementation may differ — always verify against running code.
>
> **Remediation specs:** the `remediation-*` documents record 34 defects found in the 2026-08-27 review of commit `9de20fd`, with the fix for each. **32 are implemented** (see git history on the `remediation/*` branches); the overview marks what is outstanding. Start at [`remediation-00-overview.md`](docs/specifications/remediation-00-overview.md).
>
> **Still open:** foreign-key constraints and the `Organization.id` column width (remediation-07 §5). Both need a check against production data before they can land — the orphan audit query and `SELECT MAX(LENGTH(id)) FROM source_organizations`. Also open: batching the two per-company aggregate queries in the award ingest loop, and per-column fetching on the pipeline board.

> When you change behaviour that a section of this file describes, update that
> section in the same commit. A stale description here costs more than a missing
> one: it makes the next reader reason about a system that does not exist. Every
> claim corrected in 2026-08 had been wrong for months.

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), APScheduler, httpx, Pydantic v2
- **Frontend**: React 18, TypeScript 5, Vite 5, Tailwind CSS 3, @dnd-kit, TanStack Query, Zustand
- **Database**: SQLite (dev) via aiosqlite, PostgreSQL 16 (prod) via asyncpg
- **Cache**: Redis 7 (optional, configured via `ORICRED_REDIS_URL`)
- **Infra**: systemd service (`oricred-backend.service`), uvicorn, Docker Compose

## Project Structure
```
oricred/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint, lifespan, CORS, static mount
│   │   ├── config.py            # Pydantic settings (ORICRED_ prefix)
│   │   ├── database.py          # SQLAlchemy async engine + session + init_db
│   │   ├── workflow.py          # Stage definitions, labels, legacy map, transitions
│   │   ├── api/                 # Route handlers (18 routers)
│   │   │   ├── auth.py          # Login, /me, /assignees, JWT validation
│   │   │   ├── opportunities.py # CRUD, transition, mark-contacted, find-contact, audit, relationship, funding, preference, crm-activity
│   │   │   ├── leads.py         # Filtered lead inbox
│   │   │   ├── awards.py        # Filterable/paginated awards browser + export + POST /awards/{id}/lead
│   │   │   ├── tenders.py       # Filterable/paginated tenders browser + provinces
│   │   │   ├── watchlist.py     # List + toggle (POST /watchlist/toggle)
│   │   │   ├── radar.py         # 7-day award feed + past-due count
│   │   │   ├── dashboard.py     # Aggregate stats
│   │   │   ├── admin.py         # Credentials, Jobs, Users + dead-letter retry (admin-only router)
│   │   │   ├── contacts.py      # CRUD for company/org/opportunity contacts
│   │   │   ├── historical_contacts.py # Historical contact list with search/filter
│   │   │   ├── past_due.py      # Past-due queue listing
│   │   │   ├── organizations.py # Reference list for filter dropdowns
│   │   │   └── categories.py    # Reference list for filter dropdowns
│   │   ├── clients/
│   │   │   ├── base.py          # TSAClient — REST HTTP client with retry + dead-letter
│   │   │   └── tsa_db.py        # TSADatabase — direct PostgreSQL (read-only, filter-driven)
│   │   ├── cli.py               # create-admin, list-users, reset-password, backfill-date-source, audit-orphans
│   │   ├── jobs/
│   │   │   ├── scheduler.py     # JOBS registry (single source for scheduler + Run Now)
│   │   │   ├── discovery.py     # Tender discovery via TSADatabase SQL filters
│   │   │   ├── award_check.py   # Award ingest — batched preload, one remote org fetch per run
│   │   │   ├── model_refresh.py # Weekly timing model recompute
│   │   │   ├── tender_backfill.py # Backfill stub tenders from TSA DB
│   │   │   ├── crm_sync.py      # Push opportunities to Monday.com
│   │   │   ├── contact_enrichment.py # Pull directors/key_personnel from TSA DB
│   │   │   └── historical_contacts.py # Sync historical award data per company
│   │   ├── models/              # 18 SQLAlchemy ORM models
│   │   │   ├── tender.py, award.py, award_ingestion_state.py
│   │   │   ├── company.py, organization.py, category.py
│   │   │   ├── watchlist.py, opportunity.py (incl. OpportunityAudit)
│   │   │   ├── timing_model.py, past_due.py, filter_config.py
│   │   │   ├── alert_log.py, job_run.py, failed_api_call.py
│   │   │   ├── user.py, buyer_relationship.py
│   │   │   ├── contact.py, historical_contact.py
│   │   │   └── __init__.py      # Re-exports all
│   │   ├── schemas/             # Pydantic v2 request/response schemas
│   │   │   ├── opportunity.py, award.py, tender.py, watchlist.py
│   │   │   ├── auth.py, dashboard.py, radar.py, buyer_relationship.py
│   │   │   ├── contact.py, historical_contact.py
│   │   │   └── __init__.py      # Re-exports all
│   │   └── services/            # Business logic
│   │       ├── auth.py, qualification.py, award_timing.py
│   │       ├── contact_sufficiency.py, text_utils.py
│   │       ├── email_alert.py, funding_suitability.py
│   │       ├── buyer_relationship.py, buyer_preference.py
│   │       ├── lead_scoring.py, lead_service.py, admin_config.py
│   │       ├── crm/ (monday.py adapter, sync.py)
│   │       ├── municipal_scraper/ (abstract + stubs)
│   │       └── contact_enrichment.py
│   ├── alembic/                 # Migrations (minimal — uses create_all + ALTER)
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Routes: /discover, /leads, /pipeline, /admin, /help
│   │   ├── main.tsx             # React root + QueryClient + BrowserRouter
│   │   ├── index.css            # Tailwind + custom utilities
│   │   ├── types/index.ts       # All TypeScript interfaces + stage constants
│   │   ├── services/api.ts      # Axios client + all API functions
│   │   ├── components/
│   │   │   ├── Layout.tsx       # Sidebar nav, header, offline banner
│   │   │   ├── AwardRadar.tsx   # Side panel: past-due count + recent awards
│   │   │   ├── KanbanColumn.tsx # Droppable kanban column
│   │   │   ├── OpportunityCard.tsx # Draggable card with badges
│   │   │   ├── OpportunityModal.tsx # Full detail modal
│   │   │   ├── WorkflowActions.tsx # Transition buttons
│   │   │   ├── FilterBar.tsx    # Reusable filter controls
│   │   │   ├── DataTable.tsx    # Reusable paginated table
│   │   │   └── HelpLink.tsx     # Help section link
│   │   └── pages/
│   │       ├── LoginPage.tsx
│   │       ├── DiscoverPage.tsx # Tabs: Watching, Awards, Tenders, History, Past-Due
│   │       ├── LeadsPage.tsx    # Filtered lead inbox
│   │       ├── PipelinePage.tsx # Kanban board with DnD + modal
│   │       ├── AdminPage.tsx    # Admin dashboard (Credentials, Jobs, Users)
│   │       └── HelpPage.tsx     # Help documentation
│   └── package.json
├── docs/
│   ├── implementation.md        # Implementation plan (code is truth)
│   ├── workflow.md              # Lead workflow documentation
│   ├── repo.md                  # GitHub repo URL
│   ├── contract-p2b.md         # Phase 2b contract
│   ├── openapi.json             # Auto-generated API spec
│   └── specifications/          # Spec documents
│       ├── phase-1-core-platform.md
│       ├── phase-1b-soe-gazette-gap-fill.md
│       ├── phase-2-municipalities-crm.md
│       ├── phase-2b-ui-navigation-awards-tenders.md
│       ├── phase-3-predictive-intelligence.md
│       ├── award-data-enrichment.md
│       ├── contact-editing.md
│       └── remediation-00-overview.md   # ── Remediation phase (2026-08)
│           ├── remediation-01-contact-enrichment-restoration.md
│           ├── remediation-02-security-hardening.md
│           ├── remediation-03-ingestion-correctness.md
│           ├── remediation-04-query-performance.md
│           ├── remediation-05-integrations-and-delivery.md
│           ├── remediation-06-import-and-export.md
│           └── remediation-07-engineering-hygiene.md
└── AGENTS.md                    # This file
```

## Database Rules — CRITICAL
- **Oricred DB (local PostgreSQL)**: All CREATE, UPDATE, DELETE operations must only touch the oricred application database. This is the database configured via the `ORICRED_DATABASE_URL` env var.
- **Tenders-SA DB (TSADatabase)**: This is an external PostgreSQL database provided by Tenders-SA. It is **STRICTLY READ-ONLY**. No INSERT, UPDATE, DELETE, ALTER, DROP, or any other write operations are ever permitted against this database. The `TSADatabase` client only issues SELECT queries. Violating this will break the data source agreement.
- When in doubt about which database a piece of code operates on, check the import path: `app.database` = oricred DB, `app.clients.tsa_db` = Tenders-SA read-only DB.

## Key Conventions
- **Env prefix**: `ORICRED_` for all settings (e.g. `ORICRED_DATABASE_URL`, `ORICRED_JWT_SECRET`)
- **DB**: PostgreSQL 16 (prod) / SQLite + aiosqlite (dev), auto-creates tables via `Base.metadata.create_all`
- **Auth**: JWT with bcrypt, `POST /api/auth/login` returns `access_token`. Email addresses are stored `.strip().lower()` by every write path, and login normalises and matches case-insensitively — keep both sides in step. Login also refuses an inactive user, so a deactivated account never receives a token that `get_current_user` would reject on the next request.
- **Models**: UUID string PKs, `DateTime(timezone=True)` for all timestamps
- **API routes**: All under `/api` prefix, mounted in `app/api/__init__.py`
- **Schemas**: Pydantic v2 with `from_attributes = True` for ORM mapping
- **Scheduler**: APScheduler AsyncIOScheduler, jobs logged to `job_runs` table
- **Frontend API**: Axios client with Bearer token interceptor, TanStack Query for data fetching
- **CORS**: `ORICRED_CORS_ORIGINS`, comma-separated. Empty = same-origin only (the standard deployment, since FastAPI serves the SPA); localhost:5173 is added in debug
- **Stage transition**: Use `POST /opportunities/{id}/transition` (not direct stage PATCH)

## Workflow Stages
```
new_lead → client_contacted → qualified_lead → won_opportunity → credit_preparation
→ credit_review → pre_approved → conditions_precedent → term_sheet_sent
→ term_sheet_received → contracts_sent → contracts_received → ready_to_rff → funded
```
`lost_lead` is reachable from any active stage. `back`, `reopen`, `decline`/`lose` actions supported.

## Implementation History

### Phase 1 — Core Platform (Completed)
- Tenders-SA REST API client + TSADatabase direct SQL client
- Tender discovery, award check, timing model jobs
- Qualification filter engine (config-driven)
- Contact-sufficiency classifier
- Confirmed bidders on a lead (`related_bidders`, populated during award ingest)
- Kanban pipeline with drag-and-drop
- AwardRadar sidebar (7-day feed + past-due counter)
- Watching/Matching board with award-timing windows
- Email alert service, JWT auth, admin CRUD
- Dead-letter queue for failed API calls

### Phase 2 — Municipalities & CRM (Completed)
- Funding-suitability scoring
- Buyer-relationship analytics engine + API
- CRM abstraction layer with Monday.com GraphQL adapter
- CRM sync service + scheduled job
- Municipal filter config update (includes "municipal" entity type)
- Municipal scraper adapter foundation (abstract + stubs)
- Frontend: funding suitability badge, buyer relationship panel
- Admin UI: Credentials, Jobs, Users (Filters/Sources/Notifications/Scoring tabs removed in a515055; endpoints remain)
- CRM item ID persistence + deduplication
- CRM push on opportunity assign
- Monday.com activity display in opportunity modal
- Buyer preference scoring (province weights, SOE bonus, preferred buyers)
- Sources tab (OCPO, e-Tenders, TSA-OCP config)
- PATCH /opportunities/{id} for notes/risk_flag/assigned_to
- GET /opportunities/{id}/audit + audit history panel
- Past-due queue API + frontend page
- Dead-letter retry button in admin UI
- Inline notes editing in opportunity modal
- Contact tracking model, API, and frontend panel
- Contact enrichment service + job

### Phase 2b — UI Navigation & Data Browsers (Completed)
- Navigation restructure: single-page Discover with tabs (Watching, Awards, Tenders, History, Past-Due)
- Legacy routes (/awards, /tenders, /matching, /past-due, /historical-contacts) redirect to Discover
- Awards browser: filterable/paginated table + CSV export + convert-to-lead (`POST /awards/{id}/lead`)
- Tenders browser: filterable/paginated table + watch toggle + status badges
- Historical contacts list with search/contactability filter
- GET /api/awards, GET /api/tenders, GET /api/organizations, GET /api/categories
- GET /api/tenders/provinces, POST /api/watchlist/toggle
- Watchlist schema: opportunity_id + opportunity_count
- Reusable FilterBar + DataTable components
- AwardRadar sidebar updated (view-all link, clickable cards)
- Pipeline page ?open= query param support
- Database indexes on awards + tenders tables
- Award data enrichment fix (backfill + pipeline fix)
- Lead workflow state machine (14 stages + transitions)
- Leads page with rich filtering (stage, contactability, priority, risk, value, recency)

### Phase 3 — Predictive Intelligence (Not started)
- Deferred until ≥12 months of historical data accumulated

## Award Date Domain Rules

The `award_date` on the `awards` table is the **core business value** of the
platform — it drives client workflows for contacting awarded suppliers to propose
funding. The TSA DB source can have century typos (e.g. `2062` instead of `2025`).
A missing date makes the record useless, so the resolver **never returns NULL**.

**Procurement timeline (validated ordering):**
```
tender.published_at ≤ tender.closing_date ≤ award.award_date ≤ award.publication_date ≤ discovered_at
```

**Resolution logic** (`_resolve_award_date` in `award_check.py`):
1. **Source date** — if the raw date parses and is not after `discovered_at`,
   use it. `from_source = True`.
2. **Source created_at** — the TSA DB row's creation timestamp, if it is not in
   the future. `from_source = True`.
3. **Discovery date** — when we first saw the record. `from_source = False`.

The resolver returns `ResolvedAwardDate(value, from_source)`. `from_source` is
what keeps two different consumers honest about the same number: the award date
is a business value that must never be NULL, so branch 3 synthesises one — but
the ingestion cursor must never move past a date we have actually confirmed.
Only source-backed dates advance it. Feeding a synthesised date to the cursor
pushed it to today and silently skipped every award published afterwards with an
older date.

`awards.date_source` records which branch produced the stored value, so the
nightly repair job scans only rows that are still unresolved and a repaired row
drops out permanently.

**Removed 2026-08:** year correction from reference dates, pub-date validation,
and `_parse_lenient()`. AGENTS.md described all three long after they were
deleted. Corrupt years now fall through to branch 2 or 3 and are marked
`date_source != "source"`.

**Key functions:**
- `_resolve_award_date()` — never returns None; reports whether the date is source-backed
- `parse_datetime()` — strict parse with `MAX_VALID_YEAR = 2027` guard
- `fix_corrupted_award_dates()` — daily recovery job (4AM default), batch-capped
- `python -m app.cli backfill-date-source` — one-off, marks pre-existing rows

**Key files:**
- `app/jobs/award_check.py` — `_resolve_award_date()`, `fix_corrupted_award_dates()`
- `app/utils.py` — `parse_datetime()` with `MAX_VALID_YEAR = 2027`
- `app/database.py` — `_ensure_award_columns()` adds `publication_date`, `date_source`

## Locked out of the admin account
`create-admin` refuses to run once any user exists, so recovery goes through:
- `python -m app.cli list-users` — shows every address, its role, and whether it is enabled
- `python -m app.cli reset-password --email you@example.com [--activate]` — prompts for the
  new password; `--activate` also re-enables a disabled account

Both need an interactive terminal (the password is never passed in argv), and both
need the same `.env` the server uses — run them from `backend/`.

If the login page reports a failure for every password, check the server is up
first: with no `.env`, `assert_production_safe()` refuses to start the app, and a
login request that never reaches a server is not a credentials problem.

`backend/scripts/diagnose_login.py` (read-only) tells the three causes apart on
whichever database the environment points at — run it on the API host, with that
host's environment:
- no arguments — which database, the signing-key fingerprint, and every account
  with its address in `repr()` so a stray space or capital is visible
- `--email … --check-password` — does the password match the stored hash
- `--token` — paste the token from the browser's localStorage: bad signature
  (secret rotated, or two instances signing differently), expired, minted against
  another database, disabled account, or valid — in which case the token is not
  reaching the API and the reverse proxy is dropping `Authorization`.

## Tests
- Located in `backend/tests/`
- Run with: `cd backend && .venv/bin/pytest`
- `ruff check app tests`, `mypy app` and `pytest` all run in CI (`.github/workflows/ci.yml`)
- `asyncio_mode = auto` configured in pyproject.toml

## Deployment
- **Service**: systemd `oricred-backend.service`, uvicorn on `127.0.0.1:8000`
- **Frontend**: Vite build to `frontend/dist/`, served by FastAPI static mount
- **Deploy**: `pip install -e .` for deps, `npm run build` for frontend, `sudo systemctl restart oricred-backend.service`
- **Env file**: `/home/ubuntu/oricred/.env`

## Running Locally
```bash
# Backend
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000

# Frontend
cd frontend && npm run dev
```
