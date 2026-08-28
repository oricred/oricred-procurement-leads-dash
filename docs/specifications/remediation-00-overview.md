# Remediation Phase — Overview

**Date:** 2026-08-27 (status updated 2026-08-28)
**Status:** 32 of 34 findings implemented
**Source:** Full application review at commit `9de20fd`
**Depends on:** Phase 2b (current shipped state)

> **Implementation status.** Specs 01, 02, 03, 05 and 06 are complete. Spec 04
> is complete except for two per-company aggregate queries in the award ingest
> loop and per-column fetching on the pipeline board. Spec 07 is complete except
> §5 (foreign keys and column widths), which is blocked on production data.
>
> Delivered across two branches: `remediation/incident-response` (the critical
> and high-severity work) and `remediation/ingestion-and-performance`.

---

## Objective

Close the 34 defects identified in the application review. The work is split into seven
specifications by workstream rather than by severity, because the fixes cluster by file and by
test surface — restoring the enrichment path touches one set of modules, hardening production
defaults touches another, and mixing them produces changesets nobody can review.

Each spec is independently implementable and independently shippable. The sequencing in §3
orders them by damage prevented per hour of work, which is not the same as severity order.

---

## 1. Scope

### 1.1 In scope

All 34 findings from the review, grouped as follows.

| Spec | Title | Findings covered | Status |
|------|-------|------------------|--------|
| [01](remediation-01-contact-enrichment-restoration.md) | Contact Enrichment Restoration | C1, H3, M8, M12 | done |
| [02](remediation-02-security-hardening.md) | Security Hardening | C3, C4, C5, H7, H8, M11 | done |
| [03](remediation-03-ingestion-correctness.md) | Ingestion Correctness | H1, H2, M4, M5, M10, L4 | done |
| [04](remediation-04-query-performance.md) | Query Performance | M1, M2, M3, M6, M7 | done, two follow-ups noted |
| [05](remediation-05-integrations-and-delivery.md) | Integrations & Delivery | H6, L5, L6, L7, L9 | done |
| [06](remediation-06-import-and-export.md) | Import & Export Robustness | H4, H5, M9 | done |
| [07](remediation-07-engineering-hygiene.md) | Engineering Hygiene | L1, L2, L3, L8, L10 | L10 outstanding |

### 1.2 Out of scope

- **C2 — Tenders-SA credential rotation.** The committed connection string in
  `backend/app/config.py:12` is an operational incident, not a code change. Rotating the
  password with Tenders-SA and purging it from history is handled outside this phase.
  Spec 02 §2 still removes the hardcoded default and adds the startup guard that prevents a
  recurrence, and assumes the rotation has already happened.
- Phase 3 predictive intelligence. Unchanged and still deferred.
- Any new user-facing capability. This phase adds nothing that was not already promised.

---

## 2. Finding index

Severity labels match the review. `L` findings are the hygiene items, numbered here so they
can be tracked.

| ID | Sev | Finding | Spec |
|----|-----|---------|------|
| C1 | Critical | `query_directors` / `query_key_personnel` / `query_source_directors` raise `NameError` on every call | 01 |
| C2 | Critical | Production Tenders-SA credentials committed to the repository | — |
| C3 | Critical | Saving the Admin credentials form overwrites every secret with its own mask | 02 |
| C4 | Critical | `debug` defaults to on; debug mode seeds an `admin123` superuser | 02 |
| C5 | Critical | JWT signing secret has a published default and no startup guard | 02 |
| H1 | High | Award-ingest cursor can jump to today and silently skip awards | 03 |
| H2 | High | `related_bidders` lookup keys never match, so competitor intel is always empty | 03 |
| H3 | High | `email=""` plus a full unique constraint allows only one phone-only contact per company | 01 |
| H4 | High | Contact import returns HTTP 500 when two companies share a name | 06 |
| H5 | High | Upload size limit is enforced after the whole file is in memory | 06 |
| H6 | High | Monday.com integration cannot succeed with its own default board ID | 05 |
| H7 | High | Wildcard CORS combined with credentials | 02 |
| H8 | High | Service worker caches authenticated API responses and never clears them | 02 |
| M1 | Medium | Tenders browser issues three extra queries per row | 04 |
| M2 | Medium | Award ingest runs ~7 queries per award, one of them to the external database | 04 |
| M3 | Medium | Nightly date-repair job loads the entire awards table into memory | 04 |
| M4 | Medium | Offset pagination without a unique tiebreak skips and duplicates rows | 03 |
| M5 | Medium | Tender queries return duplicate rows from the category join | 03 |
| M6 | Medium | Unbounded list endpoints polled every 15 seconds | 04 |
| M7 | Medium | Historical contacts applies its main filter after the row limit | 04 |
| M8 | Medium | Substring company matching can attach the wrong people to a company | 01 |
| M9 | Medium | CSV exports are vulnerable to spreadsheet formula injection | 06 |
| M10 | Medium | Sector filter rejects uncategorised tenders while sibling filters pass them | 03 |
| M11 | Medium | Seven admin read endpoints are missing the admin role check | 02 |
| M12 | Medium | Nothing on screen updates after "Find contact" succeeds | 01 |
| L1 | Hygiene | Lint and type checking configured but never enforced (369 ruff errors) | 07 |
| L2 | Hygiene | AGENTS.md describes an award-date resolver that no longer exists | 07 |
| L3 | Hygiene | Dead code presented as shipped features | 07 |
| L4 | Hygiene | Operator-precedence bug in the `_build_tender_where` `since` clause | 03 |
| L5 | Hygiene | Notification recipients config is never read | 05 |
| L6 | Hygiene | Email delivery opens a new SMTP connection per message inside the ingest loop | 05 |
| L7 | Hygiene | CRM push makes one HTTP request per column, synchronously in the request path | 05 |
| L8 | Hygiene | Admin job trigger map is out of sync with the scheduler | 07 |
| L9 | Hygiene | Failed network calls are recorded to the dead-letter queue twice | 05 |
| L10 | Hygiene | No foreign keys in the schema; `Organization.id` width unverified | 07 |

