# Remediation 05 — Integrations & Delivery

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** H6 (high), L5, L6, L7, L9 (hygiene)
**Depends on:** spec 02 §1 (credential storage must be trustworthy before the CRM reads from it)

---

## Objective

Make the two outbound integrations — Monday.com and SMTP — work with the configuration the
platform ships, cost a bounded number of network calls, and stop blocking the request path.

The Monday adapter cannot succeed with its own default board ID. The email service ignores the
recipient list the Admin page collects and opens a fresh TLS connection per message inside the
ingest loop. Both are the kind of defect that looks fine in a unit test and fails on the first
real run.

---

## 1. Make the Monday.com adapter usable (H6)

### 1.1 Current state — the default board ID is not valid GraphQL

Every query interpolates identifiers directly into the document:

```python
# backend/app/services/crm/monday.py:40-48
query = f"""
mutation {{
  create_item (
    board_id: {board_id},
    group_id: "{group_id}",
    item_name: {json.dumps(name)},
    column_values: {json.dumps(json.dumps(column_values))}
  ) {{ id }}
}}
"""
```

```python
# :75-88
query = f"""
query {{
  boards (ids: {board_id}) {{ ... }}
}}
"""
```

The shipped default is a string:

```python
# backend/app/services/admin_config.py:13
"monday_board_id": "oricred_opportunities",
```

`board_id: oricred_opportunities` and `ids: oricred_opportunities` are unquoted identifiers
where Monday expects an `ID!`. Every request is a GraphQL syntax error until an operator
happens to replace the default with a numeric board ID. Nothing in the Admin UI says that is
required.

### 1.2 Current state — injection surface

`board_id`, `group_id`, `item_id`, and `column_id` all reach the document unescaped.
`group_id` and `board_id` come from admin-controlled configuration and `item_id` from
`opportunities.crm_item_id`, so this is not remotely reachable — but it is one careless
migration away from being so, and the fix costs nothing.

### 1.3 Change — GraphQL variables

```python
async def _execute(self, query: str, variables: dict | None = None) -> dict:
    response = await self._client.post(
        "", json={"query": query, "variables": variables or {}},
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        logger.error("monday_api_error", errors=data["errors"])
        raise CRMError(f"Monday.com API error: {data['errors']}")
    return data["data"]


CREATE_ITEM = """
mutation ($boardId: ID!, $groupId: String!, $itemName: String!, $columnValues: JSON!) {
  create_item (
    board_id: $boardId,
    group_id: $groupId,
    item_name: $itemName,
    column_values: $columnValues
  ) { id }
}
"""


async def create_item(self, board_id: str, group_id: str, name: str, column_values: dict) -> str:
    result = await self._execute(CREATE_ITEM, {
        "boardId": board_id,
        "groupId": group_id,
        "itemName": name,
        "columnValues": json.dumps(column_values),
    })
    return result["create_item"]["id"]
```

Apply the same treatment to `update_column_value`, `get_recent_activity`, and `search_items`.
Move the `import json` calls to module level while doing so.

### 1.4 Change — validate the board ID and fail with a usable message

```python
# backend/app/services/crm/monday.py

class CRMError(RuntimeError):
    """Raised when the CRM rejects a request or is misconfigured."""


def validate_board_id(board_id: str) -> str:
    if not str(board_id).strip().isdigit():
        raise CRMError(
            f"Monday.com board ID must be numeric, got {board_id!r}. "
            "Copy it from the board URL: monday.com/boards/<board-id>."
        )
    return str(board_id).strip()
```

Called once in `MondayDotComAdapter.__init__`-adjacent code paths — `_get_board_config` in
`crm/sync.py` is the single choke point:

```python
async def _get_board_config(db: AsyncSession) -> tuple[str, str]:
    creds = await get_config("admin_credentials", db)
    return (
        validate_board_id(creds.get("monday_board_id", "")),
        creds.get("monday_group_id", "main"),
    )
```

