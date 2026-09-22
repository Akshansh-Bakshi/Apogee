"""POST /api/v1/capture: record one browsing event."""

from fastapi import APIRouter, status

from app.api.deps import DbSession
from app.api.errors import ErrorResponse
from app.schemas.capture import CaptureRequest, CaptureResponse
from app.services.ingestion import ingest_browsing_event

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
def capture(payload: CaptureRequest, session: DbSession) -> CaptureResponse:
    """Normalise the URL, find or create the user's page for it, and store one event.

    Every accepted request creates a new event (hence 201); ``page_created`` says whether the page
    is new or was reused. The stored URL is the *normalised* one: fragment and tracking parameters
    are dropped and the raw URL is never persisted.

    **Development-stage boundary, not an authenticated production endpoint.** The caller supplies
    `user_id` and `device_id` and nothing verifies who they are, so anyone who can reach this port
    can write events for any user. Authentication is deliberately deferred; do not expose this
    service beyond a trusted machine or network.
    """
    return ingest_browsing_event(session, payload)
