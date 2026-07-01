from fastapi import APIRouter

from app.api.opportunities import router as opportunities_router
from app.api.radar import router as radar_router
from app.api.watchlist import router as watchlist_router
from app.api.auth import router as auth_router
from app.api.dashboard import router as dashboard_router
from app.api.admin import router as admin_router

router = APIRouter()
router.include_router(auth_router, prefix="/auth", tags=["auth"])
router.include_router(opportunities_router, prefix="/opportunities", tags=["opportunities"])
router.include_router(radar_router, prefix="/radar", tags=["radar"])
router.include_router(watchlist_router, prefix="/watchlist", tags=["watchlist"])
router.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
router.include_router(admin_router, prefix="/admin", tags=["admin"])


@router.get("/health")
async def health():
    return {"status": "ok"}
