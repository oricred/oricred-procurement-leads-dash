from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.organization import Organization

router = APIRouter()


@router.get("/organizations")
async def list_organizations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Organization.id, Organization.name)
        .order_by(Organization.name)
    )
    return [{"id": r.id, "name": r.name} for r in result.all()]
