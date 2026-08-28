# Remediation 07 — Engineering Hygiene

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** L1, L2, L3, L8, L10 (hygiene)
**Note:** §1 is sequenced with the incident response in overview §3, not with the rest of this spec

---

## Objective

Install the controls that would have caught the critical findings, and close the gap between
what the documentation claims and what the code does.

This spec exists because of one fact: **`ruff check` already detects the platform's most
serious defect.** The rule is configured in `pyproject.toml`, the tool is installed in the
virtualenv, and nothing runs it. C1 was one two-hour CI task away from never happening.

---

## 1. Enforce lint, types, and tests in CI (L1)

### 1.1 Current state

`pyproject.toml` declares both tools:

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

[tool.mypy]
strict = true
disallow_untyped_defs = true
```

Neither has ever been enforced. Current output:

| Rule | Count | Meaning |
|------|-------|---------|
| `E501` | 245 | Line longer than 100 characters |
| `I001` | 46 | Import block unsorted |
| `F401` | 39 | Imported but unused |
| `E402` | 30 | Module-level import not at top of file |
| **`F821`** | **3** | **Undefined name — this is C1** |
| `E712` | 3 | Comparison to `True` |
| `F841` | 2 | Local assigned but never used |
| `W292` | 1 | No newline at end of file |
| | **369** | |

There is no `.github/workflows/` directory. `mypy` has never been run.

### 1.2 Change — the gate, in stages

Turning on all 369 at once means either a 300-file diff mixed into the remediation work, or a
gate everyone learns to ignore. Split it.

**Stage 1 — the rules that catch bugs. Ship with the incident response.**

```toml
[tool.ruff.lint]
select = ["E", "F", "I", "N", "W"]

# Staged adoption — see docs/specifications/remediation-07-engineering-hygiene.md
# Stage 2 removes E501 and E402; stage 3 removes the rest.
ignore = ["E501", "E402"]
```

`F401`, `I001`, `E712`, `W292` are all safely auto-fixable:

```bash
ruff check app tests --select F401,I001,E712,W292 --fix
```

`F821` and `F841` are fixed by hand in specs 01 §1 and 04 §3.3. After that, stage 1 is green.

**Stage 2 — formatting.** `E402` is 30 real cases where imports sit below module-level code
(`discovery.py:21`, `award_check.py:23`); move them. `E501` is mechanical — adopt
`ruff format` with `line-length = 100` in a single formatting-only commit, tagged so `git blame`
can skip it via `.git-blame-ignore-revs`.

**Stage 3 — types.** `mypy --strict` on a codebase this size will produce hundreds of errors.
Start with the modules where a type error would be expensive and expand outward:

```toml
[[tool.mypy.overrides]]
module = ["app.clients.*", "app.jobs.*", "app.services.contact_enrichment", "app.workflow"]
strict = true

[[tool.mypy.overrides]]
module = ["app.api.*", "app.models.*", "app.services.*"]
ignore_errors = true      # removed module by module; each removal is its own PR
```

### 1.3 Change — the workflow

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  backend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: backend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check app tests
      - run: mypy app
      - run: pytest -q

  frontend:
    runs-on: ubuntu-latest
    defaults: { run: { working-directory: frontend } }
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: "20", cache: npm, cache-dependency-path: frontend/package-lock.json }
      - run: npm ci
      - run: npm run build          # tsc -b && vite build
```

Add a `[project.optional-dependencies] dev = ["ruff", "mypy", "pytest", "pytest-asyncio"]`
group so CI and local development install the same versions. `pytest` and `ruff` are currently
in the virtualenv but not in `pyproject.toml` dependencies at all.

