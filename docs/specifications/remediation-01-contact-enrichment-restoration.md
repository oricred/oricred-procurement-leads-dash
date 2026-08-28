# Remediation 01 — Contact Enrichment Restoration

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** C1 (critical), H3 (high), M8 (medium), M12 (medium)
**Depends on:** nothing — this spec is implementable immediately

---

## Objective

Make the platform's headline capability work: pull a named, reachable contact at an awarded
supplier from the Tenders-SA database, store it, and show it to the operator.

Today none of that happens. Three query methods crash on every call, the crash is swallowed,
the database constraint would reject most of the rows even if they arrived, the fallback
matcher can attach the wrong people to a company, and the UI would not refresh to show them.
This spec fixes the whole chain, because fixing any one link leaves the feature still broken.

---

## 1. Restore the three TSA query methods (C1)

### 1.1 Current state

`query_directors`, `query_key_personnel`, and `query_source_directors` each contain a line
referencing a name that does not exist in their scope:

```python
# backend/app/clients/tsa_db.py:627, :661, :687
sql += " ORDER BY d.full_name"
params["limit"] = limit
params["offset"] = max(offset, 0)   # <- `offset` is not a parameter of this function
sql += " LIMIT :limit"
```

None of the three declares an `offset` parameter, none emits an `OFFSET` clause, and there is
no module-level `offset` binding. Python raises at runtime:

```
query_directors        -> NameError: name 'offset' is not defined
query_key_personnel    -> NameError: name 'offset' is not defined
query_source_directors -> NameError: name 'offset' is not defined
```

The four sibling methods that *do* accept `offset` (`query_tenders`, `query_awards`,
`query_companies`, `query_organizations`) all emit `LIMIT :limit OFFSET :offset` correctly.
The three broken ones look like a copy-paste of the parameter binding without the signature
or the SQL that goes with it.

### 1.2 Change

Delete the three `params["offset"]` lines. Do **not** add an `offset` parameter — no caller
paginates these, and the 5,000-row default limit is well above the realistic count of
directors for a single company.

```diff
  sql += " ORDER BY d.full_name"
  params["limit"] = limit
- params["offset"] = max(offset, 0)
  sql += " LIMIT :limit"
```

Apply the identical deletion at `tsa_db.py:627`, `:661`, and `:687`.

### 1.3 Regression test

`ruff check` already catches this class of defect (`F821`), and spec 07 §1 puts it in CI. Add
a direct test as well, because a lint rule can be disabled and a test cannot be silently
skipped:

```python
# backend/tests/test_tsa_db.py

@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("query_directors", {"company_ids": ["c1"]}),
        ("query_key_personnel", {"company_ids": ["c1"]}),
        ("query_source_directors", {"organization_ids": ["o1"]}),
    ],
)
async def test_contact_queries_build_and_execute(method, kwargs, tsa_db_stub):
    """Guards against the NameError class of defect: these must reach the session."""
    rows = await getattr(tsa_db_stub, method)(**kwargs)
    assert rows == []
    sql = tsa_db_stub.last_sql
    assert "LIMIT :limit" in sql
    assert "OFFSET" not in sql          # these methods deliberately do not paginate
    assert ":offset" not in tsa_db_stub.last_params
```

`tsa_db_stub` is a `TSADatabase` whose `_session_factory` is replaced with a recorder that
captures the SQL and parameters and returns an empty result set. It needs no live database.

---

## 2. Stop swallowing programming errors (C1, cross-cutting)

### 2.1 Current state

The reason C1 survived for months is not the typo — it is that every call site hides it:

```python
# backend/app/services/contact_enrichment.py:229-243 (and :245, :279, :295, :330)
try:
    directors = await tsa_db.query_directors(company_ids=[tsa_id])
    for d in directors:
        ...
except Exception as e:
    logger.warning("director_fetch_failed", company=company.name, error=str(e))
```

