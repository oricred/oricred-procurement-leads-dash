# Remediation 02 — Security Hardening

**Date:** 2026-08-27
**Status:** Draft
**Findings closed:** C3, C4, C5 (critical), H7, H8 (high), M11 (medium)
**Assumes:** the Tenders-SA database password (C2) has already been rotated out of band

---

## Objective

Remove every insecure default the platform ships with, stop the Admin page from destroying the
credentials it displays, and make the production configuration fail loudly rather than run
quietly in an unsafe state.

The findings here share a shape: a convenience that is correct in development is also the
production default, and nothing checks. §2 introduces one guard that covers all of them.

---

## 1. Stop the Admin credentials form destroying secrets (C3)

### 1.1 Current state

`GET /admin/credentials` masks each secret by keeping its first four characters:

```python
# backend/app/api/admin.py:50-51
if isinstance(v, str) and v and any(secret in k for secret in ("key", "password", "secret")):
    masked[k] = v[:4] + "****" if len(v) > 4 else "****"
```

`CredentialsTab` loads that response straight into form state (`AdminPage.tsx:50`) and posts
the entire form back on save. The write handler tries to detect untouched fields:

```python
# backend/app/api/admin.py:61
if body[k] and not (isinstance(body[k], str) and body[k].startswith("****") and k in config):
    config[k] = body[k]
```

`"sk-l****"` does not start with `"****"`, so the guard never fires. Verified round-trip:

```
GET returns   -> sk-l****
PUT stores    -> sk-l****     the real key is gone
```

Editing the SMTP host to correct a typo destroys the Tenders-SA API key, the Monday.com key,
and the SMTP password in the same request. The environment-variable fallbacks in
`crm/sync.py:24-26` do not rescue it, because `"sk-l****"` is a non-empty value and wins.

Two secondary defects in the same handler:

- `any(secret in k for ...)` is case-sensitive, so a key named `API_KEY` or `SMTP_Password`
  would be returned in clear text.
- There is no way to tell "unset" from "set but hidden" in the UI.

### 1.2 Change — a sentinel the client cannot collide with

```python
# backend/app/services/admin_config.py

SECRET_SENTINEL = "•" * 12          # twelve bullet characters
SECRET_KEY_MARKERS = ("key", "password", "secret", "token")


def is_secret_field(name: str) -> bool:
    return any(marker in name.lower() for marker in SECRET_KEY_MARKERS)


def mask_secrets(config: dict) -> dict:
    """Replace every set secret with a fixed sentinel. Never leaks a prefix."""
    return {
        k: (SECRET_SENTINEL if is_secret_field(k) and isinstance(v, str) and v else v)
        for k, v in config.items()
    }


def merge_secrets(incoming: dict, stored: dict) -> dict:
    """Apply an incoming credentials payload over the stored one.

    A field equal to SECRET_SENTINEL means 'unchanged'. An empty string means
    'clear this credential'. Anything else is a new value.
    """
    merged = dict(stored)
    for k, v in incoming.items():
        if isinstance(v, str) and v == SECRET_SENTINEL:
            continue
        merged[k] = v
    return merged
```

The API handlers become thin:

```python
@router.get("/credentials")
async def get_credentials(db: AsyncSession = Depends(get_db)):
    return mask_secrets(await get_config("admin_credentials", db))


@router.put("/credentials")
async def update_credentials(
    body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(get_current_user)
):
    stored = await get_config("admin_credentials", db)
    await save_config("admin_credentials", merge_secrets(body, stored), current_user["user_id"], db)
    return {"status": "ok"}
```

The sentinel is a run of `U+2022 BULLET`, which no real API key or password contains, and
which renders as a plausible password mask in the existing `type="password"` input with no
frontend change required.

### 1.3 Frontend — make "clear" explicit

Because the sentinel is now indistinguishable from a real value in the input, the operator
needs a deliberate way to remove a credential. Add a small **Clear** control beside each
secret field that sets the form value to `""`:

```
  tsa_api_key
  ┌──────────────────────────────┐
  │ ••••••••••••                 │  [Clear]
  └──────────────────────────────┘
  Set · leave unchanged to keep the existing key
```

Non-secret fields (`tsa_base_url`, `monday_board_id`, `email_from`) are unaffected and stay
editable in clear text.

### 1.4 Test

```python
async def test_credential_round_trip_preserves_unedited_secrets(client, admin_token):
    await set_config("admin_credentials", {"tsa_api_key": "sk-live-real", "smtp_host": "old"})
    masked = (await client.get("/api/admin/credentials", headers=admin_token)).json()
    assert masked["tsa_api_key"] == SECRET_SENTINEL

    masked["smtp_host"] = "new"                       # operator edits one non-secret field
    await client.put("/api/admin/credentials", json=masked, headers=admin_token)

    stored = await get_config("admin_credentials", db)
    assert stored["tsa_api_key"] == "sk-live-real"    # <- the regression this test exists for
    assert stored["smtp_host"] == "new"


async def test_empty_string_clears_a_credential(client, admin_token):
    ...
```

