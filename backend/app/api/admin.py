from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.filter_config import FilterConfig
from app.models.job_run import JobRun
from app.models.failed_api_call import FailedApiCall
from app.models.user import User
from app.api.auth import get_current_user
from app.schemas.auth import UserRead
from app.services.auth import AuthService
from app.services.qualification import QualificationService
from app.services.admin_config import (
    get_config, save_config, get_all_configs,
    CONFIG_DEFAULTS,
)

router = APIRouter(dependencies=[Depends(get_current_user)])


async def _require_admin(current_user: dict = Depends(get_current_user)):
    if current_user.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required")
    return current_user


# ── General settings ──

@router.get("/settings")
async def get_settings(db: AsyncSession = Depends(get_db), _=Depends(_require_admin)):
    from app.config import settings
    return {
        "app_name": settings.app_name,
        "debug": settings.debug,
        "jwt_expire_minutes": settings.jwt_expire_minutes,
    }


# ── Credentials ──

@router.get("/credentials")
async def get_credentials(db: AsyncSession = Depends(get_db), _=Depends(_require_admin)):
    config = await get_config("admin_credentials", db)
    masked = {}
    for k, v in config.items():
        if isinstance(v, str) and v and any(secret in k for secret in ("key", "password", "secret")):
            masked[k] = v[:4] + "****" if len(v) > 4 else "****"
        else:
            masked[k] = v
    return masked


@router.put("/credentials")
async def update_credentials(body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    config = await get_config("admin_credentials", db)
    for k in body:
        if body[k] and not (isinstance(body[k], str) and body[k].startswith("****") and k in config):
            config[k] = body[k]
        elif not body[k]:
            config[k] = ""
    await save_config("admin_credentials", config, current_user["user_id"], db)
    return {"status": "ok"}


# ── Filter config ──

@router.get("/filter-config")
async def get_filter_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == "qualification"))
    row = result.scalar_one_or_none()
    if row:
        return {"key": row.key, "value": row.value, "enabled": row.enabled}
    return {"key": "qualification", "value": QualificationService.default_config(), "enabled": True}


@router.put("/filter-config")
async def update_filter_config(config: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == "qualification"))
    row = result.scalar_one_or_none()
    if row:
        row.value = config
        row.updated_at = datetime.now(timezone.utc).isoformat()
        row.updated_by = current_user["user_id"]
    else:
        row = FilterConfig(key="qualification", value=config, enabled=True, updated_by=current_user["user_id"])
        db.add(row)
    await db.commit()
    QualificationService._config_cache = None
    return {"status": "ok"}


# ── Scrapers ──

@router.get("/sources")
async def get_sources(db: AsyncSession = Depends(get_db)):
    return await get_config("admin_sources", db)


@router.put("/sources")
async def update_sources(body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    await save_config("admin_sources", body, current_user["user_id"], db)
    return {"status": "ok"}


# ── Notifications ──

@router.get("/notifications")
async def get_notifications(db: AsyncSession = Depends(get_db)):
    return await get_config("admin_notifications", db)


@router.put("/notifications")
async def update_notifications(body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    await save_config("admin_notifications", body, current_user["user_id"], db)
    return {"status": "ok"}


# ── Scoring ──

@router.get("/scoring")
async def get_scoring(db: AsyncSession = Depends(get_db)):
    return await get_config("admin_scoring", db)


@router.put("/scoring")
async def update_scoring(body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    await save_config("admin_scoring", body, current_user["user_id"], db)
    return {"status": "ok"}


# ── Jobs ──

@router.get("/jobs")
async def get_jobs(db: AsyncSession = Depends(get_db)):
    return await get_config("admin_jobs", db)


@router.put("/jobs")
async def update_jobs(body: dict, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    await save_config("admin_jobs", body, current_user["user_id"], db)
    return {"status": "ok"}


@router.get("/jobs/history")
async def get_job_history(limit: int = 50, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(JobRun).order_by(JobRun.started_at.desc()).limit(limit)
    )
    rows = result.scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "job_name": r.job_name,
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "error": r.error,
                "items_processed": r.items_processed,
            }
            for r in rows
        ]
    }


@router.post("/jobs/{job_name}/trigger")
async def trigger_job(job_name: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    from app.jobs.scheduler import run_job
    handlers = {
        "discover_tenders": "app.jobs.discovery:discover_new_tenders",
        "check_awards": "app.jobs.award_check:check_awards_for_watching",
        "refresh_timing_model": "app.jobs.model_refresh:refresh_timing_model",
        "sync_crm": "app.jobs.crm_sync:sync_crm",
    }
    import_path = handlers.get(job_name)
    if not import_path:
        raise HTTPException(status_code=404, detail=f"Unknown job: {job_name}")

    import importlib
    module_path, func_name = import_path.split(":")
    module = importlib.import_module(module_path)
    handler = getattr(module, func_name)

    await run_job(job_name, handler)
    return {"status": "triggered", "job": job_name}


# ── Users ──

@router.get("/users", response_model=list[UserRead])
async def list_users(db: AsyncSession = Depends(get_db), _=Depends(_require_admin)):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("/users", response_model=UserRead)
async def create_user(body: dict, db: AsyncSession = Depends(get_db), _=Depends(_require_admin)):
    email = body.get("email", "").strip().lower()
    password = body.get("password", "")
    name = body.get("name", "").strip()
    role = body.get("role", "operator")

    if not email or not password or not name:
        raise HTTPException(status_code=400, detail="email, password, and name are required")

    existing = await db.execute(select(User).where(User.email == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="User with this email already exists")

    user = User(
        email=email,
        name=name,
        hashed_password=AuthService.hash_password(password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserRead)
async def update_user(user_id: str, body: dict, db: AsyncSession = Depends(get_db), _=Depends(_require_admin)):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if "name" in body and body["name"]:
        user.name = body["name"].strip()
    if "role" in body and body["role"] in ("admin", "operator", "manager", "viewer"):
        user.role = body["role"]
    if "password" in body and body["password"]:
        user.hashed_password = AuthService.hash_password(body["password"])
    if "email" in body and body["email"]:
        new_email = body["email"].strip().lower()
        if new_email != user.email:
            dup = await db.execute(select(User).where(User.email == new_email))
            if dup.scalar_one_or_none():
                raise HTTPException(status_code=409, detail="Email already in use")
            user.email = new_email

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, db: AsyncSession = Depends(get_db), current_user: dict = Depends(_require_admin)):
    if user_id == current_user["user_id"]:
        raise HTTPException(status_code=400, detail="Cannot delete yourself")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    await db.execute(delete(User).where(User.id == user_id))
    await db.commit()
    return {"status": "deleted"}


@router.get("/failed-api-calls")
async def get_failed_api_calls(limit: int = 50, resolved: bool | None = None, db: AsyncSession = Depends(get_db)):
    q = select(FailedApiCall).order_by(FailedApiCall.failed_at.desc())
    if resolved is not None:
        q = q.where(FailedApiCall.resolved == resolved)
    result = await db.execute(q.limit(limit))
    rows = result.scalars().all()
    return {
        "items": [
            {
                "id": str(r.id),
                "endpoint": r.endpoint,
                "error": r.error,
                "attempts": r.attempts,
                "failed_at": r.failed_at.isoformat(),
                "resolved": r.resolved,
            }
            for r in rows
        ]
    }
