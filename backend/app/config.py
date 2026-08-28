from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "Oricred"
    # Development conveniences are gated on this flag, so it must default to the
    # safe value. See assert_production_safe() below.
    debug: bool = False

    tsa_api_key: str = ""
    tsa_base_url: str = "https://api.tenders-sa.org"
    # No default: this is a live third-party database and its credentials must
    # come from the environment. Set ORICRED_TSA_DATABASE_URL.
    tsa_database_url: str = ""

    database_url: str = f"sqlite+aiosqlite:///{Path(__file__).resolve().parent.parent / 'oricred.db'}"
    redis_url: str = ""

    # No defaults: a shipped signing key is a published signing key. Anyone
    # holding it can mint a token for any user with any role.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    email_from: str = "noreply@oricred.com"
    email_from_name: str = "Oricred Platform"

    monday_api_key: str = ""

    session_secret: str = ""

    # Logging. sql_echo is deliberately independent of debug: echoing every
    # statement is what filled the production disk, so it must never be a
    # side effect of turning debug on. See app/logging_config.py.
    log_level: str = "INFO"
    log_json: bool = False
    sql_echo: bool = False

    # Comma-separated allowed browser origins. Empty means same-origin only,
    # which is correct for the standard deployment where FastAPI serves the SPA.
    cors_origins: str = ""

    # Optional unattended first-boot administrator. Both must be set, and only
    # takes effect when no user exists. Prefer `python -m app.cli create-admin`.
    bootstrap_admin_email: str = ""
    bootstrap_admin_password: str = ""

    model_config = {"env_prefix": "ORICRED_", "env_file": "../.env"}

    @property
    def sync_database_url(self) -> str:
        return self.database_url.replace("+aiosqlite", "")


settings = Settings()


# ── Production configuration guard ──

# Settings that have no safe default and must be supplied by the environment
# before this application serves traffic.
REQUIRED_IN_PRODUCTION = (
    "jwt_secret",
    "session_secret",
    "database_url",
    "tsa_database_url",
)

# Values that mean "nobody configured this". Includes the placeholders that
# earlier versions shipped as defaults, so an old .env that copied them forward
# is still rejected.
KNOWN_INSECURE_VALUES = frozenset({
    "",
    "changeme",
    "oricred-dev-secret-change-in-production",
    "generate-a-random-secret",
    "generate-another-random-secret",
})

MIN_SECRET_LENGTH = 32


def assert_production_safe(s: Settings) -> None:
    """Refuse to serve traffic with a development configuration.

    Called from the FastAPI lifespan before the database is touched, so a
    misconfigured deployment fails at boot with a readable message rather than
    running quietly with a signing key that is published in the repository.

    No-op when debug is on.
    """
    if s.debug:
        return

    problems: list[str] = []
    for name in REQUIRED_IN_PRODUCTION:
        value = str(getattr(s, name)).strip()
        if value in KNOWN_INSECURE_VALUES:
            problems.append(
                f"ORICRED_{name.upper()} is unset or still set to a shipped default"
            )

    for name in ("jwt_secret", "session_secret"):
        value = str(getattr(s, name)).strip()
        if value and value not in KNOWN_INSECURE_VALUES and len(value) < MIN_SECRET_LENGTH:
            problems.append(
                f"ORICRED_{name.upper()} must be at least {MIN_SECRET_LENGTH} characters "
                f"(got {len(value)})"
            )

    if problems:
        raise RuntimeError(
            "Refusing to start in production mode (ORICRED_DEBUG is false):\n  - "
            + "\n  - ".join(problems)
            + "\n\nSet these in the environment, or set ORICRED_DEBUG=true for local development."
        )
