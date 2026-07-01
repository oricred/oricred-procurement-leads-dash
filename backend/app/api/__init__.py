from fastapi import APIRouter

from app.api.opportunities import router as opportunities_router
from app.api.radar import router as radar_router
from app.api.watchlist import router as watchlist_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.admin import router as admin_router
from app.api.past_due import router as past_due_router
from app.api.contacts import router as contacts_router
from app.api.awards import router as awards_router
from app.api.tenders import router as tenders_router
from app.api.organizations import router as org_router
from app.api.categories import router as cat_router

router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(opportunities_router, prefix="/opportunities", tags=["opportunities"])
router.include_router(radar_router, prefix="/radar", tags=["radar"])
router.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])
router.include_router(past_due_router, prefix="/past-due", tags=["past-due"])
router.include_router(contacts_router, tags=["contacts"])
router.include_router(awards_router, tags=["awards"])
router.include_router(tenders_router, tags=["tenders"])
router.include_router(org_router, tags=["organizations"])
router.include_router(cat_router, tags=["categories"])


@router.get("/health")
async def health():
    return {"status": "ok"}
