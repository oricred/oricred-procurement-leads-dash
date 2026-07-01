# Phase 1 — Core Platform — Detailed Specification

**Status:** Approved
**Version:** 2.0 (detailed)

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Tech Stack](#2-tech-stack)
3. [API Integration Layer](#3-api-integration-layer)
4. [Database Schema](#4-database-schema)
5. [Core Workflow Engine](#5-core-workflow-engine)
6. [Award-Timing Model](#6-award-timing-model)
7. [Qualification Filter Engine](#7-qualification-filter-engine)
8. [Contact-Sufficiency Classifier](#8-contact-sufficiency-classifier)
9. [Competitor Intelligence](#9-competitor-intelligence)
10. [Kanban Dashboard](#10-kanban-dashboard)
11. [Email Alerting Service](#11-email-alerting-service)
12. [Scheduler & Job Definitions](#12-scheduler--job-definitions)
13. [Security Model](#13-security-model)
14. [Deployment Architecture](#14-deployment-architecture)
15. [Testing Strategy](#15-testing-strategy)
16. [Monitoring & Observability](#16-monitoring--observability)
17. [Deliverables](#17-deliverables)
18. [Acceptance Criteria](#18-acceptance-criteria)
19. [Deferred Scope](#19-deferred-scope)

---

## 1. System Architecture

### 1.1 High-Level Component Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                        Scheduler                            │
│  (cron jobs: tender poll, model refresh, past-due checks)   │
└──────────┬──────────────────────────────────┬───────────────┘
           │                                  │
           ▼                                  ▼
┌─────────────────────┐          ┌──────────────────────────┐
│  Polling Workers    │          │   Award-Timing Model     │
│  (tender discovery, │          │   (weekly batch compute) │
│   award checks)     │          └────────────┬─────────────┘
└──────────┬──────────┘                       │
           │                                  │
           ▼                                  ▼
┌────────────────────────────────────────────────────────────┐
│                    Core Service                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐ │
│  │  TSA     │  │Qualifica-│  │ Contact  │  │ Known-    │ │
│  │  Client  │  │ tion     │  │Suffici-  │  │ Supplier  │ │
│  │  Module  │  │ Filter   │  │ency      │  │ Short-    │ │
│  │          │  │ Engine   │  │Classifier│  │ circuit   │ │
│  └──────────┘  └──────────┘  └──────────┘  └───────────┘ │
└────────────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────┐
│                       Database                              │
│     PostgreSQL: tenders, awards, companies, organizations,  │
│     opportunities, award_timing_model, filter_config,       │
│     past_due_queue, alert_log, job_runs                    │
└────────────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────┐
│                    Web Application                          │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │
│  │  Kanban      │  │  Award       │  │  Watching      │   │
│  │  Pipeline    │  │  Radar Panel │  │  Board         │   │
│  └──────────────┘  └──────────────┘  └────────────────┘   │
│  ┌────────────────────────────────────────────────────┐    │
│  │  Card Expansion: Award Detail | Company Intel |    │    │
│  │  Org Contact | Competitor List                     │    │
│  └────────────────────────────────────────────────────┘    │
└────────────────────────────────────────────────────────────┘
           │
           ▼
┌────────────────────────────────────────────────────────────┐
│              Email Alerting Service                         │
│  (SMTP / transactional email API)                           │
└────────────────────────────────────────────────────────────┘
```

### 1.2 Service Boundaries

All Phase 1 functionality runs as a **single backend service** (monolith deploy). Rationale:
- Team size is small; microservices add overhead without benefit at this stage.
- All components share the same database.
- If scale requires splitting later, the internal module boundaries are clean enough to extract.

The **Scheduler** is a separate lightweight process (or cron container) that triggers job functions in the main service via internal RPC or direct module calls.

---

## 2. Tech Stack

### 2.1 Backend

| Component | Choice | Rationale |
|---|---|---|
| Language | Python 3.12 | Team familiarity, rich data ecosystem, Tenders-SA SDK potential |
| Web framework | FastAPI | Async support, OpenAPI auto-docs, high performance |
| ORM | SQLAlchemy 2.0 + asyncpg | Mature, async, well-typed |
| Migration tool | Alembic | Standard for SQLAlchemy |
| Task queue | ARQ (Redis-based) | Lightweight async job queue for polling workers |
| Scheduler | APScheduler + cron | Recurring job scheduling |
| HTTP client | httpx (async) | Native async, connection pooling, retry support |
| Validation | Pydantic v2 | Schema validation, used by FastAPI natively |

### 2.2 Frontend

| Component | Choice | Rationale |
|---|---|---|
| Framework | React 18 + TypeScript | Type safety, ecosystem |
| State management | Zustand | Lightweight, minimal boilerplate |
| UI components | Tailwind CSS + Radix UI | Utility-first + accessible primitives |
| Drag-and-drop | dnd-kit | Kanban column drag-and-drop |
| Data fetching | TanStack Query (React Query) | Caching, polling, optimistic updates |
| Charts | Recharts | Award radar timeline charts |
| Build tool | Vite | Fast dev, tree-shaking |

### 2.3 Infrastructure

| Component | Choice | Rationale |
|---|---|---|
| Database | PostgreSQL 16 | JSONB for raw API payloads, indexing, reliability |
| Cache / queue | Redis 7 | ARQ task queue, optional caching |
| Container | Docker + docker-compose | Dev parity with production |
| Hosting | Linux VPS / AWS EC2 or equivalent | Simple, cost-effective for single service |

---

## 3. API Integration Layer

### 3.1 Module Structure

```
app/
  clients/
    __init__.py
    base.py              # Base HTTP client with auth, retry, rate-limit handling
    tenders.py           # /tenders/* endpoints
    awards.py            # /awards/* endpoints
    companies.py         # /companies/* endpoints
    organizations.py     # /organizations/* endpoints
    forensic.py          # /forensic/* endpoints
    categories.py        # /categories, /provinces, /match endpoints

  models/
    tenders.py           # Pydantic models for tender API responses
    awards.py
    companies.py
    organizations.py
    forensic.py
```

### 3.2 Base HTTP Client

```python
# app/clients/base.py — pseudocode for design

class TSAClient:
    """Thread-safe async HTTP client for Tenders-SA API."""

    BASE_URL = "https://api.tenders-sa.org"
    MAX_RETRIES = 3
    RETRY_DELAYS = [1, 4, 16]  # seconds

    def __init__(self, api_key: str):
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30.0,
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=50),
        )

    async def request(self, method: str, path: str, **kwargs) -> dict:
        """Send request with retry and rate-limit handling."""
        last_exception = None
        for attempt in range(self.MAX_RETRIES + 1):
            try:
                response = await self._client.request(method, path, **kwargs)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", "60"))
                    await asyncio.sleep(retry_after)
                    continue
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (401, 403, 404):
                    raise  # Don't retry auth/not-found errors
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
                else:
                    raise
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(self.RETRY_DELAYS[attempt])
        raise last_exception  # All retries exhausted
```

### 3.3 Endpoint Client Example

```python
# app/clients/tenders.py
class TendersClient:
    def __init__(self, client: TSAClient):
        self._client = client

    async def get_new_tenders(self, since: datetime) -> list[TenderSummary]:
        data = await self._client.request("GET", "/tenders/new", params={
            "since": since.isoformat(),
            "limit": 100,
        })
        return [TenderSummary(**item) for item in data["tenders"]]

    async def get_tender_detail(self, tender_id: str) -> TenderDetail:
        data = await self._client.request("GET", f"/tenders/{tender_id}")
        return TenderDetail(**data["tender"])

    async def get_bidders(self, tender_id: str) -> list[Bidder]:
        data = await self._client.request("GET", f"/tenders/{tender_id}/bidders")
        return [Bidder(**item) for item in data["bidders"]]
```

### 3.4 Caching Strategy

| Data Type | Cache TTL | Cache Key |
|---|---|---|
| Category list | 24h | `ref:categories` |
| Province list | 24h | `ref:provinces` |
| Company profile | 1h | `company:{name}` |
| Organization profile | 1h | `org:{id}` |
| Tender detail | 15min | `tender:{id}` |
| Award timing analytics (raw) | 24h | `analytics:award_timing` |

Cache stored in Redis. Cache-aside pattern: read from cache, fall back to API, write result to cache.

### 3.5 Polling Strategy

```python
# Pseudocode for the tender discovery poll worker
async def discover_new_tenders():
    last_poll = await get_last_poll_timestamp("tender_discovery")
    now = datetime.utcnow()

    tenders = await tenders_client.get_new_tenders(since=last_poll)

    for tender in tenders:
        with db.session() as session:
            existing = session.query(Tender).filter_by(
                api_id=tender.id
            ).first()
            if existing:
                continue

            # Store raw tender
            db_tender = Tender(
                api_id=tender.id,
                raw_payload=tender.model_dump(),
                title=tender.title,
                estimated_value=tender.estimated_value,
                province=tender.province,
                category_id=tender.category_id,
                closing_date=tender.closing_date,
                buyer_org_id=tender.organization_id,
                discovered_at=now,
            )
            session.add(db_tender)
            session.flush()

            # Run qualification filter
            passes = await qualification_engine.evaluate(db_tender)
            if passes:
                session.add(WatchlistItem(
                    tender_id=db_tender.id,
                    status="watching",
                    started_watching_at=now,
                ))
                # Compute expected award window
                await award_timing_service.assign_window(db_tender)

            await record_poll_timestamp("tender_discovery", now)

    # Update last poll timestamp
    await set_last_poll_timestamp("tender_discovery", now)
```

### 3.6 Dead-Letter Queue

Failed API calls after 3 retries are written to a `failed_api_calls` table:

| Column | Type | Description |
|---|---|---|
| `id` | UUID PK | |
| `endpoint` | text | e.g. `/tenders/{id}` |
| `params` | jsonb | Request params |
| `error` | text | Error message |
| `attempts` | int | Retry count |
| `failed_at` | timestamptz | |
| `resolved` | bool | Manual resolution flag |

---

## 4. Database Schema

### 4.1 Entity-Relationship Overview

```
tenders ──1:N──> awards
tenders ──1:1──> watchlist_items
tenders ──1:N──> past_due_queue

companies ──1:N──> opportunities
organizations ──1:N──> tenders
organizations ──1:N──> awards

opportunities ──1:1──> kanban_state
opportunities ──1:N──> alert_log

award_timing_model ──N:1──> organizations
award_timing_model ──N:1──> categories
```

### 4.2 Table: `tenders`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK, default gen_random_uuid() | |
| `api_id` | `varchar(64)` | UNIQUE, NOT NULL | Tenders-SA API tender ID |
| `raw_payload` | `jsonb` | NOT NULL | Full API response for reprocessing |
| `title` | `text` | NOT NULL | |
| `description` | `text` | | |
| `estimated_value` | `decimal(15,2)` | | |
| `province` | `varchar(64)` | | |
| `category_id` | `varchar(32)` | FK → categories.id | |
| `closing_date` | `timestamptz` | | |
| `buyer_org_id` | `varchar(32)` | FK → organizations.id | |
| `tender_type` | `varchar(32)` | | |
| `published_at` | `timestamptz` | | From API |
| `discovered_at` | `timestamptz` | NOT NULL | When we first saw it |
| `created_at` | `timestamptz` | NOT NULL, default now() | |
| `updated_at` | `timestamptz` | NOT NULL, default now() | |
| `deleted_at` | `timestamptz` | | Soft delete |

**Indexes:**
- `idx_tenders_api_id` UNIQUE on `api_id`
- `idx_tenders_discovered_at` on `discovered_at`
- `idx_tenders_closing_date` on `closing_date`
- `idx_tenders_buyer_org` on `buyer_org_id`
- `idx_tenders_category` on `category_id`

### 4.3 Table: `awards`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `api_id` | `varchar(64)` | UNIQUE | |
| `tender_id` | `uuid` | FK → tenders.id, NOT NULL | |
| `raw_payload` | `jsonb` | | |
| `supplier_name` | `text` | NOT NULL | |
| `supplier_company_id` | `varchar(64)` | FK → companies.api_id | Resolved company |
| `amount` | `decimal(15,2)` | | |
| `award_date` | `timestamptz` | | |
| `bee_level` | `int` | | |
| `bee_points` | `int` | | |
| `buyer_org_id` | `varchar(32)` | FK → organizations.id | |
| `source` | `varchar(16)` | NOT NULL, default `'tenders_api'` | Data source |
| `discovered_at` | `timestamptz` | NOT NULL | |
| `created_at` | `timestamptz` | NOT NULL | |

**Indexes:**
- `idx_awards_tender_id` on `tender_id`
- `idx_awards_supplier` on `supplier_name`
- `idx_awards_award_date` on `award_date`
- `idx_awards_source` on `source`

### 4.4 Table: `companies`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `api_id` | `varchar(64)` | UNIQUE | Tenders-SA company identifier |
| `name` | `text` | NOT NULL | |
| `registration_number` | `varchar(64)` | | |
| `bee_level` | `int` | | |
| `cipc_forensic_risk_score` | `decimal(5,2)` | | 0.00–100.00 |
| `cipc_compliance_status` | `varchar(32)` | | |
| `restricted_supplier` | `bool` | NOT NULL, default false | |
| `raw_payload` | `jsonb` | | |
| `last_refreshed_at` | `timestamptz` | | |
| `created_at` | `timestamptz` | NOT NULL | |

**Indexes:**
- `idx_companies_api_id` UNIQUE on `api_id`
- `idx_companies_name` on `name` (for fuzzy matching)
- `idx_companies_bee_level` on `bee_level`
- `idx_companies_restricted` on `restricted_supplier`

### 4.5 Table: `organizations`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `varchar(32)` | PK | Tenders-SA org ID |
| `name` | `text` | NOT NULL | |
| `organization_type` | `varchar(32)` | | national, provincial, municipal, soe |
| `industry_codes` | `text[]` | | |
| `contact_email` | `varchar(256)` | | |
| `contact_phone` | `varchar(32)` | | |
| `contact_website` | `varchar(256)` | | |
| `contact_email_is_role_based` | `bool` | | |
| `confidence_score` | `decimal(4,3)` | | 0.000–1.000 |
| `raw_payload` | `jsonb` | | |
| `last_refreshed_at` | `timestamptz` | | |
| `created_at` | `timestamptz` | NOT NULL | |

**Indexes:**
- `idx_orgs_type` on `organization_type`
- `idx_orgs_name` on `name`

### 4.6 Table: `categories`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `varchar(32)` | PK | |
| `name` | `text` | NOT NULL | |
| `parent_id` | `varchar(32)` | | Hierarchical category |
| `raw_payload` | `jsonb` | | |

### 4.7 Table: `watchlist_items`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `tender_id` | `uuid` | FK → tenders.id, UNIQUE | |
| `status` | `varchar(16)` | NOT NULL | `watching`, `awarded`, `past_due`, `expired` |
| `expected_window_start` | `timestamptz` | | From award-timing model |
| `expected_window_end` | `timestamptz` | | |
| `started_watching_at` | `timestamptz` | NOT NULL | |
| `awarded_at` | `timestamptz` | | |
| `past_due_at` | `timestamptz` | | |
| `created_at` | `timestamptz` | NOT NULL | |

**Indexes:**
- `idx_watchlist_status` on `status`
- `idx_watchlist_window_end` on `expected_window_end`

### 4.8 Table: `opportunities`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `tender_id` | `uuid` | FK → tenders.id | Null for manual entries |
| `award_id` | `uuid` | FK → awards.id | |
| `company_id` | `uuid` | FK → companies.id | |
| `kanban_stage` | `varchar(32)` | NOT NULL | `new`, `assigned`, `contacted`, `in_discussion`, `application_received`, `funded`, `closed` |
| `assigned_to` | `varchar(128)` | | User identifier |
| `contact_sufficiency` | `varchar(8)` | | `sufficient`, `role_based`, `none` |
| `risk_flag` | `varchar(8)` | | `red`, `amber`, `green` |
| `win_probability` | `decimal(5,2)` | | 0.00–100.00 (Phase 3, null in Phase 1) |
| `funding_suitability` | `decimal(5,2)` | | 0.00–100.00 (Phase 2, null in Phase 1) |
| `notes` | `text` | | |
| `created_at` | `timestamptz` | NOT NULL | |
| `updated_at` | `timestamptz` | NOT NULL | |
| `closed_at` | `timestamptz` | | |
| `version` | `int` | NOT NULL, default 1 | Optimistic concurrency |

**Indexes:**
- `idx_opportunities_stage` on `kanban_stage`
- `idx_opportunities_company` on `company_id`
- `idx_opportunities_assigned` on `assigned_to`

### 4.9 Table: `award_timing_model`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `organization_id` | `varchar(32)` | FK → organizations.id | |
| `category_id` | `varchar(32)` | FK → categories.id | |
| `avg_days_to_award` | `decimal(8,2)` | | Mean of (award_date − closing_date) |
| `stddev_days_to_award` | `decimal(8,2)` | | Standard deviation |
| `sample_count` | `int` | NOT NULL | Number of historical awards used |
| `min_days` | `int` | | |
| `max_days` | `int` | | |
| `computed_at` | `timestamptz` | NOT NULL | |
| `created_at` | `timestamptz` | NOT NULL | |

**Indexes:**
- `idx_atm_org_category` UNIQUE on `(organization_id, category_id)`
- `idx_atm_sample_count` on `sample_count`

### 4.10 Table: `past_due_queue`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `tender_id` | `uuid` | FK → tenders.id, UNIQUE | |
| `entered_queue_at` | `timestamptz` | NOT NULL | |
| `poll_count_since_due` | `int` | NOT NULL, default 0 | |
| `last_polled_at` | `timestamptz` | | |
| `resolution` | `varchar(16)` | | `pending`, `award_found`, `no_award_confirmed`, `escalated` |
| `resolved_at` | `timestamptz` | | |
| `notes` | `text` | | |

### 4.11 Table: `filter_config`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `key` | `varchar(32)` | UNIQUE, NOT NULL | Config key |
| `value` | `jsonb` | NOT NULL | Config value |
| `description` | `text` | | |
| `enabled` | `bool` | NOT NULL, default true | |
| `updated_at` | `timestamptz` | NOT NULL | |
| `updated_by` | `varchar(128)` | | |

### 4.12 Table: `alert_log`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `event_type` | `varchar(32)` | NOT NULL | |
| `recipient` | `varchar(256)` | NOT NULL | |
| `subject` | `text` | | |
| `body` | `text` | | |
| `sent_at` | `timestamptz` | NOT NULL | |
| `delivery_status` | `varchar(16)` | | `sent`, `failed`, `bounced` |
| `error` | `text` | | |

**Indexes:**
- `idx_alert_event_type` on `event_type`
- `idx_alert_sent_at` on `sent_at`

### 4.13 Table: `job_runs`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `job_name` | `varchar(64)` | NOT NULL | |
| `started_at` | `timestamptz` | NOT NULL | |
| `finished_at` | `timestamptz` | | |
| `status` | `varchar(16)` | | `running`, `success`, `failed` |
| `error` | `text` | | |
| `items_processed` | `int` | | |

### 4.14 Table: `failed_api_calls`

| Column | Type | Constraints | Description |
|---|---|---|---|
| `id` | `uuid` | PK | |
| `endpoint` | `text` | NOT NULL | |
| `params` | `jsonb` | | |
| `error` | `text` | | |
| `attempts` | `int` | NOT NULL | |
| `failed_at` | `timestamptz` | NOT NULL | |
| `resolved` | `bool` | NOT NULL, default false | |

---

## 5. Core Workflow Engine

### 5.1 End-to-End Flow (Detailed)

```
Step 1: TENDER DISCOVERY (every 15 min)
  └─ Poll /tenders/new since last_poll_timestamp
  └─ For each new tender:
       ├─ Insert into tenders table
       ├─ Run Qualification Filter (§7)
       │    ├─ PASS → Insert into watchlist_items (status=watching)
       │    │          Compute expected award window (§6)
       │    │          
       │    └─ FAIL → Log as discarded (no further action)
       └─ Store raw_payload

Step 2: WATCHING (daily poll for each active watchlist item)
  └─ For each watchlist_item where status=watching:
       ├─ Check expected_window_end vs now()
       │    ├─ Now < window_end → poll /awards/by-tender/{id}
       │    │    ├─ Award found → Step 3
       │    │    └─ No award → continue watching (next cycle)
       │    │
       │    └─ Now > window_end, no award → Step 4 (past-due)
       └─

Step 3: AWARD DETECTED
  ├─ Fetch award detail from /awards/by-tender/{id}
  ├─ Insert into awards table
  ├─ Update watchlist_item (status=awarded, awarded_at=now)
  ├─ Fetch company: /companies/{supplier_name}
  │    ├─ Found → upsert companies table
  │    └─ Not found → queue for manual lookup (§9)
  ├─ Fetch organization: /organizations/{buyer_org_id}
  │    └─ Upsert organizations table
  ├─ Forensic screen: POST /forensic/restricted-suppliers/check
  │    └─ Set risk_flag (red/amber/green)
  ├─ Contact sufficiency check (§8)
  │    └─ Set contact_sufficiency
  ├─ Competitor intelligence (§9)
  │    ├─ Pre-close: query /companies/top for speculative list
  │    └─ At close: query /tenders/{id}/bidders for confirmed list
  ├─ Create opportunity record (kanban_stage=new)
  └─ Send email alert (§11)

Step 4: PAST-DUE (no award found past expected window)
  ├─ Insert into past_due_queue
  ├─ Update watchlist_item (status=past_due)
  ├─ Escalate poll frequency to hourly
  └─ If past-due queue threshold exceeded → alert ops lead (§11)
```

### 5.2 State Machine: Watchlist Item

```
                  ┌──────────┐
                  │ watching │
                  └────┬─────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
         award found       window expired
              │                 │
              ▼                 ▼
         ┌─────────┐     ┌───────────┐
         │ awarded │     │ past_due  │
         └─────────┘     └─────┬─────┘
                               │
                      ┌────────┴────────┐
                      ▼                 ▼
                 award found       escalated
                 (by Phase 1B)     (manual)
                      │                 │
                      ▼                 ▼
                 ┌─────────┐     ┌───────────┐
                 │ awarded │     │ expired   │
                 └─────────┘     └───────────┘
```

### 5.3 State Machine: Opportunity (Kanban)

```
New ──> Assigned ──> Contacted ──> In Discussion ──> Application Received ──> Funded
 │                                                                              │
 └──────────────────────── Closed ──────────────────────────────────────────────┘
```

Stage transitions are idempotent (setting the same stage twice is a no-op). Each transition logs to an `opportunity_audit` table (see §10).

---

## 6. Award-Timing Model

### 6.1 Algorithm Detail

```python
# app/services/award_timing.py

async def compute_timing_model():
    """Weekly batch: compute avg/stddev days-to-award per (org, category)."""

    query = """
    SELECT
        a.buyer_org_id AS organization_id,
        t.category_id,
        AVG(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400) AS avg_days,
        STDDEV(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400) AS stddev_days,
        COUNT(*) AS sample_count,
        MIN(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400)::int AS min_days,
        MAX(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400)::int AS max_days
    FROM awards a
    JOIN tenders t ON t.id = a.tender_id
    WHERE a.award_date IS NOT NULL
      AND t.closing_date IS NOT NULL
      AND a.source = 'tenders_api'
    GROUP BY a.buyer_org_id, t.category_id
    """

    results = await db.execute(query)

    for row in results:
        await upsert_model_row(
            organization_id=row.organization_id,
            category_id=row.category_id,
            avg_days=round(row.avg_days, 2),
            stddev_days=round(row.stddev_days, 2),
            sample_count=row.sample_count,
            min_days=row.min_days,
            max_days=row.max_days,
        )

    # Compute category-level global averages for cold-start fallback
    await compute_category_globals()
```

### 6.2 Category-Level Fallback

```python
async def compute_category_globals():
    """Aggregate across all orgs per category for cold-start fallback."""
    query = """
    SELECT
        t.category_id,
        AVG(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400) AS avg_days,
        STDDEV(EXTRACT(EPOCH FROM (a.award_date - t.closing_date)) / 86400) AS stddev_days,
        COUNT(*) AS sample_count
    FROM awards a
    JOIN tenders t ON t.id = a.tender_id
    WHERE a.award_date IS NOT NULL AND t.closing_date IS NOT NULL
      AND a.source = 'tenders_api'
    GROUP BY t.category_id
    """
    results = await db.execute(query)
    for row in results:
        await set_cache(
            f"model:global:{row.category_id}",
            {"avg_days": round(row.avg_days, 2), "stddev": round(row.stddev_days, 2)},
            ttl=604800,  # 7 days
        )
```

### 6.3 Prediction Lookup

```python
async def get_expected_window(tender: Tender) -> tuple[datetime, datetime]:
    """Return (window_start, window_end) for a tender."""

    # Try specific (org, category) model
    model = await db.execute("""
        SELECT avg_days_to_award, stddev_days_to_award
        FROM award_timing_model
        WHERE organization_id = :org_id AND category_id = :cat_id
          AND sample_count >= 3
    """, {"org_id": tender.buyer_org_id, "cat_id": tender.category_id})

    if model:
        avg_days = model.avg_days_to_award
        stddev = model.stddev_days_to_award
    else:
        # Fall back to category global
        fallback = await get_cache(f"model:global:{tender.category_id}")
        if fallback:
            avg_days = fallback["avg_days"]
            stddev = fallback["stddev"]
        else:
            # No data at all — use a default 30-day window
            avg_days = 30
            stddev = 15

    window_start = tender.closing_date + timedelta(days=max(0, avg_days - stddev))
    window_end = tender.closing_date + timedelta(days=avg_days + stddev)
    return window_start, window_end
```

### 6.4 Edge Cases

| Scenario | Handling |
|---|---|
| `closing_date` is null | Set window to null; tender remains in watching with manual review flag |
| `avg_days_to_award` is negative (award before closing — data anomaly) | Clamp `window_start` to `closing_date` |
| `stddev` is 0 (single sample) | Use ±15 days as minimum spread |
| No model data at any level (brand new category) | Use default 30±15 day window; log for monitoring |
| Tender's closing_date is in the past on discovery | Compute window immediately; if past window, go straight to past-due queue |

---

## 7. Qualification Filter Engine

### 7.1 Architecture

```
Input: Tender (raw data from tenders table)
         │
         ▼
┌───────────────────────────────────────────┐
│  Filter Pipeline (ordered evaluation)     │
│                                           │
│  1. Value Range Filter   ──fail──> DISCARD│
│  2. Sector Filter        ──fail──> DISCARD│
│  3. Province Filter      ──fail──> DISCARD│
│  4. Entity Type Filter   ──fail──> DISCARD│
│  5. BEE Level Filter     ──fail──> DISCARD│
│  6. Risk Exclusion Filter──fail──> DISCARD│
│                                           │
│  All pass ──> ACCEPT (add to watchlist)   │
└───────────────────────────────────────────┘
```

### 7.2 Filter Config Schema (JSON)

Stored in `filter_config` table as JSONB. Default seed config:

```json
{
  "value_range": {
    "enabled": true,
    "rules": [
      {
        "field": "estimated_value",
        "min": 500000.00,
        "max": null
      }
    ]
  },
  "sector": {
    "enabled": true,
    "rules": [
      {
        "type": "include",
        "values": ["construction", "infrastructure", "it-services", "consulting"],
        "field": "category_id"
      },
      {
        "type": "exclude",
        "values": ["cleaning", "catering", "security-guarding"],
        "field": "category_id"
      }
    ]
  },
  "province": {
    "enabled": true,
    "rules": [
      {
        "type": "include",
        "values": ["gp", "wc", "kzn", "ec"]
      }
    ]
  },
  "entity_type": {
    "enabled": true,
    "rules": [
      {
        "type": "include",
        "values": ["national", "provincial", "soe"]
      }
    ]
  },
  "bee_level": {
    "enabled": true,
    "rules": [
      {
        "min_level": 1,
        "max_level": 4,
        "min_points": 75
      }
    ]
  },
  "risk_exclusion": {
    "enabled": true,
    "rules": [
      {
        "exclude_if_restricted": true,
        "max_forensic_score": 70.0
      }
    ]
  }
}
```

### 7.3 Filter Evaluation Engine

```python
# app/services/qualification.py

class FilterEngine:
    def __init__(self, config_repo: FilterConfigRepository):
        self._config = config_repo

    async def evaluate(self, tender: Tender) -> FilterResult:
        config = await self._config.get_active()
        if not config:
            return FilterResult(passed=True)  # No config = pass all

        results = []

        for filter_name, filter_def in config.items():
            if not filter_def.get("enabled"):
                continue

            handler = self._get_handler(filter_name)
            result = await handler.evaluate(tender, filter_def["rules"])
            results.append(result)

            if not result.passed:
                return FilterResult(
                    passed=False,
                    failed_filter=filter_name,
                    reason=result.reason,
                )

        return FilterResult(passed=True)

    def _get_handler(self, name: str) -> FilterHandler:
        handlers = {
            "value_range": ValueRangeFilter(),
            "sector": SectorFilter(),
            "province": ProvinceFilter(),
            "entity_type": EntityTypeFilter(),
            "bee_level": BEEFilter(),
            "risk_exclusion": RiskExclusionFilter(),
        }
        return handlers[name]


class FilterHandler(ABC):
    @abstractmethod
    async def evaluate(self, tender: Tender, rules: list[dict]) -> FilterResult: ...

class ValueRangeFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict]) -> FilterResult:
        value = tender.estimated_value
        if value is None:
            return FilterResult(passed=True)  # No value = pass (can't filter)
        for rule in rules:
            if rule.get("min") is not None and value < rule["min"]:
                return FilterResult(passed=False, reason=f"Below minimum value {rule['min']}")
            if rule.get("max") is not None and value > rule["max"]:
                return FilterResult(passed=False, reason=f"Above maximum value {rule['max']}")
        return FilterResult(passed=True)

class SectorFilter(FilterHandler):
    async def evaluate(self, tender: Tender, rules: list[dict]) -> FilterResult:
        tender_cats = [tender.category_id]
        # also check buyer org industry codes if available
        for rule in rules:
            if rule["type"] == "include":
                if not any(c in rule["values"] for c in tender_cats):
                    return FilterResult(passed=False, reason="Sector not in include list")
            elif rule["type"] == "exclude":
                if any(c in rule["values"] for c in tender_cats):
                    return FilterResult(passed=False, reason="Sector in exclude list")
        return FilterResult(passed=True)

# ... similar implementations for ProvinceFilter, EntityTypeFilter,
# BEEFilter, RiskExclusionFilter
```

### 7.4 Config Hot-Reload

The filter config is cached in memory with a 60-second TTL. Changes to `filter_config` table are picked up within 1 minute without restart.

---

## 8. Contact-Sufficiency Classifier

### 8.1 Implementation

```python
# app/services/contact_sufficiency.py

@dataclass
class ContactSufficiencyResult:
    label: str  # "sufficient" | "role_based" | "none"
    icon: str   # "✓" | "⚠" | "✗"
    reason: str

def classify(org: Organization) -> ContactSufficiencyResult:
    """Classify contact sufficiency per §1.1 of implementation plan."""

    has_email = bool(org.contact_email)
    has_phone = bool(org.contact_phone)

    if not has_email and not has_phone:
        return ContactSufficiencyResult(
            label="none",
            icon="✗",
            reason="No contact on file",
        )

    if org.contact_email_is_role_based:
        return ContactSufficiencyResult(
            label="role_based",
            icon="⚠",
            reason="Role-based email only (e.g. info@, admin@)",
        )

    # Named email (not role-based)
    confidence = org.confidence_score or 0.0
    if confidence >= 0.7:
        return ContactSufficiencyResult(
            label="sufficient",
            icon="✓",
            reason=f"Named official — confidence {confidence:.0%}",
        )
    elif confidence >= 0.4:
        return ContactSufficiencyResult(
            label="role_based",
            icon="⚠",
            reason=f"Named contact, low confidence ({confidence:.0%})",
        )
    else:
        return ContactSufficiencyResult(
            label="role_based",
            icon="⚠",
            reason=f"Named contact, insufficient confidence ({confidence:.0%})",
        )
```

### 8.2 Integration in Workflow

Called during Step 3 (Award Detected) after `organizations` data is fetched. The result is stored on the `opportunities.contact_sufficiency` field and displayed on the kanban card.

---

## 9. Competitor Intelligence

### 9.1 Pre-Close (Speculative List)

At award detection time, before the tender close date:

```python
async def get_speculative_competitors(tender: Tender) -> list[Competitor]:
    """Derive likely bidders from historical award frequency."""
    # Query top companies for this (org, category) pair
    data = await companies_client.get_top(
        organization_id=tender.buyer_org_id,
        category_id=tender.category_id,
        limit=10,
    )
    # /companies/top returns: [{name, award_count, total_value}, ...]
    competitors = [
        Competitor(
            name=item["name"],
            inferred=True,
            reason=f"Top bidder for {tender.category_id} awards from this org",
        )
        for item in data["companies"]
    ]
    return competitors
```

### 9.2 At Close (Confirmed List)

At award detection time, after the close date:

```python
async def get_confirmed_competitors(tender: Tender) -> list[Competitor]:
    """Fetch actual bidder names from the tender."""
    bidders = await tenders_client.get_bidders(tender.api_id)
    competitors = []

    for bidder in bidders:
        # Try known-supplier short-circuit
        company = await find_company(bidder.name)
        competitors.append(
            Competitor(
                name=bidder.name,
                inferred=False,
                company_id=company.id if company else None,
                resolved=company is not None,
            )
        )

    return competitors
```

### 9.3 Known-Supplier Short-Circuit

```python
async def find_company(name: str) -> Company | None:
    """Resolve a bidder name to a company record."""
    # 1. Exact match
    company = await db.execute(
        "SELECT * FROM companies WHERE name = :name", {"name": name}
    )
    if company:
        return company

    # 2. Fuzzy match via /match endpoint
    match_result = await match_client.match(name)
    if match_result and match_result.confidence >= 0.8:
        company = await db.execute(
            "SELECT * FROM companies WHERE api_id = :id",
            {"id": match_result.company_id},
        )
        if company:
            return company

    # 3. Queue for manual lookup
    await db.execute(
        "INSERT INTO manual_lookup_queue (company_name, source, created_at) "
        "VALUES (:name, 'bidder', now())",
        {"name": name},
    )
    return None
```

---

## 10. Kanban Dashboard

### 10.1 API Endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/opportunities` | List opportunities (filterable by stage, assignee, date range) |
| `GET` | `/api/opportunities/{id}` | Opportunity detail with all panels |
| `PATCH` | `/api/opportunities/{id}/stage` | Move card to new stage (with version check) |
| `PATCH` | `/api/opportunities/{id}/assign` | Assign opportunity to user |
| `GET` | `/api/radar/awards` | Rolling 7-day pre-filter award feed |
| `GET` | `/api/radar/past-due-count` | Past-Due Queue counter |
| `GET` | `/api/watchlist` | Watching board items |
| `GET` | `/api/watchlist/{id}` | Watchlist item detail with countdown |
| `GET` | `/api/dashboard/stats` | Aggregate stats (by stage, by day) |

### 10.2 WebSocket Events

| Event | Direction | Payload |
|---|---|---|
| `opportunity:stage_changed` | Server → Client | `{ id, new_stage, old_stage, timestamp }` |
| `opportunity:created` | Server → Client | `{ id, company, value }` |
| `radar:new_award` | Server → Client | `{ tender_id, supplier, value }` |
| `watchlist:past_due` | Server → Client | `{ tender_id, title, days_overdue }` |

### 10.3 React Component Tree

```
<App>
  <DashboardLayout>
    <Sidebar>
      <AwardRadarPanel />        ← Live Award Radar
      <PastDueCounter />         ← Past-Due Queue count
    </Sidebar>
    <MainContent>
      <Tabs>
        <Tab label="Pipeline">
          <KanbanBoard>
            <KanbanColumn stage="new">
              <OpportunityCard />  ← Repeated
            </KanbanColumn>
            <KanbanColumn stage="assigned">
              <OpportunityCard />
            </KanbanColumn>
            <!-- ... more columns -->
          </KanbanBoard>
        </Tab>
        <Tab label="Watching">
          <WatchingBoard>
            <WatchingCard />     ← Repeated
          </WatchingBoard>
        </Tab>
      </Tabs>
    </MainContent>
  </DashboardLayout>
  <Modal>
    <CardExpansionPanel>
      <AwardDetailTab />
      <CompanyIntelTab />
      <OrgContactTab />
      <CompetitorListTab />
    </CardExpansionPanel>
  </Modal>
</App>
```

### 10.4 Opportunity Card

```
┌──────────────────────────────────────┐
│ [✓] [🟢]  R1.2M   GP  Construction  │
│                                      │
│  Acme Construction (Pty) Ltd         │
│  Dept of Public Works                │
│                                      │
│  BEE: Level 1  |  Award: 12d ago    │
│  Assigned: John D                    │
└──────────────────────────────────────┘
  ▲           ▲           ▲           ▲
  │           │           │           │
  Contact     Risk        Value       Province /
  Suff.       Flag        + badge     Category
```

### 10.5 Card Expansion Panels

**Award Detail:**
- Tender title and reference
- Award value, date
- Awarding organization
- Tender category and province
- Closing date → award date timeline

**Company Intelligence:**
- Company name, registration number
- BEE level (with verification badge)
- CIPC forensic risk score (with color bar)
- Restricted supplier indicator
- Historical award count and total value (12mo)
- Recent awards list (5 most recent)

**Organization Contact:**
- Buyer organization name and type
- Contact email (with sufficiency indicator)
- Contact phone
- Website
- Confidence score

**Competitor List:**
- Section 1: **Confirmed bidders** (at close) — labeled as confirmed
- Section 2: **Likely competitors** (pre-close) — labeled as inferred
- Each entry: name, resolved/unknown badge

### 10.6 Watching Board Card

```
┌──────────────────────────────────────┐
│  R2.5M   Construction   GP           │
│                                      │
│  Upgrade of National Road N2 Section │
│  SANRAL                              │
│                                      │
│  Expected award: in 12 days          │
│  ████████░░░░░░░░░░ 40%              │
│  Status: On Track                    │
│  Closing: 2026-07-15                 │
└──────────────────────────────────────┘
```

### 10.7 Opportunity Audit Log

Every stage transition is logged:

```sql
CREATE TABLE opportunity_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    opportunity_id UUID NOT NULL REFERENCES opportunities(id),
    from_stage VARCHAR(32),
    to_stage VARCHAR(32) NOT NULL,
    changed_by VARCHAR(128) NOT NULL,
    changed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_audit_opp ON opportunity_audit(opportunity_id);
CREATE INDEX idx_audit_changed_at ON opportunity_audit(changed_at);
```

---

## 11. Email Alerting Service

### 11.1 Architecture

```
Trigger Event → Queue (Redis list / ARQ) → Email Worker → SMTP / API → Recipient
```

Using ARQ (async Redis queue) for delivery. Failed sends are retried twice (5min, 30min), then logged as failed.

### 11.2 Email Templates

All templates use plain text (no HTML) with the following structure:

**Template: New Qualified Tender**
```
Subject: [Oricred] New Opportunity: {company_name} — {award_value}

Hi {assignee},

A new qualified opportunity has been created:

  Company:    {company_name}
  Award:      R{amount:,.0f}
  Buyer:      {buyer_org}
  Province:   {province}
  Risk:       {risk_flag}
  Contact:    {contact_sufficiency_icon} {contact_sufficiency_label}

View in dashboard: {dashboard_url}

Action: Review and assign within 24 hours.
```

**Template: Award Detected**
```
Subject: [Oricred] Award Detected: {company_name} — {tender_title}

Hi {assignee},

An award has been detected for a tracked tender:

  Tender:     {tender_title}
  Supplier:   {supplier_name}
  Amount:     R{amount:,.0f}
  Award date: {award_date}

View opportunity: {dashboard_url}
```

**Template: Past-Due Alert**
```
Subject: [Oricred] Past-Due: {tender_title} — No award found

Hi {team},

The following tender has passed its expected award window with no award found:

  Tender:     {tender_title}
  Buyer:      {buyer_org}
  Category:   {category}
  Window:     {window_start} → {window_end}
  Days overdue: {days_overdue}

View past-due queue: {dashboard_url}
```

**Template: API Failure**
```
Subject: [Oricred ALERT] API Integration Failure — {endpoint}

The Tenders-SA API integration has encountered a persistent failure:

  Endpoint:   {endpoint}
  Error:      {error}
  Attempts:   {attempts}
  Time:       {failed_at}

Action: Check API key and endpoint availability immediately.

Admin dashboard: {admin_url}
```

### 11.3 Configuration

| Setting | Environment Variable | Default |
|---|---|---|
| SMTP host | `SMTP_HOST` | `smtp.sendgrid.net` |
| SMTP port | `SMTP_PORT` | `587` |
| SMTP username | `SMTP_USER` | `apikey` |
| SMTP password | `SMTP_PASSWORD` | — |
| From address | `EMAIL_FROM` | `noreply@oricred.com` |
| From name | `EMAIL_FROM_NAME` | `Oricred Platform` |

### 11.4 Rate Limiting

- Maximum 20 emails per minute per recipient
- Maximum 5 identical alerts per tender per 24 hours

---

## 12. Scheduler & Job Definitions

### 12.1 Job Registry

| Job Name | Cron Expression | Description | Retry |
|---|---|---|---|
| `discover_tenders` | `*/15 * * * *` | Poll `/tenders/new` | 3x, 1min apart |
| `check_awards` | `0 * * * *` | Poll awards for watching tenders inside window | 2x |
| `check_past_due` | `0 * * * *` | Poll awards for past-due tenders (hourly) | 2x |
| `refresh_timing_model` | `0 2 * * 0` | Recompute award-timing model | 1x |
| `refresh_reference_data` | `0 5 * * *` | Refresh categories, provinces cache | 2x |
| `cleanup_expired` | `0 6 * * *` | Close expired watching items (>90d past closing) | 2x |
| `alert_threshold_check` | `0 8 * * *` | Check past-due queue threshold, alert if exceeded | 1x |

### 12.2 Job Implementation Pattern

```python
# app/jobs/registry.py

@dataclass
class JobDefinition:
    name: str
    cron: str
    handler: Callable
    max_retries: int = 3
    retry_delay_seconds: int = 60
    timeout_seconds: int = 300

JOB_REGISTRY = [
    JobDefinition(
        name="discover_tenders",
        cron="*/15 * * * *",
        handler=discover_new_tenders,
        timeout_seconds=600,
    ),
    JobDefinition(
        name="check_awards",
        cron="0 * * * *",
        handler=check_awards_for_watching,
    ),
    # ...
]

async def job_wrapper(job_def: JobDefinition):
    """Wrapper that handles logging, errors, and job tracking."""
    run = JobRun(job_name=job_def.name, started_at=datetime.utcnow())
    db.add(run)
    await db.flush()

    try:
        result = await asyncio.wait_for(
            job_def.handler(),
            timeout=job_def.timeout_seconds,
        )
        run.status = "success"
        run.finished_at = datetime.utcnow()
    except Exception as e:
        run.status = "failed"
        run.error = str(e)
        run.finished_at = datetime.utcnow()
        logger.exception(f"Job {job_def.name} failed: {e}")
        # Retry logic if applicable
    finally:
        await db.commit()
```

---

## 13. Security Model

### 13.1 Authentication

| Access Point | Method | Detail |
|---|---|---|
| Web dashboard | Session cookie | Username/password + session token (httpOnly, Secure, SameSite=Strict) |
| API endpoints | Bearer token | JWT with 24h expiry, refresh token flow |
| Scheduler internal | None (localhost only) | Scheduler binds to 127.0.0.1 only |

### 13.2 Authorization

Simple role-based access:

| Role | Permissions |
|---|---|
| `admin` | All access, including filter config editing, user management |
| `manager` | Full kanban access, assignment, opportunity editing |
| `operator` | View and update own opportunities, view dashboards |
| `viewer` | Read-only dashboard access |

### 13.3 API Key Storage

- `TSA_API_KEY` stored as environment variable (not in database).
- Rotated via deploy pipeline: update env var, restart service.
- All outbound API calls use HTTPS with TLS 1.2+.

### 13.4 Database Security

- Connection strings via environment variables (not in code).
- Application database user has only DML permissions (SELECT, INSERT, UPDATE, DELETE).
- Migrations run with a separate admin user.
- All sensitive columns (raw_payload may contain keys if API changes) access-controlled at application level.

---

## 14. Deployment Architecture

### 14.1 Container Layout

```
docker-compose.yml
├── app                  # FastAPI backend + web frontend (served via same process or Nginx)
│   ├── Dockerfile
│   └── .env
├── scheduler            # APScheduler process (separate container)
│   └── Dockerfile
├── redis
│   └── redis.conf
└── postgres
    └── init.sql
```

### 14.2 CI/CD Pipeline

```
Git push → GitHub Actions:
  1. Lint (ruff, mypy, ESLint, Prettier)
  2. Test (pytest, vitest)
  3. Build Docker images
  4. Push to container registry
  5. Deploy to staging (single-host docker-compose pull && up)
  6. Smoke tests (API health, dashboard load)
  7. Deploy to production (zero-downtime: rolling update or blue/green)
```

### 14.3 Infrastructure Requirements

| Resource | Dev | Production |
|---|---|---|
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8+ GB |
| Disk | 20 GB SSD | 50+ GB SSD |
| PostgreSQL | 12 (Docker) | 16 (managed, e.g. RDS) |
| Redis | 6 (Docker) | 7 (managed, e.g. ElastiCache) |

---

## 15. Testing Strategy

### 15.1 Unit Tests

| Module | Framework | Coverage Target |
|---|---|---|
| Filter engine | pytest | 100% of handler classes |
| Contact-sufficiency classifier | pytest | 100% of classification branches |
| Award-timing model logic | pytest | 100% of edge cases (§6.4) |
| Email template rendering | pytest | All template variables |
| API client retry logic | pytest + respx mock | All retry scenarios |

### 15.2 Integration Tests

| Test | Approach |
|---|---|
| API client → Tenders-SA | Test against sandbox/staging API (if available) or recorded responses (VCR.py) |
| Database operations | Test against test PostgreSQL (spawned in Docker) |
| Full pipeline (discover → qualify → watch → award) | End-to-end with mock API responses and real database |
| Kanban stage transitions | Test API endpoints with real database |

### 15.3 End-to-End Tests

| Tool | Scope |
|---|---|
| Playwright | Critical user paths: login, view pipeline, move card, view radar |

### 15.4 Mock Data

A seed SQL file with:
- 3 buyer organizations (national, provincial, SOE)
- 4 categories
- 10 tenders (various stages of qualification pass/fail)
- 5 awards (various org/category combinations for model training)
- 8 companies
- 3 opportunities in different kanban stages

---

## 16. Monitoring & Observability

### 16.1 Key Metrics

| Metric | Where | Alert Threshold |
|---|---|---|
| Tenders discovered per hour | Dashboard / logs | < 1 for >2h (API may be down) |
| Qualification pass rate | Dashboard | > 80% or < 10% (config may be too loose/tight) |
| Award poll success rate | Dashboard | < 95% over 1h |
| Past-due queue count | Dashboard | > 10 (check Phase 1B trigger) |
| API response times | Logs / APM | p95 > 5s |
| Job failure rate | Dashboard | Any failure in last 24h |
| Email delivery success | Dashboard | < 98% over 1h |

### 16.2 Logging

- Structured JSON logs (all services)
- Log levels: DEBUG (dev), INFO (prod), WARNING (rate limits), ERROR (failures)
- Log shipping: stdout → Docker collector → log aggregation (e.g. Grafana Loki or Axiom)

### 16.3 Health Check Endpoint

```
GET /health → 200 { "status": "ok", "db": "connected", "redis": "connected", "last_poll": "2026-06-26T12:00:00Z" }
```

Used by Docker health checks and load balancer.

---

## 17. Deliverables

1. **TSA API Client Module** — `app/clients/` with base client, all endpoint clients, caching, retry, rate-limit handling
2. **Database Schema** — Alembic migrations for all 11 tables with indexes, FKs, constraints
3. **Award-Timing Model Service** — Weekly batch computation, category-global fallback, prediction endpoint
4. **Qualification Filter Engine** — Config-driven pipeline with 6 filter handlers, hot-reload, seed config
5. **Contact-Sufficiency Classifier** — Classification function, integration in award-detection workflow
6. **Competitor Intelligence Module** — Pre-close speculative list, confirmed bidders at close, known-supplier short-circuit
7. **Kanban Web Dashboard** — React app with pipeline, watching board, award radar, card expansion panels, WebSocket live updates
8. **REST API** — FastAPI app with all endpoints in §10.1, OpenAPI docs, JWT auth
9. **Email Alerting Service** — ARQ worker with 4 templates, rate limiting, retry logic
10. **Scheduler** — APScheduler-based job runner with 7 job definitions, retry, logging
11. **Opportunity Audit Log** — Stage transition tracking with timestamps and user attribution
12. **Integration Test Suite** — pytest tests for all services with mocked API and real database
13. **E2E Test Suite** — Playwright tests for critical user paths
14. **Docker Compose Setup** — Multi-container deployment for dev and prod
15. **Deployment Runbook** — Step-by-step deploy instructions, rollback procedure, incident response

---

## 18. Acceptance Criteria

### 18.1 Functional

- [ ] **Tender discovery:** New tenders appear in the database within 15 minutes of publication on Tenders-SA
- [ ] **Qualification filter:** Tenders are correctly accepted or rejected per the active config; config changes take effect within 60 seconds
- [ ] **Award timing:** Expected award windows are assigned to all tracked tenders within 1 minute of discovery; cold-start fallback works
- [ ] **Award detection:** Awards are detected within 1 hour of publication on Tenders-SA for tenders inside their expected window
- [ ] **Past-due detection:** Tenders past their expected window with no award are moved to the past-due queue within 1 hour
- [ ] **Contact sufficiency:** Every opportunity has a correctly classified contact-sufficiency indicator (✓/⚠/✗)
- [ ] **Known-supplier short-circuit:** >80% of bidder names in confirmed-competitor lists are resolved to company records without manual lookup
- [ ] **Kanban pipeline:** Cards can be dragged between columns; stage changes are persisted and logged
- [ ] **Watching board:** Shows all tracked pre-award tenders with countdown; statuses update correctly (On Track → Approaching Window → Past Due)
- [ ] **Award radar:** Shows rolling 7-day pre-filter award feed with past-due counter
- [ ] **Card expansion:** All 4 panels (award detail, company intel, org contact, competitor list) load within 2 seconds
- [ ] **Email alerts:** All 4 alert templates are sent on their trigger events; delivery rate >99%
- [ ] **Assignment:** Opportunities can be assigned to users; assignment persists across page reloads

### 18.2 Non-Functional

- [ ] **Dashboard load time:** <2s cold, <500ms subsequent (cached)
- [ ] **API endpoint response:** p95 <500ms for read endpoints, <1s for write endpoints
- [ ] **Concurrent users:** Dashboard handles 20 concurrent users without degradation
- [ ] **API rate limits:** System never exceeds Tenders-SA rate limits (429s are handled, not triggered ourselves)
- [ ] **Data integrity:** No duplicate tenders, awards, or opportunities in the database
- [ ] **Uptime:** 99.5% excluding scheduled maintenance (15 min/week window)

### 18.3 Testing

- [ ] Unit test coverage >85% on core business logic (filter engine, classifier, timing model)
- [ ] Integration tests cover all API client retry scenarios
- [ ] E2E tests cover: login, pipeline view, card drag, card expansion open/close, watching board
- [ ] All tests pass in CI before deployment

---

## 19. Deferred Scope

| Item | Rationale | Target |
|---|---|---|
| SOE internal-portal checks | Triggered by past-due queue data | Phase 1B |
| OCPO Gazette PDF parsing | Triggered by past-due queue data | Phase 1B |
| Municipalities expanded scope | Phase 2 scope | Phase 2 |
| Buyer-relationship analytics / CRM | Incremental on Phase 1 data | Phase 2 |
| Predictive procurement intelligence | Requires 12+ months accumulated data | Phase 3 |