### 1.4 Change — catch it locally too

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.16.3
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
```

Optional for contributors, but it makes the CI gate a formality rather than a surprise.

---

## 2. Correct the documentation drift (L2)

### 2.1 Current state

AGENTS.md — the file that tells every future contributor and agent how this system works —
describes an award-date resolver that no longer exists.

It documents five resolution steps including "year correction using reference dates in
priority order: award `publication_date.year` → `tender.published_at.year` →
`tender.closing_date.year` → `discovered_at.year` → `discovered_at.year - 1`", a pub-date
validation step, and a `_parse_lenient()` helper described as "parses without MAX_VALID_YEAR
guard for year-correction recovery".

The actual `_resolve_award_date` (`award_check.py:82-102`) is three branches: parse the raw
date, fall back to `source_created_at`, fall back to `discovered_at`. There is no year
correction, no pub-date validation, and `_parse_lenient` does not exist anywhere in the
codebase. `fix_corrupted_award_dates`'s own docstring still promises the removed behaviour.

This is worse than no documentation: it sent this review looking for functions that were not
there, and it will send the next contributor to reason about behaviour the system does not
have.

### 2.2 Change

Rewrite the "Award Date Domain Rules" section against the code as it will be after spec 03 §1.
The business rule at the top of that section — that `award_date` is the core business value
and the resolver never returns NULL — is still true and should stay. What changes is the
mechanism.

```markdown
**Resolution logic** (`_resolve_award_date` in `award_check.py`):

1. **Source date** — if the raw date parses and is not after `discovered_at`, use it.
2. **Source created_at** — the TSA DB row's creation timestamp, if it is not in the future.
3. **Discovery date** — when we first saw the record.

The resolver returns `ResolvedAwardDate(value, from_source)`. `from_source` is true only for
branches 1 and 2. Only source-backed dates advance the ingestion cursor; see
`docs/specifications/remediation-03-ingestion-correctness.md` section 1 for why.

**Removed in 2026-08:** year correction from reference dates, pub-date validation, and
`_parse_lenient()`. Awards with corrupt years now fall through to branch 2 or 3 and are
marked `date_source != "source"`, which is what the nightly repair job scans.
```

Also correct in the same pass:

- **"Admin: 7 tabs"** — the Admin page has three (`AdminPage.tsx:7-11`: Credentials, Jobs,
  Users). Commit `a515055` removed the rest; AGENTS.md still lists Filters, Sources,
  Notifications, and Scoring in two places.
- **"CORS: Wildcard in dev, locked down in prod"** — not true until spec 02 §3 lands; update
  with that change.
- **"eliminated N+1"** on `award_check.py` — that claim describes the batch fetch of tenders
  and companies, not the per-award loop, which still issues six queries per row. Reword to say
  what was actually batched.
- **"53 tests"** — there are 121.
- **Phase 2 "Competitor intel (speculative + confirmed bidders)"** listed as complete — see §3.

### 2.3 Add a standing rule

At the top of AGENTS.md, under the existing "code is the source of truth" note:

```markdown
> When you change behaviour that a section of this file describes, update that section in the
> same commit. A stale description here is more expensive than a missing one — it makes future
> readers reason about a system that does not exist.
```

---

## 3. Remove dead code and dead configuration (L3)

### 3.1 Dead code

| Symbol | Location | Referenced by |
|--------|----------|---------------|
| `CompetitorIntelService` | `services/competitor_intel.py` | `services/__init__.py` re-export and its own test only |
| `query_tenders_from_config` | `clients/tsa_db.py:444` | nothing |
| `count_tenders` | `clients/tsa_db.py:490` | nothing |
| `search_items` | `services/crm/monday.py:103` | its own test only |

`CompetitorIntelService` is the notable one, because AGENTS.md lists "Competitor intel
(speculative + confirmed bidders)" under Phase 1 as completed. The feature that actually
populates `related_bidders` is eight lines inside `award_check.py` — the ones spec 03 §2 fixes.
The service class was never wired in.

It also carries a latent resource issue: `__init__` constructs `TSADatabase()` when none is
passed, creating a connection pool with no `close()` method on the class to dispose it.

### 3.2 Change

**Delete** `query_tenders_from_config`, `count_tenders`, and `search_items`. None has a caller,
and `count_tenders` and `query_tenders_from_config` both carry the L4 precedence bug that spec
03 §6 fixes — fixing dead code is wasted effort, but leaving a landmine is worse, so spec 03
§6 fixes `_build_tender_where` itself (which is live) and this spec removes the dead callers.

**Decide on `CompetitorIntelService`.** Two options, and the choice is a product one:

- *Wire it in.* `get_speculative_competitors` is the only source of "companies that usually win
  this buyer's work" — genuinely useful for the funding conversation. It needs a `close()`
  method, a category filter that is currently accepted and ignored (`competitor_intel.py:27-35`
  takes `category_id` and never uses it in the query), and an endpoint.
- *Delete it,* and correct the Phase 1 claim in AGENTS.md.

Recommend deleting now and re-specifying if the feature is wanted, because the current code
would need most of a rewrite to be correct anyway.

**`pull_crm_activity` is live but inert.** It is not dead code — the scheduled `sync_crm` job
calls it hourly (`jobs/crm_sync.py:13`) — but it fetches Monday activity and then throws it
away:

```python
# services/crm/sync.py:130-133
for activity in activities:
    if activity.event in ("update_column_value", "create_item"):
        logger.debug("crm_activity_event", event=activity.event, data=activity.data)