A `NameError` is indistinguishable here from a network timeout. The enrichment job therefore
finishes, returns `{"added": 0}`, and `run_job` records `status: success`. The operator sees
"No contacts found in Tenders-SA" in the modal.

### 2.2 Change

Introduce a narrow exception set and an error counter that reaches the caller.

```python
# backend/app/services/contact_enrichment.py

from sqlalchemy.exc import DBAPIError, SQLAlchemyError

# Errors that mean "this one company could not be enriched right now".
# Anything else is a bug in our code and must reach the job runner.
RECOVERABLE = (DBAPIError, SQLAlchemyError, TimeoutError, OSError)


@dataclass
class EnrichmentResult:
    added: int = 0
    errors: int = 0
    companies_attempted: int = 0

    def __add__(self, other: "EnrichmentResult") -> "EnrichmentResult":
        return EnrichmentResult(
            self.added + other.added,
            self.errors + other.errors,
            self.companies_attempted + other.companies_attempted,
        )
```

Every `except Exception` in this module becomes `except RECOVERABLE`, and every handler
increments `result.errors` rather than only logging:

```python
try:
    directors = await tsa_db.query_directors(company_ids=[tsa_id])
except RECOVERABLE as exc:
    logger.warning("director_fetch_failed", company=company.name, error=str(exc))
    result.errors += 1
else:
    for d in directors:
        if await _upsert_contact(...):
            result.added += 1
```

Apply the same treatment to `lead_service.retry_new_lead_contact_lookups` (line 70) and
`historical_contacts.sync_historical_contacts` (line 191).

### 2.3 Surface the counter

`run_contact_enrichment` currently returns `None`, so `job_runs.items_processed` is always
null. Return the count and fail the run when the error rate is high enough to mean something
systemic is wrong:

```python
# backend/app/jobs/contact_enrichment.py

ERROR_RATE_THRESHOLD = 0.5


async def run_contact_enrichment() -> int:
    logger.info("job_started", job="contact_enrichment")
    result = await enrich_all_contacts()
    retried = await retry_new_lead_contact_lookups()

    attempted = result.companies_attempted
    if attempted and result.errors / attempted >= ERROR_RATE_THRESHOLD:
        raise RuntimeError(
            f"Contact enrichment failed for {result.errors} of {attempted} companies"
        )

    logger.info(
        "job_completed", job="contact_enrichment",
        added=result.added, errors=result.errors, lead_retries=retried,
    )
    return result.added
```

`run_job` already turns a raised exception into `status: failed` with the message in
`job_runs.error`, which the Admin → Jobs table already renders.

### 2.4 Surface it in the API

`POST /opportunities/{id}/find-contact` returns `contacts_added` only. Add the error count so
the modal can tell the two cases apart:

```python
# backend/app/api/opportunities.py — find_opportunity_contact
return {
    "opportunity": opportunity.model_dump(),
    "contacts_added": result.added,
    "lookup_errors": result.errors,
}
```

---

## 3. Allow more than one phone-only contact per company (H3)

### 3.1 Current state

Three mechanisms disagree about how "this contact has no email" is represented.

| Mechanism | Location | Representation |
|-----------|----------|----------------|
| Enrichment writer | `contact_enrichment.py:120` | `email = email or ""` |
| Enrichment reader | `contact_enrichment.py:91` | looks for `Contact.email == ""` |
| Startup migration | `database.py:103` | rewrites `''` to `NULL`, once, at boot |
| Table constraint | `contact.py:29-32` | `UniqueConstraint("company_id", "email")` |

The consequence: the first director with a phone and no email occupies the key
`(company_id, "")`. The second raises `IntegrityError`, caught by the §2 handler and logged as
a warning. After a restart the startup migration rewrites those rows to `NULL`, at which point
the reader at line 91 can no longer find them and the writer inserts duplicates instead.

### 3.2 Change — represent "unknown" as NULL everywhere

