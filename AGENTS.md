# Oricred Project Guide

## Tech Stack
- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.0 (async), APScheduler, httpx, Pydantic v2
- **Frontend**: React 18, TypeScript 5, Vite 5, Tailwind CSS 3, @dnd-kit, TanStack Query, Zustand
- **Database**: SQLite (dev), PostgreSQL 16 (prod)
- **Cache**: Redis 7
- **Infra**: systemd service, uvicorn, Docker Compose

## Project Structure
```
oricred/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint, lifespan, CORS, static mount
│   │   ├── config.py            # Pydantic settings (ORICRED_ prefix)
│   │   ├── database.py          # SQLAlchemy async engine + session
│   │   ├── seed.py              # (removed — all data comes from TSA DB ingestion)
│   │   ├── api/                 # Route handlers (auth, opportunities, watchlist, radar, dashboard, admin)
│   │   ├── clients/             # Tenders-SA: TSADatabase (direct SQL) + TSAClient (REST, admin retry only)
│   │   ├── jobs/                # APScheduler jobs (discovery, award_check, model_refresh, scheduler, crm_sync, contact_enrichment)
│   │   ├── models/              # SQLAlchemy ORM models (16 tables + contact, failed_api_call)
│   │   ├── schemas/             # Pydantic request/response schemas (+ contact)
│   │   └── services/            # Business logic (qualification, award_timing, contact_sufficiency, competitor_intel, email_alert, auth, funding_suitability, buyer_relationship, crm/, municipal_scraper, contact_enrichment)
│   ├── alembic/                 # Migrations (empty — uses create_all)
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx, main.tsx
│   │   ├── components/ (Layout, KanbanColumn, OpportunityCard, OpportunityModal, AwardRadar)
│   │   ├── pages/ (LoginPage, PipelinePage, WatchingPage)
│   │   ├── services/api.ts      # Axios client + API functions
│   │   └── types/index.ts       # TS interfaces
│   └── package.json
├── docker-compose.yml
└── docs/
    ├── implementation.md
    └── specifications/ (phase-1, phase-1b, phase-2, phase-3)
```

## Database Rules — CRITICAL
- **Oricred DB (local PostgreSQL)**: All CREATE, UPDATE, DELETE operations must only touch the oricred application database. This is the database configured via the `ORICRED_DATABASE_URL` env var.
- **Tenders-SA DB (TSADatabase)**: This is an external PostgreSQL database provided by Tenders-SA. It is **STRICTLY READ-ONLY**. No INSERT, UPDATE, DELETE, ALTER, DROP, or any other write operations are ever permitted against this database. The `TSADatabase` client only issues SELECT queries. Violating this will break the data source agreement.
- When in doubt about which database a piece of code operates on, check the import path: `app.database` = oricred DB, `app.clients.tsa_db` = Tenders-SA read-only DB.

## Key Conventions
- **Env prefix**: `ORICRED_` for all settings
- **DB**: PostgreSQL 16, auto-creates tables via `Base.metadata.create_all`
- **Auth**: JWT with bcrypt, `POST /api/auth/login` returns `access_token`
- **Models**: UUID string PKs, `DateTime(timezone=True)` for all timestamps
- **API routes**: All under `/api` prefix, mounted in `app/api/__init__.py`
- **Schemas**: Pydantic v2 with `from_attributes = True` for ORM mapping
- **Scheduler**: APScheduler AsyncIOScheduler, jobs logged to `job_runs` table
- **Frontend API**: Axios client with Bearer token interceptor, TanStack Query for data fetching
- **CORS**: Wildcard in dev, locked down in prod

## Phase 2 Implementation Status
### Completed
- [x] Funding-suitability scoring module (`backend/app/services/funding_suitability.py`)
- [x] Buyer-relationship model + analytics engine + API endpoint
- [x] CRM abstraction layer with Monday.com GraphQL adapter
- [x] CRM sync service + scheduled job
- [x] Municipal filter config update (includes "municipal" entity type)
- [x] Municipal scraper adapter foundation (abstract + Joburg/Cape Town stubs)
- [x] Frontend: funding suitability badge on kanban cards
- [x] Frontend: buyer relationship panel in opportunity modal
- [x] Admin UI (7 tabs): Credentials, Filter Config, Sources, Notifications, Scoring, Jobs, Users
- [x] CRM item ID persistence + deduplication (`sync.py` writes `crm_item_id`)
- [x] CRM push to `PATCH /opportunities/{id}/assign` endpoint
- [x] Municipal scrapers wired into discovery job (reads config from DB)
- [x] Monday.com activity detail display in opportunity modal (column changes with old→new)
- [x] Buyer preference scoring (province weights, SOE bonus, preferred buyers)
- [x] Sources tab renamed from Scrapers → Sources with OCPO, e-Tenders, TSA-OCP config
- [x] Monday.com fully configurable via admin UI (API key, board ID, group ID)
- [x] Competitor Intel wired into award_check + displayed in modal (confirmed + speculative)
- [x] `PATCH /opportunities/{id}` for notes/risk_flag/assigned_to editing
- [x] `GET /opportunities/{id}/audit` endpoint + audit history panel in modal
- [x] Past-due queue API + frontend page (`/past-due` route with auto-refresh)
- [x] Dead-letter queue: `FailedApiCall` writes in TSAClient on retry exhaustion
- [x] `GET /admin/failed-api-calls` endpoint for dead-letter management
- [x] Inline notes editing in opportunity modal (edit/save/cancel)
- [x] Contact tracking model, API, and frontend panel in opportunity modal
- [x] TSADatabase — direct PostgreSQL interface to Tenders-SA (read-only, filter-driven)
- [x] Discovery job rewritten to use TSADatabase SQL filters (vs REST API)
- [x] Award check job rewritten for batch SQL (eliminated N+1)
- [x] CompetitorIntelService refactored to use TSADatabase
- [x] Contact enrichment service — pulls directors/key_personnel from TSA DB on schedule
- [x] Tests for contacts, TSADatabase query builders, and competitor intel (53 tests)
- [x] Dead-letter retry button in admin UI (re-queues failed API calls via TSAClient)
- [x] Cleaned up 7 unused REST API client files (now only TSAClient + TSADatabase)

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