```

So an enabled hourly job makes a real API call and produces nothing but a debug line. Either
disable the job in `DEFAULT_JOBS` until two-way sync is specified (spec 05 §8), or keep it and
say so in the docstring — but do not leave a scheduled job that looks like it is syncing when
it is not:

```python
async def pull_crm_activity(since: datetime | None = None) -> None:
    """Fetch recent Monday.com activity.

    Currently logs and discards — inbound sync is not implemented. See
    remediation-05 section 8. The `sync_crm` job that calls this is disabled
    by default until it does something.
    """
```

### 3.3 Dead configuration

Two qualification filters ship default rules and do nothing:

```python
# services/qualification.py:89-96
class BEEFilter(FilterHandler):
    async def evaluate(self, tender, rules, db=None) -> FilterResult:
        return FilterResult(passed=True)


class RiskExclusionFilter(FilterHandler):
    async def evaluate(self, tender, rules, db=None) -> FilterResult:
        return FilterResult(passed=True)
```

`default_config()` supplies them with `{"min_level": 1, "max_level": 4, "min_points": 75}` and
`{"exclude_if_restricted": True, "max_forensic_score": 70.0}`. The Admin filter UI therefore
presents settings that have no effect, which is a trust problem: an operator who sets a B-BBEE
floor and sees unqualified tenders arrive will reasonably conclude the whole filter engine is
broken.

Either implement both or remove their entries from `default_config()`. Implementing
`RiskExclusionFilter` is cheap — `Company.restricted_supplier` and
`Company.cipc_forensic_risk_score` already exist and are already honoured in
`lead_scoring.compute_lead_priority:75-76`. `BEEFilter` has no tender-level B-BBEE data to act
on (it is an award attribute, not a tender one) and should be removed.

### 3.4 Frontend dead code

`services/api.ts` still exports `getFilterConfig`, `updateFilterConfig`, `getSources`,
`updateSources`, `getNotifications`, `updateNotifications`, `getScoring`, `updateScoring`
(lines 94-105) for the four Admin tabs removed in commit `a515055`. The backend endpoints stay
(spec 05 §3 makes the notifications config live again), but the unused client functions should
go until a UI needs them.

`AdminPage.tsx:1` imports `useCallback` and never uses it.

---

## 4. Make the job registry single-source (L8)

### 4.1 Current state

Two hand-maintained maps that must agree and do not:

```python
# jobs/scheduler.py:22-30 — what the scheduler runs
JOB_HANDLERS = {
    "discover_tenders", "check_awards", "refresh_timing_model", "sync_crm",
    "contact_enrichment", "historical_contacts", "fix_corrupted_award_dates",
}

# api/admin.py:175-183 — what the Admin "Run Now" button can trigger
handlers = {
    "discover_tenders", "check_awards", "refresh_timing_model", "sync_crm",
    "contact_enrichment", "historical_contacts", "backfill_tenders",
}
```

Verified divergence:

```
schedulable but NOT triggerable: {'fix_corrupted_award_dates'}
triggerable but NOT schedulable: {'backfill_tenders'}
```

So the nightly date-repair job cannot be run on demand when an operator notices bad dates, and
`backfill_tenders` appears in the API but not in `DEFAULT_JOBS`, so the Admin → Jobs list never
renders a row for it.

The two maps also differ in kind: the scheduler holds function references, the API holds
`"module:function"` strings resolved with `importlib` at request time — a needless indirection
that turns a typo into a runtime 500 instead of an import error at startup.

### 4.2 Change

One registry, in `jobs/scheduler.py`, holding everything both consumers need:

```python
@dataclass(frozen=True)
class JobDefinition:
    name: str
    label: str
    handler: JobHandler
    default_cron: str
    description: str
    schedulable: bool = True      # False for on-demand recovery jobs
    triggerable: bool = True