```diff
  contact = Contact(
      company_id=company_id,
      organization_id=organization_id,
      first_name=first_name,
      last_name=last_name,
      job_title=job_title,
-     email=email or "",
+     email=email or None,
      phone_direct=phone,
      phone_mobile=None,
      source=source,
  )
```

And the lookup at line 89-93 becomes:

```diff
  result = await db.execute(
      select(Contact)
-     .where(*entity_filters, Contact.email == "")
+     .where(*entity_filters, Contact.email.is_(None))
      .limit(1)
  )
```

### 3.3 Change — make the constraints partial

Two rows with `email IS NULL` must not collide. Replace the full unique constraints with
partial unique indexes:

```python
# backend/app/models/contact.py

from sqlalchemy import Index, text

    __table_args__ = (
        Index(
            "uq_contact_company_email",
            "company_id", "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
        Index(
            "uq_contact_org_email",
            "organization_id", "email",
            unique=True,
            postgresql_where=text("email IS NOT NULL"),
            sqlite_where=text("email IS NOT NULL"),
        ),
    )
```

`Base.metadata.create_all` skips existing tables entirely, indexes included, so the change
needs explicit DDL for deployed databases. Extend the existing pattern in `database.py`:

```python
async def _ensure_contact_indexes() -> None:
    """Replace the full unique constraints with partial ones so multiple
    phone-only contacts can coexist for a company."""
    async with engine.begin() as conn:
        await conn.execute(text("UPDATE contacts SET email = NULL WHERE email = ''"))
        if conn.dialect.name == "sqlite":
            await conn.execute(text("DROP INDEX IF EXISTS uq_contact_company_email"))
            await conn.execute(text("DROP INDEX IF EXISTS uq_contact_org_email"))
        else:
            await conn.execute(text(
                "ALTER TABLE contacts DROP CONSTRAINT IF EXISTS uq_contact_company_email"
            ))
            await conn.execute(text(
                "ALTER TABLE contacts DROP CONSTRAINT IF EXISTS uq_contact_org_email"
            ))
            await conn.execute(text("ALTER TABLE contacts ALTER COLUMN email DROP NOT NULL"))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_company_email "
            "ON contacts (company_id, email) WHERE email IS NOT NULL"
        ))
        await conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_contact_org_email "
            "ON contacts (organization_id, email) WHERE email IS NOT NULL"
        ))
```

Call it from `init_db()` and delete `_ensure_contact_email_nullable`, whose `DROP NOT NULL` is
now folded into the block above.

> **Note on de-duplication.** Removing the unique key on `(company_id, NULL)` means the
> database no longer prevents duplicate phone-only contacts. `_upsert_contact` already
> de-duplicates by phone number and then by name before inserting; those checks become the
> sole guard and must therefore run before every insert, which they do. Add a test that
> enriching the same company twice produces one contact, not two.

---

## 4. Replace substring company matching (M8)

### 4.1 Current state

```python
# backend/app/services/contact_enrichment.py:150-154 and :189-193
for tsa_name, tsa_id in tsa_by_name.items():
    if local_lower in tsa_name or tsa_name in local_lower:
        mapping[local.id] = tsa_id
        logger.info("company_name_fuzzy_match", local=local.name, tsa=tsa_name)
        break
```

The first substring hit wins, across a dictionary of up to 10,000 companies in arbitrary
insertion order. "ABC Trading" matches "ABC Trading Holdings", "ABCD Trading", and every other
name containing the substring; whichever the dict yields first is accepted.

This is not a cosmetic mislabel. The matched TSA company's directors — real people's mobile
numbers and personal email addresses — are written onto the wrong local company's lead record,
and an operator then calls them.

### 4.2 Change — normalise, then require an unambiguous match