### 1.5 Change — remove the misleading default

```diff
# backend/app/services/admin_config.py
- "monday_board_id": "oricred_opportunities",
+ "monday_board_id": "",
```

An empty board ID means "CRM sync not configured", which `_get_adapter` already handles for
the API key. Extend that check so a missing board ID is treated the same way rather than
raising on every transition:

```python
async def push_opportunity_to_crm(opportunity_id: str) -> None:
    async with async_session() as db:
        adapter = await _get_adapter(db)
        if not adapter:
            return
        try:
            board_id, group_id = await _get_board_config(db)
        except CRMError as exc:
            logger.warning("crm_not_configured", error=str(exc))
            return
```

### 1.6 Verify the API version and `items` field

Two things to confirm against a live workspace before closing H6:

- **`API-Version` header.** The adapter sends none. Monday resolves an unversioned request to
  the account's default version, which changes over time. Pin it:
  `headers["API-Version"] = "2024-10"` (or the current stable), and record the pinned version
  in a comment with a note to review it annually.
- **`boards { items }`.** `search_items` (line 103-117) queries a field Monday replaced with
  `items_page` in version `2023-10`. If the pinned version postdates that, rewrite as:

```graphql
query ($boardId: ID!, $limit: Int!) {
  boards (ids: [$boardId]) {
    items_page (limit: $limit) {
      items { id name column_values { id text } }
    }
  }
}
```

`search_items` has no callers today, so this can be fixed or the method deleted — see spec 07
§3.

---

## 2. Push CRM updates in one request, off the request path (L7)

### 2.1 Current state

```python
# backend/app/services/crm/sync.py:103-106
if opp.crm_item_id:
    for col_id, value in column_values.items():
        await adapter.update_column_value(opp.crm_item_id, col_id, value)
```

Up to seven columns are set, so an update is up to seven sequential HTTP round trips to
Monday. And `push_opportunity_to_crm` is awaited *inside* three request handlers:

| Handler | Line |
|---------|------|
| `transition_opportunity` | `opportunities.py:261` |
| `mark_contacted` | `opportunities.py:349` |
| `assign_opportunity` | `opportunities.py:369` |

Dragging a card between kanban columns therefore blocks on up to seven external calls before
the API responds. Each is wrapped in `try/except Exception` so a Monday outage does not fail
the transition — but it does add its full timeout (30 s) to the response.

### 2.2 Change — one mutation

```python
CHANGE_MULTIPLE = """
mutation ($boardId: ID!, $itemId: ID!, $columnValues: JSON!) {
  change_multiple_column_values (
    board_id: $boardId, item_id: $itemId, column_values: $columnValues
  ) { id }
}
"""


async def update_columns(self, board_id: str, item_id: str, column_values: dict) -> None:
    await self._execute(CHANGE_MULTIPLE, {
        "boardId": board_id,
        "itemId": item_id,
        "columnValues": json.dumps(column_values),
    })
```

`update_column_value` stays on the `CRMAdapter` interface for single-field updates, but
`sync.py` calls `update_columns`.

### 2.3 Change — move the push off the request path

```python
# backend/app/api/opportunities.py

@router.post("/{opportunity_id}/transition", response_model=OpportunityRead)
async def transition_opportunity(
    opportunity_id: str,
    body: OpportunityTransition,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    ...
    await db.commit()
    await db.refresh(opp)
    background_tasks.add_task(push_opportunity_to_crm, opportunity_id)
    return await _read_opportunity_with_context(opp, db)
```

`push_opportunity_to_crm` opens its own session (`sync.py:41`), so it is already safe to run
after the response is sent. The `try/except` at each call site can then be deleted — the
function logs its own failures and nothing depends on its return value.

`admin.py:173` already uses `BackgroundTasks` for job triggers, so the pattern is established.