JOBS: dict[str, JobDefinition] = {
    j.name: j for j in (
        JobDefinition("discover_tenders", "Discover new tenders", discover_new_tenders,
                      "*/15 * * * *", "Poll Tenders-SA for new tenders"),
        JobDefinition("check_awards", "Ingest Tenders-SA awards", check_awards_for_watching,
                      "*/30 * * * *", "Ingest Tenders-SA awards incrementally"),
        JobDefinition("fix_corrupted_award_dates", "Fix corrupted award dates",
                      fix_corrupted_award_dates, "0 4 * * *",
                      "Repair awards with NULL, future, or synthesised dates"),
        JobDefinition("backfill_tenders", "Backfill stub tenders", backfill_stub_tenders,
                      "", "Re-fetch metadata for tenders created from awards",
                      schedulable=False),
        ...
    )
}
```

`DEFAULT_JOBS` in `admin_config.py` is derived rather than duplicated:

```python
DEFAULT_JOBS = {
    j.name: {"enabled": True, "cron": j.default_cron, "description": j.description}
    for j in JOBS.values() if j.schedulable
}
```

and the trigger endpoint looks up the registry directly, dropping `importlib`:

```python
@router.post("/jobs/{job_name}/trigger")
async def trigger_job(job_name: str, background_tasks: BackgroundTasks, ...):
    job = JOBS.get(job_name)
    if not job or not job.triggerable:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")
    background_tasks.add_task(run_job, job.name, job.handler)
    return {"status": "accepted", "job": job_name}
```

### 4.3 Test

```python
def test_every_schedulable_job_has_a_valid_cron():
    for job in JOBS.values():
        if job.schedulable:
            CronTrigger.from_crontab(job.default_cron)   # raises on a bad expression


def test_every_job_is_reachable_from_the_admin_trigger_endpoint():
    ...
```

The first test would also have caught a bad default cron, which currently only produces a
`logger.warning` at startup and silently drops the job (`scheduler.py:76-80`).

---

## 5. Add foreign keys and verify column widths (L10)

### 5.1 Current state — no referential integrity

Every relationship in the schema is an unconstrained string column:

| Column | References | Constraint |
|--------|-----------|------------|
| `opportunities.tender_id` | `tenders.id` | none |
| `opportunities.award_id` | `awards.id` | unique index only |
| `opportunities.company_id` | `companies.id` | index only |
| `opportunities.assigned_to` | `users.id` | none |
| `awards.tender_id` | `tenders.id` | index only |
| `contacts.company_id` | `companies.id` | index only |
| `watchlist_items.tender_id` | `tenders.id` | unique only |
| `past_due_queue.tender_id` | `tenders.id` | none |

`DELETE /admin/users/{id}` (`admin.py:257`) removes a user and leaves every
`opportunities.assigned_to` pointing at a row that no longer exists. `_opportunity_to_read`
returns that dangling ID as `assigned_to`, and the modal's assignee dropdown shows a blank.
`DELETE /contacts/{id}` has the same shape.

### 5.2 Change — add constraints where the semantics are clear

```python
tender_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("tenders.id", ondelete="RESTRICT"), nullable=True, index=True,
)
company_id: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("companies.id", ondelete="RESTRICT"), nullable=True, index=True,
)
assigned_to: Mapped[str | None] = mapped_column(
    String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
)
```

`RESTRICT` for the ingestion entities — a tender or company with dependent rows should not be
deletable by accident. `SET NULL` for `assigned_to`, which is exactly the intended behaviour
when a user leaves: the lead becomes unassigned rather than dangling.

`watchlist_items.tender_id` and `past_due_queue.tender_id` take `ondelete="CASCADE"` — they are
tracking state about a tender and are meaningless without it.

> **Deployment note.** Existing databases will have orphans. The migration must clean them
> first, in this order: null out dangling `assigned_to`, delete watchlist and past-due rows
> whose tender is missing, then report any remaining orphaned opportunities for manual review
> rather than deleting them. Ship the audit query before the constraint.

```sql
-- run before the migration, expect zero rows
SELECT 'opportunity->tender' AS ref, COUNT(*) FROM opportunities o
  LEFT JOIN tenders t ON t.id = o.tender_id WHERE o.tender_id IS NOT NULL AND t.id IS NULL
UNION ALL
SELECT 'opportunity->company', COUNT(*) FROM opportunities o
  LEFT JOIN companies c ON c.id = o.company_id WHERE o.company_id IS NOT NULL AND c.id IS NULL
