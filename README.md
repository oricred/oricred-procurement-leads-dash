# Oricred — Procurement Intelligence Platform

**Oricred** is an end-to-end procurement intelligence platform for South African public-sector contracts. It integrates with the [Tenders-SA.org Public API](https://tenders-sa.org) to discover, qualify, track, and manage tender and award opportunities through a full lifecycle — from tender publication through to opportunity closure.

---

## Architecture

```
                     ┌──────────────┐
                     │ Tenders-SA   │
                     │ Public API   │
                     └──────┬───────┘
                            │ httpx (async)
                            ▼
               ┌─────────────────────┐
               │   Backend (FastAPI) │
               │   ┌───────────────┐ │
               │   │  APScheduler  │ │ ← 4 recurring jobs
               │   ├───────────────┤ │
               │   │  Services     │ │ ← Qualification, AwardTiming, Contact, Competitor, Email
               │   ├───────────────┤ │
               │   │  API Layer    │ │ ← Auth, Opportunities, Watchlist, Radar, Dashboard, Admin
               │   └──────┬────────┘ │
               └──────────┼──────────┘
                          │
              ┌───────────┴───────────┐
              │                       │
              ▼                       ▼
      ┌──────────────┐       ┌──────────────┐
      │  PostgreSQL   │       │    Redis     │
      │  (SQLite dev) │       │ (caching/q)  │
      └──────────────┘       └──────────────┘
              │
              ▼
      ┌──────────────┐
      │   Frontend   │
      │  React 18 +  │
      │  Vite + TW   │
      └──────────────┘
```

**Tech Stack:**

| Layer | Technology |
|---|---|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2.0 (async), APScheduler, httpx |
| Frontend | React 18, TypeScript 5, Vite 5, Tailwind CSS 3, @dnd-kit, TanStack Query, Zustand |
| Database | PostgreSQL 16 (production), SQLite (dev default) |
| Cache | Redis 7 |
| Infrastructure | Docker Compose |

---

## Core Workflow

The platform operates a continuous pipeline with four main stages:

### 1. Tender Discovery (Every 15 minutes)

The `discover_new_tenders` job polls `GET /tenders/new` on the Tenders-SA API. Each new tender is run through a configurable **qualification filter** pipeline:

| Filter | Purpose |
|---|---|
| **ValueRange** | Estimated value falls within configured min/max bounds |
| **Sector** | Tender category matches included (or excluded) sectors |
| **Province** | Location is in a targeted province |
| **EntityType** | Buyer organization type is targeted (national, provincial, SOE, municipal) |
| **BEE Level** | Expected BEE level requirement is within range |
| **RiskExclusion** | Buyer is not on a restricted-supplier list |

Tenders that pass all filters are added to the **Watchlist** as "watching" items.

### 2. Pre-Award Tracking (Watching Board)

Each watchlist item receives an **expected award window** computed by the `AwardTimingService`:

- Looks up historical (buyer organization + category) → average days from closing to award
- Computes `expected_window_start = closing_date + avg_days - stddev`
- Computes `expected_window_end = closing_date + avg_days + stddev`
- **Cold-start fallback:** if no historical data exists for the (org, category) pair, falls back to category global average, then to a default of 30 ± 15 days

The **Watching Page** displays:
- A progress bar showing where the tender sits in its window (0-100%)
- Status labels: "On Track" (before window), "Approaching Window", "Past Due"
- A countdown until the expected award date

### 3. Award Ingestion (Every 30 Minutes)

The `check_awards_for_watching` job ingests the actual Tenders-SA award feed independently of the tender watchlist. Its first run reads the previous 30 days; thereafter it resumes from the latest successfully ingested award timestamp.

For every source award it:

1. Upserts the tender context when it is available; a minimal tender record is retained if the source award arrives before tender metadata.
2. Enriches the supplier, buyer, and bidder context where available.
3. Upserts the award and creates the related opportunity if no lead exists yet.
4. Marks a matching watched tender as awarded, but never requires a watchlist match to ingest the award.
5. Sends an award alert and queues contact/CRM enrichment for new leads.

Watched tenders remain useful for timing and Past-Due monitoring. A watched tender only becomes Past Due when its expected window has elapsed and there is no locally ingested award for it.
### 4. Opportunity Pipeline

Awarded suppliers enter the current lead workflow:

```
New Lead → Client Contacted → Qualified Lead → Won Opportunity
→ Credit Preparation → Credit Review → Pre-Approved
→ Conditions Precedent → Term Sheet Sent → Term Sheet Received
→ Contracts Sent → Contracts Received → Ready to RFF → Funded
```

A lead may be moved to **Lost Lead** from any active stage with a recorded reason. All forward movement is deliberate from the opportunity panel; contact, credit approval, cleared conditions, backward moves, reopening, and every stage transition are audit logged.
### Award Radar (Side Panel)

The **Award Radar** is a live-updating side panel showing:
- **Past-Due Queue counter** (amber badge when > 0)
- **7-Day Award Feed** — scrolling list of all detected awards (pre-qualification), polling every 30 seconds

---

## Project Structure

```
oricred/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint, lifespan, CORS, static mount
│   │   ├── config.py            # Pydantic settings (ORICRED_ prefix)
│   │   ├── database.py          # SQLAlchemy async engine + session
│   │   ├── seed.py              # Dev seed data (users, categories, orgs, etc.)
│   │   ├── api/                 # Route handlers
│   │   │   ├── auth.py          # POST /auth/login, GET /auth/me
│   │   │   ├── opportunities.py # CRUD + stage transitions
│   │   │   ├── watchlist.py     # GET /watchlist
│   │   │   ├── radar.py         # GET /radar
│   │   │   ├── dashboard.py     # GET /dashboard/stats
│   │   │   └── admin.py         # Filter-config CRUD
│   │   ├── clients/             # Tenders-SA API client wrappers
│   │   │   ├── base.py          # TSAClient (httpx, retry, rate-limit)
│   │   │   ├── tenders.py       # /tenders/* endpoints
│   │   │   ├── awards.py        # /awards/* endpoints
│   │   │   ├── companies.py     # /companies/* endpoints
│   │   │   ├── organizations.py # /organizations/* endpoints
│   │   │   ├── reference.py     # /categories, /provinces
│   │   │   └── forensic.py      # /forensic/*, /match
│   │   ├── jobs/                # APScheduler job definitions
│   │   │   ├── discovery.py     # discover_new_tenders (15 min)
│   │   │   ├── award_check.py   # check_awards_for_watching (hourly)
│   │   │   ├── model_refresh.py # refresh_timing_model (weekly)
│   │   │   └── scheduler.py     # Scheduler registration
│   │   ├── models/              # SQLAlchemy ORM models
│   │   │   ├── tender.py        # Tenders from API
│   │   │   ├── award.py         # Award records
│   │   │   ├── company.py       # Supplier companies
│   │   │   ├── organization.py  # Buyer organizations
│   │   │   ├── opportunity.py   # Kanban opportunities + audit log
│   │   │   ├── watchlist.py     # Tracked tenders
│   │   │   ├── timing_model.py  # Award-timing predictions
│   │   │   ├── past_due.py      # Past-due queue
│   │   │   ├── filter_config.py # Qualification filter config
│   │   │   ├── alert_log.py     # Email alert audit trail
│   │   │   ├── job_run.py       # Job execution tracking
│   │   │   ├── failed_api_call.py # Dead-letter queue
│   │   │   ├── user.py          # Auth users
│   │   │   └── category.py      # Tender categories
│   │   ├── schemas/             # Pydantic request/response schemas
│   │   └── services/            # Business logic
│   │       ├── qualification.py # Filter engine (6-stage pipeline)
│   │       ├── award_timing.py  # Historical avg/stddev computation
│   │       ├── contact_sufficiency.py # Org contact classifier
│   │       ├── competitor_intel.py # Pre-close + at-close competitor resolution
│   │       ├── email_alert.py   # Templated email sending
│   │       └── auth.py          # JWT + bcrypt
│   ├── alembic/                 # Migration framework (empty)
│   ├── Dockerfile               # Python 3.12-slim
│   └── pyproject.toml           # Dependencies + tooling config
├── frontend/
│   ├── src/
│   │   ├── App.tsx              # Router (login, pipeline, watching)
│   │   ├── main.tsx             # Entry: QueryClient + BrowserRouter
│   │   ├── components/
│   │   │   ├── Layout.tsx       # Sidebar + header + Outlet
│   │   │   ├── KanbanColumn.tsx # Droppable column (dnd-kit)
│   │   │   ├── OpportunityCard.tsx # Draggable card
│   │   │   ├── OpportunityModal.tsx # Detail modal (4 panels)
│   │   │   └── AwardRadar.tsx   # Side panel with award feed
│   │   ├── pages/
│   │   │   ├── LoginPage.tsx    # JWT login form
│   │   │   ├── PipelinePage.tsx # Kanban board with DndContext
│   │   │   └── WatchingPage.tsx # Watchlist grid with progress bars
│   │   ├── services/api.ts      # Axios client + API functions
│   │   └── types/index.ts       # TypeScript interfaces + constants
│   ├── vite.config.ts           # Dev proxy /api → :8000
│   ├── tailwind.config.js       # Dark theme custom palette
│   └── package.json             # React 18, Vite 5, etc.
├── docker-compose.yml           # PostgreSQL + Redis + Backend
├── .env.example                 # Environment variable template
└── docs/
    ├── implementation.md        # Master implementation plan
    └── specifications/          # Phase specs (1, 1B, 2, 3)
```

---

## Database Schema

The system uses 14 tables:

| Table | Purpose |
|---|---|
| `users` | Authentication (email, bcrypt password, role) |
| `tenders` | Procurements from Tenders-SA API |
| `awards` | Contract awards linked to tenders |
| `companies` | Supplier companies (BEE, forensic risk) |
| `organizations` | Buyer entities (contact info, confidence) |
| `categories` | Hierarchical tender categories |
| `watchlist_items` | Tenders being tracked (status, expected window) |
| `opportunities` | Kanban pipeline items (stage, version, risk) |
| `opportunity_audit` | Stage transition audit trail |
| `award_timing_model` | Computed avg/stddev days-to-award per (org, category) |
| `past_due_queue` | Tenders past expected award window |
| `filter_config` | JSONB qualification filter configuration |
| `alert_log` | Email alert delivery audit trail |
| `job_runs` | Scheduler job execution tracking |
| `failed_api_calls` | Dead-letter queue for API failures |

---

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/auth/login` | JWT login |
| `GET` | `/api/auth/me` | Current user info |
| `GET` | `/api/opportunities` | List opportunities (filterable by stage/assignee) |
| `GET` | `/api/opportunities/{id}` | Full opportunity detail |
| `PATCH` | `/api/opportunities/{id}/stage` | Update kanban stage (version-checked) |
| `PATCH` | `/api/opportunities/{id}/assign` | Assign opportunity to user |
| `GET` | `/api/radar` | 7-day award feed + past-due count |
| `GET` | `/api/watchlist` | Active watching items |
| `GET` | `/api/dashboard/stats` | Stage counts, totals, past-due |
| `GET` | `/api/admin/filter-config` | Get qualification filter config |
| `PUT` | `/api/admin/filter-config` | Update qualification filter config |

---

## Scheduler Jobs

| Job | Schedule | Description |
|---|---|---|
| `discover_new_tenders` | Every 15 minutes | Polls `/tenders/new`, runs qualification filter, adds to watchlist |
| `check_awards_for_watching` | Every 30 minutes | Incrementally ingests Tenders-SA awards; watches provide optional award and past-due context |
| `refresh_timing_model` | Weekly (Sun 2am) | Recomputes award-timing model from historical data |

All jobs log execution results to the `job_runs` table.

---

## Setup & Running

### Local Development (SQLite, no Docker)

Prerequisites: Python 3.12+, Node.js 20+

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate    # Windows
pip install -e .
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

The backend seeds automatically on first startup with:
- **Users:** `admin@oricred.com` / `admin123` (admin), `ops@oricred.com` / `ops123` (operator)
- **7 categories, 4 organizations, 6 companies, 5 tenders, 3 awards, 2 watchlist items, 3 opportunities**

Open `http://localhost:5173` and log in.

### Production (Docker)

```bash
cp .env.example .env
# Edit .env with your Tenders-SA API key and secrets
docker compose up -d
```

### Configuration

All configuration is via environment variables with the `ORICRED_` prefix:

| Variable | Default | Description |
|---|---|---|
| `ORICRED_TSA_API_KEY` | — | Tenders-SA API key |
| `ORICRED_DATABASE_URL` | `sqlite+aiosqlite:///oricred.db` | Database connection string |
| `ORICRED_REDIS_URL` | — | Redis connection (optional, for caching) |
| `ORICRED_JWT_SECRET` | — | JWT signing secret |
| `ORICRED_JWT_ALGORITHM` | `HS256` | JWT algorithm |
| `ORICRED_JWT_EXPIRE_MINUTES` | `480` | JWT token expiry |
| `ORICRED_SMTP_HOST` | — | SMTP server for email alerts |
| `ORICRED_SMTP_PORT` | `587` | SMTP port |
| `ORICRED_SESSION_SECRET` | — | Session cookie secret |
| `ORICRED_DEBUG` | `false` | Enable debug mode |

---

## Qualification Filter Configuration

The qualification filter is a JSONB configuration stored in the `filter_config` table and editable via `PUT /api/admin/filter-config`:

```json
{
  "value_range": { "min": 500000, "max": 50000000 },
  "sectors": { "include": ["Construction", "Infrastructure", "IT Services"], "exclude": ["Cleaning", "Catering"] },
  "provinces": ["Gauteng", "Western Cape", "KwaZulu-Natal"],
  "entity_types": ["national", "provincial", "soe"],
  "bee_level": { "min": 1, "max": 4 },
  "risk_exclusion": { "enabled": true }
}
```

---

## Phased Roadmap

| Phase | Focus | Status |
|---|---|---|
| **Phase 1** | Core platform: Tenders-SA integration, timing model, qualification filter, kanban dashboard, contact classifier, email alerts | ✅ Complete |
| **Phase 1B** | SOE portal checker + OCPO Gazette PDF parsing for missing awards | 📋 Planned |
| **Phase 2** | Municipal procurement coverage, buyer-relationship analytics, Monday.com CRM, funding-suitability scoring | 📋 Planned |
| **Phase 3** | Predictive intelligence: forecasting, win-probability modeling, director network graphs, anomaly detection | 📋 Planned |

Phase 1B triggers when the past-due queue sustains volume — indicating that SOEs are publishing awards through internal portals before the central Tenders-SA API is updated.
