"""GET /api/v1/history: bounded local browsing-event timeline."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from app.api.deps import DbSession
from app.schemas.history import HistoryQuery, HistoryResponse
from app.services.history import get_user_history

router = APIRouter(tags=["history"])


@router.get(
    "/history",
    response_model=HistoryResponse,
    summary="Recorded browsing events with provisional topics",
)
def history(
    query: Annotated[HistoryQuery, Query()],
    request: Request,
    session: DbSession,
) -> HistoryResponse:
    """The supplied user ID scopes records but does not authenticate the caller."""
    return get_user_history(session, request.app.state.topic_assigner, query)