---

## 2. Refuse to start with shipped defaults in production (C4, C5)

### 2.1 Current state

| Setting | Default | Risk |
|---------|---------|------|
| `debug` | `True` | Enables the seeded superuser below |
| `jwt_secret` | `"oricred-dev-secret-change-in-production"` | Published in the repo; anyone can forge `{"sub": ..., "role": "admin"}` |
| `session_secret` | same placeholder | Same |
| `tsa_database_url` | live production connection string | C2 |

`.env.example` — the file operators copy — sets `ORICRED_DEBUG=true`, and does not mention
`ORICRED_TSA_DATABASE_URL` at all, so the hardcoded default is what actually runs.

With `debug` true, `main.py:15-29` inserts an administrator on any database with no users:

```python
db.add(User(
    email="admin@oricred.com", name="Admin",
    hashed_password=AuthService.hash_password("admin123"),
    role="admin",
))
```

### 2.2 Change — safe defaults

```diff
# backend/app/config.py
- debug: bool = True
+ debug: bool = False

- tsa_database_url: str = "postgresql+asyncpg://tendersa_app:...@10.0.1.175:5432/tendersa_prod"
+ tsa_database_url: str = ""

- jwt_secret: str = "oricred-dev-secret-change-in-production"
+ jwt_secret: str = ""

- session_secret: str = "oricred-dev-secret-change-in-production"
+ session_secret: str = ""

+ cors_origins: str = ""      # see §3
+ bootstrap_admin_email: str = ""
+ bootstrap_admin_password: str = ""
```

`.env.example` gains `ORICRED_TSA_DATABASE_URL` and drops `ORICRED_DEBUG=true`; a commented
`# ORICRED_DEBUG=true  # local development only` documents it without arming it.

### 2.3 Change — a startup guard

```python
# backend/app/config.py

REQUIRED_IN_PRODUCTION = ("jwt_secret", "session_secret", "database_url", "tsa_database_url")

KNOWN_INSECURE_VALUES = {
    "oricred-dev-secret-change-in-production",
    "changeme",
    "",
}


def assert_production_safe(s: "Settings") -> None:
    """Refuse to serve traffic with a development configuration.

    Called from the FastAPI lifespan before the database is touched, so a
    misconfigured deployment fails at boot rather than on first request.
    """
    if s.debug:
        return
    problems = [
        f"ORICRED_{name.upper()} is unset or still a shipped default"
        for name in REQUIRED_IN_PRODUCTION
        if str(getattr(s, name)).strip() in KNOWN_INSECURE_VALUES
    ]
    if len(str(s.jwt_secret)) < 32 and s.jwt_secret not in KNOWN_INSECURE_VALUES:
        problems.append("ORICRED_JWT_SECRET must be at least 32 characters")
    if problems:
        raise RuntimeError(
            "Refusing to start in production mode:\n  - " + "\n  - ".join(problems)
        )
```

Wired in first, before `init_db`:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    assert_production_safe(settings)
    await init_db()
    await _ensure_admin_user()
    ...
```

### 2.4 Change — replace the seeded superuser

Delete `_ensure_admin_user` from `main.py`. Bootstrapping the first administrator becomes an
explicit action with an operator-supplied password:

```python
# backend/app/cli.py  (new)

async def create_admin(email: str, name: str, password: str) -> None:
    """Create the first administrator. Refuses to run if any user already exists."""
    if len(password) < 12:
        raise SystemExit("Password must be at least 12 characters")
    async with async_session() as db:
        if (await db.execute(select(User).limit(1))).first():
            raise SystemExit("A user already exists — use Admin -> Users to add more")
        db.add(User(
            email=email.strip().lower(), name=name,
            hashed_password=AuthService.hash_password(password), role="admin",
        ))
        await db.commit()
    print(f"Created administrator {email}")
```

```bash
python -m app.cli create-admin --email ops@oricred.com --name "Ops"
# password read from stdin via getpass, never from argv
```

For unattended first boot (containers, CI), the lifespan may still seed **only** when both
`bootstrap_admin_email` and `bootstrap_admin_password` are set and no user exists — an
explicit opt-in with an operator-chosen password, not a hardcoded one.

### 2.5 Test

```python
def test_production_mode_rejects_default_jwt_secret():
    s = Settings(debug=False, jwt_secret="oricred-dev-secret-change-in-production", ...)
    with pytest.raises(RuntimeError, match="ORICRED_JWT_SECRET"):
        assert_production_safe(s)


