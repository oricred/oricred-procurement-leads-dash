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
│   │   ├── seed.py              # Dev seed data
│   │   ├── api/                 # Route handlers (auth, opportunities, watchlist, radar, dashboard, admin)
│   │   ├── clients/             # Tenders-SA API client wrappers (base, tenders, awards, companies, organizations, reference, forensic)
│   │   ├── jobs/                # APScheduler jobs (discovery, award_check, model_refresh, scheduler, crm_sync)
│   │   ├── models/              # SQLAlchemy ORM models (15 tables)
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── services/            # Business logic (qualification, award_timing, contact_sufficiency, competitor_intel, email_alert, auth, funding_suitability, buyer_relationship, crm/, municipal_scraper)
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

## Key Conventions
- **Env prefix**: `ORICRED_` for all settings
- **DB**: SQLite dev (`sqlite+aiosqlite:///oricred.db`), auto-creates tables via `Base.metadata.create_all`
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

### Remaining
- [ ] Real municipal scraper implementations (at least City of Joburg + Cape Town)
- [ ] Hook CRM push into opportunity creation/stage changes (real-time sync)
- [ ] Monday.com activity displayed in card expansion
- [ ] Tests for new services

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