```python
# backend/app/services/text_utils.py

LEGAL_SUFFIXES = {
    "pty", "ltd", "limited", "proprietary", "inc", "incorporated",
    "cc", "close corporation", "npc", "soc", "trust", "and", "the",
}


def normalise_company_name(name: str) -> str:
    """Reduce a company name to a comparable key.

    Lowercases, strips punctuation, collapses whitespace, and removes South African
    legal-form suffixes so that "ABC Trading (Pty) Ltd" and "ABC TRADING PTY LTD"
    produce the same key — while "ABC Trading" and "ABC Trading Holdings" do not.
    """
    cleaned = re.sub(r"[^a-z0-9\s]", " ", name.lower())
    tokens = [t for t in cleaned.split() if t not in LEGAL_SUFFIXES]
    return " ".join(tokens)
```

The matcher then accepts a match only when exactly one TSA company shares the normalised key:

```python
async def _match_companies_to_tsa(
    tsa_db: TSADatabase,
    local_companies: list[Company],
) -> dict[str, str]:
    mapping: dict[str, str] = {}
    unmatched: list[Company] = []
    for c in local_companies:
        if c.api_id and not _is_synthetic_company_api_id(c.api_id):
            mapping[c.id] = c.api_id
        else:
            unmatched.append(c)
    if not unmatched:
        return mapping

    tsa_companies = await tsa_db.query_companies(limit=10000)
    by_key: dict[str, list[str]] = defaultdict(list)
    for c in tsa_companies:
        name = (c.get("name") or "").strip()
        if name:
            by_key[normalise_company_name(name)].append(c["id"])

    for local in unmatched:
        candidates = by_key.get(normalise_company_name(local.name), [])
        if len(candidates) == 1:
            mapping[local.id] = candidates[0]
        elif candidates:
            logger.info(
                "company_match_ambiguous",
                local=local.name, candidate_count=len(candidates),
            )
        else:
            logger.info("company_match_none", local=local.name)

    return mapping
```

Apply the same shape to `_match_orgs_to_tsa`.

### 4.3 Consequence to accept

Match rate will drop. That is the point: an unmatched company shows the operator "no contact
found" and prompts a manual lookup, which is recoverable. A wrong match sends them to a
stranger, which is not. Ambiguous and unmatched counts are logged so the normaliser can be
tuned against real data.

### 4.4 Tests

```python
def test_normalise_strips_legal_form():
    assert normalise_company_name("ABC Trading (Pty) Ltd") == "abc trading"
    assert normalise_company_name("ABC TRADING PTY LTD") == "abc trading"


def test_normalise_does_not_conflate_distinct_names():
    assert normalise_company_name("ABC Trading") != normalise_company_name("ABC Trading Holdings")
    assert normalise_company_name("ABC Trading") != normalise_company_name("ABCD Trading")


async def test_ambiguous_match_is_rejected():
    """Two TSA companies normalising to the same key must produce no match at all."""
```

---

## 5. Refresh the UI when contacts arrive (M12)

### 5.1 Current state

```typescript
// frontend/src/components/OpportunityModal.tsx:162-163
queryClient.invalidateQueries({ queryKey: ['leads'] });
queryClient.invalidateQueries({ queryKey: ['opportunities', opp.id] });
```

No query uses `['opportunities', opp.id]`. The modal's own query is `['opportunity', opp.id]`
(singular) and the pipeline board's is `['opportunities']` (no ID). TanStack Query matches a
filter key as a *prefix* of a query key, so a filter longer than the query key never matches —
`['opportunities', id]` matches neither.

### 5.2 Change

```diff
  onSuccess: (res) => {
    const added = res.data.contacts_added;
    ...
    queryClient.invalidateQueries({ queryKey: ['leads'] });
-   queryClient.invalidateQueries({ queryKey: ['opportunities', opp.id] });
+   queryClient.invalidateQueries({ queryKey: ['opportunity', opp.id] });
+   queryClient.invalidateQueries({ queryKey: ['opportunities'] });
  },
```

