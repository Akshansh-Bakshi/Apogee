"""POST /api/v1/capture: record one browsing event."""

from fastapi import APIRouter, BackgroundTasks, Request, status

from app.api.deps import DbSession
from app.api.errors import ErrorResponse
from app.schemas.capture import CaptureRequest, CaptureResponse
from app.services.ingestion import ingest_browsing_event
from app.services.post_capture import embed_page_after_capture

router = APIRouter(tags=["capture"])


@router.post(
    "/capture",
    response_model=CaptureResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Record a browsing event (development stage, unauthenticated)",
    responses={
        404: {"model": ErrorResponse, "description": "No such device for this user"},
        409: {"model": ErrorResponse, "description": "Data conflict (rare race); safe to retry"},
        422: {"model": ErrorResponse, "description": "Invalid request"},
        503: {"model": ErrorResponse, "description": "Database temporarily unavailable"},
    },
)
def capture(
    payload: CaptureRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    session: DbSession,
) -> CaptureResponse:
    """Normalise the URL, find or create the user's page for it, and store one event.

    Every accepted request creates a new event (hence 201); ``page_created`` says whether the page
    is new or was reused. The stored URL is the *normalised* one: fragment and tracking parameters
    are dropped and the raw URL is never persisted.

    The optional ``content`` field carries the page's visible text (typically from the browser
    extension). When present it is cleaned and split into deterministic chunks, which replace any
    chunks stored from an earlier capture of the same page; ``content_processed``/``chunk_count``
    in the response reflect this. A plain revisit with no ``content`` behaves exactly as in Day 2
    and never touches stored chunks.

    **Development-stage boundary, not an authenticated production endpoint.** The caller supplies
    `user_id` and `device_id` and nothing verifies who they are, so anyone who can reach this port
    can write events for any user. Authentication is deliberately deferred; do not expose this
    service beyond a trusted machine or network.
    """
    result = ingest_browsing_event(session, payload)
    if result.content_processed and result.chunk_count:
        background_tasks.add_task(
            embed_page_after_capture,
            request.app.state.session_factory,
            result.page_id,
            request.app.state.embedding_encoder,
        )
    return result
