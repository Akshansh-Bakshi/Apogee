from fastapi import APIRouter

from app.api.v1.capture import router as capture_router
from app.api.v1.health import router as health_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(capture_router)