def test_production_mode_rejects_short_secret(): ...
def test_debug_mode_skips_the_guard(): ...
def test_create_admin_refuses_when_a_user_exists(): ...
```

---

## 3. Lock down CORS (H7)

### 3.1 Current state

```python
# backend/app/main.py:48-54
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    ...
)
```

There is no production branch, despite AGENTS.md stating "CORS: Wildcard in dev, locked down
in prod". Browsers reject `Access-Control-Allow-Origin: *` together with
`Access-Control-Allow-Credentials: true`, so the configuration is simultaneously unsafe in
intent and non-functional in effect.

### 3.2 Change

```python
# backend/app/main.py

def _cors_origins() -> list[str]:
    configured = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if configured:
        return configured
    if settings.debug:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return []          # same-origin only; the SPA is served from this app's static mount


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)
```

Production serves the built SPA from the same origin via the static mount at `main.py:58`, so
the empty default is correct and no `ORICRED_CORS_ORIGINS` value is needed for the standard
deployment. It exists for the case where the frontend is moved to a separate host.

Update the AGENTS.md "Key Conventions" line to describe what the code now does.

---

## 4. Stop caching authenticated API responses to disk (H8)

### 4.1 Current state

```typescript
// frontend/vite.config.ts:45-55
{
  urlPattern: /^\/api\/.*/i,
  handler: 'NetworkFirst',
  options: {
    cacheName: 'api-cache',
    expiration: { maxEntries: 200, maxAgeSeconds: 60 * 60 * 24 },
    ...
  },
}
```

Lead lists and supplier contact records — names, direct phone numbers and personal email
addresses of real people — are written into Cache Storage on the operator's machine. Logout
(`Layout.tsx:44`) clears `localStorage` only. The cache survives logout, is readable from
devtools, and persists across users on a shared device. For a platform holding third-party
personal data this is a POPIA exposure, not only a hygiene issue.

### 4.2 Change — allow-list reference data only

Reference endpoints hold no personal data and are what the offline banner actually needs to
keep the UI coherent:

```diff
- {
-   urlPattern: /^\/api\/.*/i,
-   handler: 'NetworkFirst',
-   options: { cacheName: 'api-cache', expiration: { maxEntries: 200, ... } },
- },
+ {
+   // Reference data only. Never cache leads, contacts, opportunities or awards —
+   // those responses contain personal data and must not persist after logout.
+   urlPattern: /^\/api\/(organizations|categories|tenders\/provinces)$/i,
+   handler: 'StaleWhileRevalidate',
+   options: {
+     cacheName: 'api-reference',
+     expiration: { maxEntries: 10, maxAgeSeconds: 60 * 60 * 24 },
+     cacheableResponse: { statuses: [200] },
+   },
+ },
```

`cacheableResponse.statuses` drops `0`, which was allowing opaque responses into the cache.

### 4.3 Change — clear caches on logout

```typescript
// frontend/src/components/Layout.tsx

const handleLogout = async () => {
  localStorage.removeItem('token');
  queryClient.clear();
  if ('caches' in window) {
    await Promise.all(
      (await caches.keys())
        .filter((k) => k.startsWith('api-'))
        .map((k) => caches.delete(k)),
    );
  }
  navigate('/login');
};
```

The same clearing must run on the 401 interceptor path in `api.ts:20-23`, which is the other
way a session ends.

### 4.4 Consequence to accept

The offline banner now means "the app shell is available, live data is not", which is the
honest state. The banner copy changes from "showing cached data" to "you are offline —
reconnect to load leads".

---

## 5. Apply the admin role check to admin reads (M11)

### 5.1 Current state

`_require_admin` is applied to every write handler, but seven read handlers inherit only
router-level authentication:

| Line | Endpoint | Exposes |
|------|----------|---------|
| 72 | `GET /admin/filter-config` | Qualification rules |
| 99 | `GET /admin/sources` | Source portal configuration |
| 112 | `GET /admin/notifications` | Alert recipients |
| 125 | `GET /admin/scoring` | Scoring weights |
| 138 | `GET /admin/jobs` | Job schedule |
| 151 | `GET /admin/jobs/history` | Job run history and error text |
| 273 | `GET /admin/failed-api-calls` | Dead-letter queue, including request parameters |

Any authenticated `viewer` or `operator` can read all of it. The frontend hides the Admin nav
item by role (`Layout.tsx:70`) but the route is reachable by URL.

### 5.2 Change

Move the check to the router so it cannot be forgotten on a new endpoint:

```diff
- router = APIRouter(dependencies=[Depends(get_current_user)])
-
-
- async def _require_admin(current_user: dict = Depends(get_current_user)):
-     if current_user.get("role") != "admin":
-         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
-     return current_user
+ async def require_admin(current_user: dict = Depends(get_current_user)) -> dict:
+     if current_user.get("role") != "admin":
+         raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
+     return current_user
+
+
+ router = APIRouter(dependencies=[Depends(require_admin)])
```

Handlers that need the acting user's ID keep `current_user: dict = Depends(require_admin)`;
`Depends` caches per request, so the check runs once. Every `_=Depends(_require_admin)`
parameter that exists only to force the check can be deleted.

### 5.3 Guard it with a test

```python
@pytest.mark.parametrize("path", [
    "/api/admin/settings", "/api/admin/credentials", "/api/admin/filter-config",
    "/api/admin/sources", "/api/admin/notifications", "/api/admin/scoring",
    "/api/admin/jobs", "/api/admin/jobs/history", "/api/admin/failed-api-calls",
    "/api/admin/users",
])
async def test_every_admin_route_rejects_non_admin(client, operator_token, path):
    assert (await client.get(path, headers=operator_token)).status_code == 403
