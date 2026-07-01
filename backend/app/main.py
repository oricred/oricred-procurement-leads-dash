from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from sqlalchemy import select

from app.database import init_db, async_session
from app.models.user import User
from app.api import router as api_router


async def _ensure_admin_user():
    async with async_session() as db:
        result = await db.execute(select(User).limit(1))
        if result.first():
            return
    from app.services.auth import AuthService
    async with async_session() as db:
        db.add(User(
            email="admin@oricred.com", name="Admin",
            hashed_password=AuthService.hash_password("admin123"),
            role="admin",
        ))
        await db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await _ensure_admin_user()
    from app.jobs.scheduler import start_scheduler
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")

app.mount("/", StaticFiles(directory="../frontend/dist", html=True), name="frontend")