UNION ALL
SELECT 'opportunity->user', COUNT(*) FROM opportunities o
  LEFT JOIN users u ON u.id = o.assigned_to WHERE o.assigned_to IS NOT NULL AND u.id IS NULL;
```

Also enable enforcement on SQLite, which ignores foreign keys unless asked:

```python
@event.listens_for(engine.sync_engine, "connect")
def _sqlite_fk_pragma(dbapi_connection, _):
    if engine.dialect.name == "sqlite":
        dbapi_connection.execute("PRAGMA foreign_keys=ON")
```

### 5.3 Verify — `Organization.id` width

```python
# models/organization.py
id: Mapped[str] = mapped_column(String(32), primary_key=True)
```

`Tender.buyer_org_id` and `Award.buyer_org_id` are `String(32)` to match. These hold
Tenders-SA `source_organizations.id` values. If those are 36-character UUIDs, PostgreSQL
raises `StringDataRightTruncation` on insert — while SQLite, which ignores `VARCHAR` lengths
entirely, accepts them silently. That is why the dev database and the test suite cannot
detect it.

This is unconfirmed. **Run before deciding:**

```sql
-- against the Tenders-SA read replica
SELECT MAX(LENGTH(id)) AS max_id_len, MIN(LENGTH(id)) AS min_id_len, COUNT(*)
FROM source_organizations;
```

If the answer exceeds 32, widen all three columns to `String(64)` in one migration.
`Company.api_id` is already `String(64)` and holds the equivalent identifier for companies,
which suggests 32 was simply a typo.

Separately, `discovery._process_scraper_tender:105` creates
`Organization(id=org_id, name=org_id)` where `org_id` is a *display name* such as
"City of Johannesburg" — mixing a name into a column otherwise holding TSA identifiers. Give
scraped organisations a namespaced synthetic ID (`municipal:joburg`) instead.

---

## 6. Cover the code where the defects were (test strategy)

### 6.1 Current state

121 tests pass. Their distribution:

| File | Tests | Covers |
|------|-------|--------|
| `test_p2b_api.py` | 40 | Awards/tenders browser endpoints |
| `test_tsa_db.py` | 22 | `_build_*_where` SQL generation |
| `test_lead_contact_import.py` | 14 | Import decisions |
| `test_contacts.py` | 10 | Contact CRUD |
| `test_funding_suitability.py` | 8 | Scoring |
| `test_award_check.py` | 7 | Date resolution |
| `test_buyer_relationship.py` | 6 | Relationship computation |
| `test_crm_adapter.py` | 6 | Monday adapter shape |
| `test_competitor_intel.py` | 2 | A service with no callers |

Every finding in this review lives in code these tests do not exercise: the ingest loop, the
discovery loop, the enrichment path, and the TSA client's contact methods. `test_tsa_db.py`
tests the filter builders thoroughly and never calls the query methods, which is precisely why
C1 survived.

### 6.2 Change — a stubbed TSA fixture

The single highest-value addition is a `TSADatabase` whose `_session_factory` returns
canned rows, so the jobs can be run end to end against SQLite with no external database:

```python
# backend/tests/conftest.py

class StubTSASession:
    """Records executed SQL and returns queued fixtures."""
    def __init__(self, responses: dict[str, list[dict]]): ...
    async def execute(self, statement, params=None): ...


@pytest.fixture
def tsa_stub() -> TSADatabase:
    db = TSADatabase.__new__(TSADatabase)       # bypass engine construction
    db._session_factory = ...
    return db
```

With that in place, the tests that would have caught this review's findings become
straightforward:

| Test | Catches |
|------|---------|
| Run `check_awards_for_watching` over a 3-award fixture, assert opportunities created | H2, M2 |
| Same, with one unparseable award date, assert the cursor | H1 |
| Run `enrich_all_contacts`, assert contacts written | C1, H3, M8 |
| Call each TSA query method, assert it returns rather than raises | C1 |
| Run `discover_new_tenders` over a multi-category fixture, assert one tender per row | M5 |
| Count queries during a 10-award and a 500-award run | M2 |

### 6.3 Change — a coverage floor, on the modules that matter

Rather than a global percentage, gate the modules where a silent failure is expensive:

```toml
[tool.coverage.report]
fail_under = 0        # global floor stays off