> **Trade-off accepted.** A background push that fails is invisible to the operator who made
> the change. Record the last push outcome on the opportunity
> (`crm_synced_at`, `crm_sync_error`) so the modal can show "not yet synced to Monday" rather
> than silently diverging. This is the one piece of new schema in this spec.

---

## 3. Send notifications to the configured recipients (L5)

### 3.1 Current state

The Admin → Notifications config defines recipients and per-event toggles:

```python
# backend/app/services/admin_config.py:31-38
DEFAULT_NOTIFICATIONS = {
    "recipients": ["ops@oricred.com"],
    "events": {
        "award_detected": {"enabled": True, "subject": "..."},
        "past_due_alert": {"enabled": True, "subject": "..."},
        "api_failure": {"enabled": True, "subject": "..."},
    },
}
```

Nothing reads it. Both send sites hardcode the address:

```python
# backend/app/jobs/award_check.py:230 and :360
await email.send("past_due", "ops@oricred.com", ...)
await email.send("award_detected", "ops@oricred.com", ...)
```

Changing the recipient in the Admin UI has no effect, and the per-event enable toggles do
nothing. The `subject` templates in the config are also ignored — `EmailAlertService` has its
own hardcoded `subject_map` (`email_alert.py:61-66`).

### 3.2 Change — resolve recipients and toggles at send time

```python
# backend/app/services/email_alert.py

class EmailAlertService:
    def __init__(self, config: dict | None = None) -> None:
        self._config = config or {}
        self._enabled = bool(settings.smtp_host and settings.smtp_user and settings.smtp_password)

    @classmethod
    async def from_config(cls, db: AsyncSession) -> "EmailAlertService":
        return cls(await get_config("admin_notifications", db))

    def _recipients(self, event_type: str) -> list[str]:
        event = self._config.get("events", {}).get(event_type, {})
        if not event.get("enabled", True):
            return []
        return [r for r in self._config.get("recipients", []) if r.strip()]

    async def send(self, event_type: str, **kwargs) -> bool:
        recipients = self._recipients(event_type)
        if not recipients:
            logger.info("alert_suppressed", event_type=event_type)
            return False
        ...
```

The `recipient` positional argument is dropped from the signature; both call sites in
`award_check.py` lose their hardcoded address. `check_awards_for_watching` builds the service
once per run with `await EmailAlertService.from_config(db)`.

`api_failure` is defined in both the templates and the config but is never sent. Wire it to
the dead-letter recorder in `clients/base.py:62` so an integration outage actually alerts
somebody, or remove it from both — see §5.

### 3.3 Change — template formatting must not raise

```python
# email_alert.py:69
body = template.format(**kwargs)
```

sits outside the `try`, so a missing or misnamed key raises `KeyError` straight into the
caller — in `award_check` that is inside the ingest loop, which would abort the run. Move it
inside the guarded block and fall back to a plain rendering:

```python
try:
    body = template.format(**kwargs)
except (KeyError, IndexError, ValueError) as exc:
    logger.warning("alert_template_error", event_type=event_type, error=str(exc))
    body = "\n".join(f"{k}: {v}" for k, v in kwargs.items())
```

---

## 4. Batch email delivery (L6)

### 4.1 Current state

```python
# backend/app/services/email_alert.py:95-100
@staticmethod
def _smtp_send(msg: MIMEText, host: str, port: int, user: str, password: str) -> None:
    with smtplib.SMTP(host, port, timeout=15) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg)
```

One TCP connection, one TLS handshake, and one authentication per message — and `send` is
called from inside the award ingest loop (`award_check.py:359`). An admin-triggered 30-day
backfill that creates 1,000 leads performs 1,000 handshakes and 1,000 logins, serially, each
with a 15-second timeout budget. It also means 1,000 individual emails land in the operator's
inbox for one action.

### 4.2 Change — collect during the run, send once at the end

Alerts generated inside a job are queued and flushed after the loop:

