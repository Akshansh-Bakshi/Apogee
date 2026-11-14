"""Local-only page search; the supplied user ID is a filter, not authentication."""

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.schemas.page_search import PageSearchRequest, PageSearchResponse
from app.services.page_search import page_search

router = APIRouter(tags=["search"])


@router.post("/search/pages", response_model=PageSearchResponse)
def search_pages(payload: PageSearchRequest, request: Request, session: DbSession) -> PageSearchResponse:
    return page_search(session, getattr(request.app.state, "embedding_encoder", None), payload)