Apply the same correction to `updateMutation.onSuccess` (line 175), which currently refreshes
the modal but leaves the board showing a stale assignee and risk flag.

### 5.3 Distinguish "none found" from "lookup failed"

With §2.4 supplying `lookup_errors`, the feedback message stops lying:

```typescript
onSuccess: (res) => {
  const { contacts_added: added, lookup_errors: errors } = res.data;
  if (added > 0) {
    setFindContactFeedback(`Found ${added} contact${added !== 1 ? 's' : ''}`);
    setShowManualGuidance(false);
  } else if (errors > 0) {
    setFindContactFeedback('Contact lookup could not reach Tenders-SA — try again shortly');
    setShowManualGuidance(false);
  } else {
    setFindContactFeedback('No contacts on file at Tenders-SA for this supplier');
    setShowManualGuidance(true);
  }
  ...
}
```

The manual-research guidance should appear only in the third case. Showing it after a failed
lookup sends the operator off to do work that the system could have done.

---

## 6. Files to change

| File | Change |
|------|--------|
| `backend/app/clients/tsa_db.py` | §1.2 — delete three `params["offset"]` lines |
| `backend/app/services/contact_enrichment.py` | §2.2 `RECOVERABLE` + `EnrichmentResult`; §3.2 NULL email; §4.2 normalised matching |
| `backend/app/services/text_utils.py` | §4.2 — add `normalise_company_name` and `LEGAL_SUFFIXES` |
| `backend/app/services/lead_service.py` | §2.2 — narrow the handler at line 70; propagate `EnrichmentResult` |
| `backend/app/services/historical_contacts.py` | §2.2 — narrow the handler at line 191 |
| `backend/app/jobs/contact_enrichment.py` | §2.3 — return a count, fail on high error rate |
| `backend/app/api/opportunities.py` | §2.4 — return `lookup_errors` from `find-contact` |
| `backend/app/models/contact.py` | §3.3 — partial unique indexes |
| `backend/app/database.py` | §3.3 — `_ensure_contact_indexes`, drop `_ensure_contact_email_nullable` |
| `frontend/src/components/OpportunityModal.tsx` | §5.2 query keys; §5.3 feedback branches |
| `frontend/src/services/api.ts` | §2.4 — add `lookup_errors` to the `findContact` response type |
| `backend/tests/test_tsa_db.py` | §1.3 — execution test for the three methods |
| `backend/tests/test_contact_enrichment.py` | **new** — §3, §4 coverage |

---

## 7. Acceptance criteria

- [ ] `ruff check app` reports zero `F821` errors
- [ ] Calling all three TSA contact query methods against a stubbed session returns rows instead of raising
- [ ] `contact_enrichment` job run records a non-zero `items_processed` against a real Tenders-SA database
- [ ] A TSA outage during enrichment produces `status: failed` on the job run, not `status: success` with zero items
- [ ] Two directors at the same company, both with a phone and no email, both persist
- [ ] Re-running enrichment for the same company adds no duplicate contacts
- [ ] "ABC Trading (Pty) Ltd" matches "ABC TRADING PTY LTD" and does not match "ABC Trading Holdings"
- [ ] Two TSA companies with the same normalised name produce no match and log `company_match_ambiguous`
- [ ] Clicking *Find contact* with a reachable supplier shows the new contacts without closing the modal
- [ ] The pipeline card's contact-readiness badge updates in the same interaction
- [ ] A failed lookup shows a retry message; only a genuinely empty result shows the manual-research guidance

---

## 8. Deferred scope

- LinkedIn or web enrichment as a second source when Tenders-SA has no contact. The manual
  guidance panel stays until then.
- Token-similarity scoring for company matching. §4 deliberately ships exact-normalised-only
  first, so the ambiguous-match log can be read against real data before a threshold is picked.
- Operator-facing review queue for ambiguous matches.