# enforced in CI per-module
# app/jobs/award_check.py       >= 70%
# app/jobs/discovery.py         >= 70%
# app/services/contact_enrichment.py >= 80%
# app/clients/tsa_db.py         >= 80%
# app/workflow.py               >= 95%
```

---

## 7. Files to change

| File | Change |
|------|--------|
| `.github/workflows/ci.yml` | **new** — §1.3 |
| `.pre-commit-config.yaml` | **new** — §1.4 |
| `backend/pyproject.toml` | §1.2 staged `ignore`, mypy overrides; §1.3 `dev` extra; §6.3 coverage config |
| `.git-blame-ignore-revs` | **new** — §1.2 stage 2 formatting commit |
| `AGENTS.md` | §2.2 — award-date rules, admin tabs, CORS, N+1 claim, test count, competitor intel; §2.3 standing rule |
| `backend/app/services/competitor_intel.py` | §3.2 — delete (recommended) |
| `backend/app/services/__init__.py` | §3.2 — drop the re-export |
| `backend/app/clients/tsa_db.py` | §3.2 — delete `query_tenders_from_config`, `count_tenders` |
| `backend/app/services/crm/monday.py` | §3.2 — delete `search_items` |
| `backend/app/services/crm/sync.py` | §3.2 — document `pull_crm_activity` as scaffolding |
| `backend/app/services/qualification.py` | §3.3 — implement `RiskExclusionFilter`, remove `BEEFilter` defaults |
| `frontend/src/services/api.ts` | §3.4 — remove client functions for the four removed admin tabs |
| `frontend/src/pages/AdminPage.tsx` | §3.4 — drop the unused `useCallback` import |
| `backend/app/jobs/scheduler.py` | §4.2 — `JobDefinition`, `JOBS` registry |
| `backend/app/services/admin_config.py` | §4.2 — derive `DEFAULT_JOBS` |
| `backend/app/api/admin.py` | §4.2 — trigger from the registry, drop `importlib` |
| `backend/app/models/*.py` | §5.2 — foreign keys |
| `backend/app/database.py` | §5.2 — SQLite `PRAGMA foreign_keys=ON`, orphan cleanup |
| `backend/app/jobs/discovery.py` | §5.3 — namespaced synthetic organisation IDs |
| `backend/tests/conftest.py` | §6.2 — `tsa_stub` fixture |

---

## 8. Acceptance criteria

- [ ] `ruff check app tests` exits zero with the stage-1 rule set, and runs on every push
- [ ] `npm run build` runs in CI and fails the build on a type error
- [ ] `pytest` runs in CI and fails the build on a test failure
- [ ] A PR reintroducing an undefined name fails CI before review
- [ ] AGENTS.md's award-date section describes the code that exists, and names what was removed
- [ ] AGENTS.md's admin, CORS, N+1, and test-count claims match the code
- [ ] No module in `app/` is imported only by `services/__init__.py` and its own test
- [ ] Every filter shown in the Admin filter UI has an effect, or has been removed from the defaults
- [ ] `fix_corrupted_award_dates` can be triggered from Admin → Jobs
- [ ] `backfill_tenders` either appears in the jobs list or is removed from the trigger map
- [ ] The scheduler and Admin trigger endpoint read from one registry
- [ ] A job with an invalid default cron fails a test rather than being silently skipped at startup
- [ ] The orphan audit query returns zero rows before the foreign-key migration runs
- [ ] Deleting a user sets `assigned_to` to NULL on their leads rather than leaving a dangling ID
- [ ] `MAX(LENGTH(id))` on `source_organizations` has been measured and the column widths match it
- [ ] `check_awards_for_watching`, `discover_new_tenders`, and `enrich_all_contacts` each have an end-to-end test against `tsa_stub`

---

## 9. Deferred scope

- `mypy --strict` across `app/api` and `app/models`. Stage 3 in §1.2 expands module by module.
- Replacing `Base.metadata.create_all` plus hand-written `ALTER TABLE` helpers with real
  Alembic migrations. The `_ensure_*_columns` pattern in `database.py` works but is now
  carrying five distinct migrations and will not survive a sixth cleanly. This deserves its
  own spec before the foreign-key work in §5 goes to production.
- Frontend tests. There are none; `tsc` is the only gate. A small Vitest suite around the
  workflow transition logic and the optimistic drag-and-drop reducer would be the place to
  start.
- Load testing the ingest job against a production-sized award set.