---

## 3. Sequencing

Ordered by damage prevented per hour, not by severity label.

```
┌─ Days 1-2 · incident response ─────────────────────────────┐
│  01 §1   Delete three lines, restore enrichment    ~1 hr   │
│  07 §1   Add ruff + mypy + pytest to CI            ~2 hrs  │
│  02 §1   Fix the credential mask round-trip        ~2 hrs  │
│  02 §2   Production defaults guard                 ~3 hrs  │
└────────────────────────────────────────────────────────────┘
┌─ Week 1 ───────────────────────────────────────────────────┐
│  01 §2-5  Finish the enrichment path               1-2 d   │
│  03 §1-2  Ingest cursor + bidder key               1 d     │
└────────────────────────────────────────────────────────────┘
┌─ Week 2 ───────────────────────────────────────────────────┐
│  02 §3-5  CORS, service worker, admin RBAC                 │
│  06       Import and export robustness                     │
│  07 §5-7  Test coverage for ingest and enrichment          │
└────────────────────────────────────────────────────────────┘
┌─ Week 3+ ──────────────────────────────────────────────────┐
│  04       Query performance, before volume forces it       │
│  05       Integrations and delivery                        │
│  03 §3-6  Pagination determinism, filter semantics         │
└────────────────────────────────────────────────────────────┘
```

**Why 07 §1 sits in the first four items.** Adding `ruff check` to CI is a two-hour task that
would have caught C1 — the platform's most serious defect — on the day it was written. It
belongs with the incident response, not the cleanup, because it is the control that prevents
the next C1.

---

## 4. Cross-cutting principle

Three of the highest-severity findings (C1, H2, H3) share one root cause: **a failure was
caught by a broad `except Exception`, logged at `warning`, and reported to the operator as an
empty result.** The platform cannot currently distinguish "the data source has nothing" from
"our code crashed before reaching it".

Every spec in this phase applies the same rule.

> An exception handler may only swallow an error it can name. `except Exception` wrapped
> around a block that includes first-party function calls is not acceptable; catch the
> specific transport or data error and let programming errors propagate to the job runner,
> which already records them as `status: failed`.

Where partial failure genuinely is acceptable — one company out of five hundred failing to
enrich — the handler must increment an error counter that reaches both the `job_runs` record
and the API response, so that "0 contacts, 12 errors" is distinguishable from
"0 contacts, 0 errors".

The three call sites that must change under this rule are listed in their owning specs:
`contact_enrichment.py` (spec 01 §2), `award_check.py` (spec 03 §2), and
`lead_service.py` (spec 01 §2).

---

## 4a. Corrections to these specs

Two things written here turned out to be wrong once the code was in hand. Both
are recorded rather than quietly edited, because a spec that silently rewrites
itself is as untrustworthy as one that goes stale.

- **Spec 07 §3.3 said implementing `RiskExclusionFilter` would be cheap**,
  because `Company.restricted_supplier` already exists. It is not implementable
  at all: qualification runs against a *tender* at discovery time, before any
  supplier is known, and restricted-supplier status belongs to the awarded
  company. Both that filter and `BEEFilter` were removed instead. Supplier risk
  is already applied where the data exists — `compute_lead_priority` scores a
  restricted supplier at zero.
- **Spec 04 §2 attributed the award ingest's seven-queries-per-award to the
  upsert lookups.** Batching those took a 40-award run from 285 local queries to
  86, but most of the remainder turned out to come from the *scoring* services,
  including a fresh load of the admin scoring config for every opportunity.
  Those are now passed the entities the loop already holds. Two genuine
  per-company aggregates remain.

Three defects were also found that the review missed entirely, all surfaced by
tests written for something else: `published_at` was passed unparsed on tender
insert; `Category.parent_id` had always been NULL because `_map_fields` returned
unaliased column names; and the category exclude filter excluded a category row
rather than a tender, so a tender in both an included and an excluded category
survived.

## 5. Phase acceptance criteria

- [ ] All 34 in-scope findings are closed, or explicitly deferred with a written reason
- [ ] `ruff check app tests` passes in CI on every push
- [ ] `mypy app` passes in CI, or its remaining failures are baselined against a tracking issue
- [ ] `pytest` covers the award ingest, tender discovery, and contact enrichment paths
- [ ] Starting the backend with `ORICRED_DEBUG=false` and any shipped default secret refuses to boot
- [ ] The `contact_enrichment` job records a non-zero contact count against a real Tenders-SA database
- [ ] No `except Exception` remains around a block containing first-party calls, except where §4's counter rule is applied
- [ ] AGENTS.md matches the code for every section this phase touches
