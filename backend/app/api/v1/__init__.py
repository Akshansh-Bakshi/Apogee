from fastapi import APIRouter

from app.api.v1.capture import router as capture_router
from app.api.v1.health import router as health_router
from app.api.v1.history import router as history_router
from app.api.v1.lexical_search import router as lexical_search_router
from app.api.v1.search import router as search_router
from app.api.v1.topics import router as topics_router
from app.api.v1.page_search import router as page_search_router

router = APIRouter(prefix="/api/v1")
router.include_router(health_router)
router.include_router(history_router)
router.include_router(capture_router)
router.include_router(search_router)
router.include_router(lexical_search_router)
router.include_router(topics_router)
router.include_router(page_search_router)