```

Parametrise from the router's own route table rather than a hand-written list, so a new
endpoint is covered automatically:

```python
ADMIN_GET_PATHS = [
    r.path for r in admin_router.routes if "GET" in getattr(r, "methods", set())
]
```

### 5.4 Frontend

`AdminPage` should render a 403 state rather than a broken page when a non-admin reaches
`/admin` by URL. Guard the route in `App.tsx` with the role from the existing `['me']` query
and redirect to `/discover`.

---

## 6. Files to change

| File | Change |
|------|--------|
| `backend/app/services/admin_config.py` | §1.2 — `SECRET_SENTINEL`, `mask_secrets`, `merge_secrets`, `is_secret_field` |
| `backend/app/api/admin.py` | §1.2 handlers; §5.2 router-level `require_admin` |
| `backend/app/config.py` | §2.2 safe defaults; §2.3 `assert_production_safe` |
| `backend/app/main.py` | §2.3 guard in lifespan; §2.4 remove `_ensure_admin_user`; §3.2 CORS |
| `backend/app/cli.py` | **new** — §2.4 `create-admin` |
| `.env.example` | §2.2 — add `ORICRED_TSA_DATABASE_URL`, disarm `ORICRED_DEBUG` |
| `frontend/vite.config.ts` | §4.2 — replace the `/api/` cache rule |
| `frontend/src/components/Layout.tsx` | §4.3 clear caches on logout; §4.4 banner copy |
| `frontend/src/services/api.ts` | §4.3 — clear caches on the 401 path |
| `frontend/src/pages/AdminPage.tsx` | §1.3 — Clear control per secret field |
| `frontend/src/App.tsx` | §5.4 — role guard on `/admin` |
| `AGENTS.md` | §3.2 — correct the CORS convention line |
| `backend/tests/test_admin_credentials.py` | **new** — §1.4 |
| `backend/tests/test_config_guard.py` | **new** — §2.5 |
| `backend/tests/test_admin_rbac.py` | **new** — §5.3 |

---

## 7. Acceptance criteria

- [ ] Editing one non-secret field on the Admin credentials page leaves every other credential intact
- [ ] `GET /admin/credentials` never returns any part of a real secret, including its first four characters
- [ ] Submitting an empty string for a secret clears it; submitting the sentinel leaves it unchanged
- [ ] A field named `API_KEY` or `SMTP_Password` is masked (case-insensitive detection)
- [ ] `ORICRED_DEBUG=false` with a default `jwt_secret` refuses to start, naming the offending variable
- [ ] `ORICRED_DEBUG=false` with an unset `tsa_database_url` refuses to start
- [ ] No code path creates a user with a hardcoded password
- [ ] `python -m app.cli create-admin` requires a 12-character password and refuses when a user exists
- [ ] A cross-origin `fetch` with credentials from an unlisted origin is rejected in production mode
- [ ] After logout, `caches.keys()` contains no entry holding lead or contact data
- [ ] No `/api/` response other than the three reference endpoints appears in Cache Storage
- [ ] All ten admin endpoints return 403 for an `operator` and a `viewer` token
- [ ] A non-admin navigating to `/admin` by URL is redirected rather than shown a broken page

---

## 8. Deferred scope

- Refresh tokens and server-side revocation. Tokens remain 24-hour bearer tokens in
  `localStorage`; moving to httpOnly cookies is a larger change that needs its own spec.
- Rate limiting on `POST /auth/login`. Currently unbounded; worth a follow-up.
- Per-object authorisation. Every authenticated user can read and modify every opportunity and
  contact. Acceptable for a single-team internal tool today, and should be revisited before
  any external user is given an account.
- Audit logging of admin configuration changes beyond the existing `updated_by` field.