```python
class EmailAlertService:
    def __init__(self, config=None):
        ...
        self._queue: list[tuple[str, list[str], str, str]] = []

    async def queue(self, event_type: str, **kwargs) -> None:
        """Defer an alert until flush(). Used inside batch jobs."""

    async def flush(self) -> int:
        """Send every queued message over a single SMTP connection."""
        if not self._queue:
            return 0
        return await asyncio.to_thread(self._smtp_send_many, list(self._queue))

    @staticmethod
    def _smtp_send_many(messages: list[...]) -> int:
        sent = 0
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as server:
            server.starttls()
            server.login(settings.smtp_user, settings.smtp_password)
            for msg in messages:
                try:
                    server.send_message(msg)
                    sent += 1
                except smtplib.SMTPException as exc:
                    logger.warning("email_send_failed", error=str(exc))
        return sent
```

`check_awards_for_watching` calls `queue(...)` in the loop and `await email.flush()` after
`_mark_overdue_watches`, inside the existing `finally`.

### 4.3 Change — digest instead of one-per-lead

1,000 separate "Award Detected" emails is not a useful notification. Above a threshold, send
one digest:

```python
AWARD_DIGEST_THRESHOLD = 5

# after the ingest loop
if len(new_opportunity_ids) >= AWARD_DIGEST_THRESHOLD:
    await email.send_digest("award_detected", count=len(new_opportunity_ids), items=summaries[:50])
else:
    await email.flush()
```

The digest template lists supplier, amount, and a deep link per lead, capped at 50 rows with a
"and N more" line.

---

## 5. Stop double-recording dead-letter entries (L9)

### 5.1 Current state

```python
# backend/app/clients/base.py:50-60
except (httpx.TimeoutException, httpx.NetworkError) as e:
    last_exception = e
    if attempt < self.MAX_RETRIES:
        ...
    else:
        await self._record_failure(method, path, kwargs, str(e), self.MAX_RETRIES + 1)   # (1)
if last_exception:
    await self._record_failure(method, path, kwargs, str(last_exception), self.MAX_RETRIES + 1)  # (2)
raise last_exception
```

On the final network-error attempt, the `else` branch records the failure and then falls out
of the loop, where the trailing block records it again. Every network failure produces two
dead-letter rows, so the Admin dead-letter count is double the real figure and retrying one
row leaves its twin unresolved.

`last_status` (line 39) is assigned and never read — `ruff F841`.

### 5.2 Change

```python
async def request(self, method: str, path: str, **kwargs: Any) -> dict:
    last_exception: Exception | None = None
    for attempt in range(self.MAX_RETRIES + 1):
        try:
            response = await self._client.request(method, path, **kwargs)
            if response.status_code == 429:
                await asyncio.sleep(self._retry_after(response))
                continue
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (401, 403, 404):
                logger.error("api_auth_error", status=e.response.status_code, path=path)
                raise
            last_exception = e
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            last_exception = e
        if attempt < self.MAX_RETRIES:
            await asyncio.sleep(self.RETRY_DELAYS[attempt])

    assert last_exception is not None
    await self._record_failure(method, path, kwargs, str(last_exception), self.MAX_RETRIES + 1)
    raise last_exception
```

One record, one raise, one exit path.

### 5.3 Change — bound the `Retry-After` sleep

```python
MAX_RETRY_AFTER_SECONDS = 120

def _retry_after(self, response: httpx.Response) -> int:
    raw = response.headers.get("Retry-After", "60")
    try:
        delay = int(raw)
    except ValueError:
        delay = 60          # RFC allows an HTTP-date here; treat it as the default
    return min(max(delay, 1), self.MAX_RETRY_AFTER_SECONDS)
```

`int(response.headers.get("Retry-After", "60"))` currently raises `ValueError` on a
date-formatted header, and an unbounded value would block a request handler — `retry_failed_api_call`
in `admin.py:295` calls `request()` synchronously from an HTTP endpoint.

