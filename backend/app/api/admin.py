from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.filter_config import FilterConfig
from app.services.qualification import QualificationService

router = APIRouter()


@router.get("/filter-config")
async def get_filter_config(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == "qualification"))
    row = result.scalar_one_or_none()
    if row:
        return {"key": row.key, "value": row.value, "enabled": row.enabled}
    return {"key": "qualification", "value": QualificationService.default_config(), "enabled": True}


@router.put("/filter-config")
async def update_filter_config(config: dict, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(FilterConfig).where(FilterConfig.key == "qualification"))
    row = result.scalar_one_or_none()
    if row:
        row.value = config
    else:
        row = FilterConfig(key="qualification", value=config, enabled=True)
        db.add(row)
    await db.commit()
    return {"status": "ok"}
