# Error Report — 2026-07-15

## Overview

Three active production errors were identified by observing `journalctl` logs for `oricred-backend.service`. All three are ingestion-related (SQL datetime type mismatches). No frontend interface errors (broken UI, API failures visible to users) were detected.

---

## Ingestion Errors

### 1. `tender_query_failed` (Discovery Job)

| Field | Value |
|---|---|
| **Error** | `asyncpg.exceptions.DataError: invalid input for query argument $1: '2026-07-15T11:45:00.542986+00:00' (expected a datetime.date or datetime.datetime instance, got 'str')` |
| **Frequency** | Every discovery run (every ~60s) |
| **Root Cause** | `backend/app/jobs/discovery.py:161` passes `now.isoformat()` (a string) as `closing_from` filter. The TSA DB query builder stores it into the SQL params dict as-is, and asyncpg rejects the string for a `timestamptz` column. |
| **Fix** | Replace `now.isoformat()` with `now` (the raw datetime object). |
| **Impact** | Discovery job ingests 0 tenders from TSA DB (data source is effectively dead). |

### 2. `award_ingestion_query_failed` (Award Check Job)

| Field | Value |
|---|---|
| **Error** | `asyncpg.exceptions.DataError: invalid input for query argument $1: '2026-06-15T11:44:21.371330+00:00' (expected a datetime.date or datetime.datetime instance, got 'str')` |
| **Frequency** | Every award_check run (every ~60s) |
| **Root Cause** | `backend/app/jobs/award_check.py:219` passes `since.isoformat()` (a string) as `since` filter. Same mechanism as Bug #1. |
| **Fix** | Replace `since.isoformat()` with `since` (the raw datetime object). |
| **Impact** | Award check job ingests 0 awards from TSA DB. No new awards discovered. |

### 3. `historical_contacts job_failed`

| Field | Value |
|---|---|
| **Error** | `TypeError: can't subtract offset-naive and offset-aware datetimes` |
| **Frequency** | Every historical_contacts run (on trigger) |
| **Root Cause** | `backend/app/services/historical_contacts.py:121` produces an offset-aware `cutoff` datetime, but the downstream TSA DB query (or internal asyncpg handling) expects offset-naive. The mismatch causes the subtraction error during parameter binding. |
| **Fix** | Strip timezone info from `cutoff` with `.replace(tzinfo=None)` before passing as a SQL filter parameter, or make all datetimes consistently aware. |
| **Impact** | Historical contact enrichment job fails completely. |

---

## Interface Errors

No frontend interface errors detected:

| Check | Result |
|---|---|
| Frontend build (`npm run build`) | ✅ Succeeds (1698 modules, no TS errors) |
| Frontend dist directory | ✅ Present up to date |
| API endpoints responding | ✅ All endpoints return 200 |
| Auth/Login | ✅ Works |
| Dashboard stats | ✅ Works |
| Tenders list | ✅ Works |
| Awards list | ✅ Works |
| Categories | ✅ Works |

---

## Recommendations

1. **Fix ingestion errors immediately** — all three are simple one-liner datetime fixes in `discovery.py`, `award_check.py`, and `historical_contacts.py`.
2. **Add datetime type validation** — ensure all datetime parameters going into TSA DB queries are validated as `datetime` objects (not strings) with consistent timezone awareness.
3. **Run tests** — `pytest backend/tests/` to verify fixes don't regress.