### 5.4 Change — alert on dead-letter growth

`_record_failure` is the natural place to fire the `api_failure` alert that §3.2 found is
defined but never sent:

```python
await self._record_failure(...)
await EmailAlertService(...).send(
    "api_failure", endpoint=path, error=str(last_exception)[:200],
    attempts=self.MAX_RETRIES + 1, failed_at=datetime.now(timezone.utc).isoformat(),
)
```

Rate-limit it to at most one alert per endpoint per hour so an outage does not itself become a
mail flood.

---

## 6. Files to change

| File | Change |
|------|--------|
| `backend/app/services/crm/monday.py` | §1.3 variables; §1.4 `CRMError`, `validate_board_id`; §1.6 API version; §2.2 `update_columns` |
| `backend/app/services/crm/sync.py` | §1.4 validation choke point; §1.5 unconfigured handling; §2.2 single mutation |
| `backend/app/services/crm/__init__.py` | §2.2 — `update_columns` on the `CRMAdapter` interface |
| `backend/app/services/admin_config.py` | §1.5 — empty `monday_board_id` default |
| `backend/app/api/opportunities.py` | §2.3 — background CRM push at three call sites |
| `backend/app/models/opportunity.py` | §2.3 — `crm_synced_at`, `crm_sync_error` |
| `backend/app/database.py` | §2.3 — `OPPORTUNITY_COLUMNS` entries |
| `backend/app/services/email_alert.py` | §3.2 config-driven recipients; §3.3 template guard; §4.2 queue and flush; §4.3 digest |
| `backend/app/jobs/award_check.py` | §3.2 drop hardcoded addresses; §4.2 queue/flush; §4.3 digest threshold |
| `backend/app/clients/base.py` | §5.2 single record path; §5.3 bounded `Retry-After`; §5.4 alert |
| `frontend/src/components/OpportunityModal.tsx` | §2.3 — show CRM sync state |
| `backend/tests/test_crm_adapter.py` | §1, §2 |
| `backend/tests/test_email_alert.py` | **new** — §3, §4 |
| `backend/tests/test_tsa_client.py` | **new** — §5 |

---

## 7. Acceptance criteria

- [ ] A non-numeric Monday board ID produces a clear configuration error, not a GraphQL syntax error
- [ ] With no board ID set, CRM sync logs "not configured" and every stage transition still succeeds
- [ ] Creating a CRM item sends identifiers as GraphQL variables, never interpolated into the document
- [ ] Updating an opportunity in Monday issues one HTTP request, not one per column
- [ ] A stage transition returns without waiting for Monday; a Monday outage does not slow the response
- [ ] The opportunity modal shows when a CRM push last succeeded or failed
- [ ] Changing the recipient list in Admin → Notifications changes where alerts are delivered
- [ ] Disabling an event in Admin → Notifications stops that alert being sent
- [ ] A template with a missing key logs a warning and still sends a readable message
- [ ] A 200-lead backfill opens one SMTP connection and sends one digest, not 200 messages
- [ ] A network failure against Tenders-SA creates exactly one `failed_api_calls` row
- [ ] A `Retry-After` header in HTTP-date format does not raise, and no sleep exceeds 120 seconds

---

## 8. Deferred scope

- A real outbound queue (Redis + worker). `ORICRED_REDIS_URL` is configured and unused;
  `BackgroundTasks` is sufficient at current volume and does not survive a restart.
- Pulling CRM changes back into Oricred. `pull_crm_activity` currently logs and discards
  (`sync.py:130-133`); two-way sync needs its own spec.
- Replacing the hardcoded Monday column IDs (`numbers`, `text`, `status_1`, `text7`) with a
  configurable field map. They are board-shape assumptions that will break on any new board.
- HTML email templates. Plain text is adequate for internal alerts.
