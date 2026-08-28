from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from app.api import router as api_router
from app.config import assert_production_safe, settings
from app.database import async_session, init_db
from app.models.user import User

logger = structlog.get_logger()


async def _bootstrap_admin() -> None:
    """Create the first administrator from the environment, if asked to.

    Requires BOTH ORICRED_BOOTSTRAP_ADMIN_EMAIL and
    ORICRED_BOOTSTRAP_ADMIN_PASSWORD, and only acts when no user exists. This
    replaces the previous behaviour, which seeded a fixed administrator account
    with a hardcoded password on any empty database whenever debug was on — and
    debug defaulted to on (see remediation-02 §2.4).

    For an interactive deployment prefer `python -m app.cli create-admin`,
    which never puts a password in the environment.
    """
    if not (settings.bootstrap_admin_email and settings.bootstrap_admin_password):
        return

    from app.services.auth import AuthService

    async with async_session() as db:
        if (await db.execute(select(User).limit(1))).first():
            return
        db.add(User(
            email=settings.bootstrap_admin_email.strip().lower(),
            name="Administrator",
            hashed_password=AuthService.hash_password(settings.bootstrap_admin_password),
            role="admin",
        ))
        await db.commit()
    logger.info("bootstrap_admin_created", email=settings.bootstrap_admin_email)


def _cors_origins() -> list[str]:
    """Browser origins allowed to call this API.

    Production serves the built SPA from this app's own static mount, so the
    empty default (same-origin only) is correct. ORICRED_CORS_ORIGINS exists for
    deployments that host the frontend separately.
    """
    configured = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
    if configured:
        return configured
    if settings.debug:
        return ["http://localhost:5173", "http://127.0.0.1:5173"]
    return []


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Before anything else touches a database or binds a port.
    assert_production_safe(settings)
    await init_db()
    await _bootstrap_admin()
    from app.jobs.scheduler import start_scheduler
    scheduler = await start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(api_router, prefix="/api")

app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="frontend")
