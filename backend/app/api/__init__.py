from fastapi import APIRouter, Depends

from app.api.auth import get_current_user
from app.api.auth import router as auth_router
from app.api.admin import router as admin_router
from app.api.awards import router as awards_router
from app.api.categories import router as cat_router
from app.api.contacts import router as contacts_router
from app.api.dashboard import router as dashboard_router
from app.api.historical_contacts import router as historical_contacts_router
from app.api.leads import router as leads_router
from app.api.opportunities import router as opportunities_router
from app.api.organizations import router as org_router
from app.api.past_due import router as past_due_router
from app.api.radar import router as radar_router
from app.api.tenders import router as tenders_router
from app.api.stats import router as stats_router
from app.api.watchlist import router as watchlist_router

authenticated = [Depends(get_current_user)]
router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(opportunities_router, prefix="/opportunities", tags=["opportunities"], dependencies=authenticated)
router.include_router(leads_router, dependencies=authenticated)
router.include_router(radar_router, prefix="/radar", tags=["radar"], dependencies=authenticated)
router.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"], dependencies=authenticated)
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"], dependencies=authenticated)
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(stats_router, prefix="/stats", tags=["stats"], dependencies=authenticated)
router.include_router(past_due_router, prefix="/past-due", tags=["past-due"], dependencies=authenticated)
router.include_router(contacts_router, tags=["contacts"], dependencies=authenticated)
router.include_router(awards_router, tags=["awards"], dependencies=authenticated)
router.include_router(tenders_router, tags=["tenders"], dependencies=authenticated)
router.include_router(historical_contacts_router, dependencies=authenticated)
router.include_router(org_router, tags=["organizations"], dependencies=authenticated)
router.include_router(cat_router, tags=["categories"], dependencies=authenticated)


@router.get("/health")
async def health():
    return {"status": "ok"}
