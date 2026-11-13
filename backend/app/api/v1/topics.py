"""Read-only, user-scoped provisional topic suggestions."""

from uuid import UUID

from fastapi import APIRouter, Request

from app.api.deps import DbSession
from app.schemas.topics import TopicAssignmentsResponse
from app.schemas.topic_coverage import TopicCoverageResponse
from app.services.topic_coverage import user_topic_coverage
from app.services.topics import assign_user_pages

router = APIRouter(tags=["topics"])


@router.get(
    "/topics/assignments",
    response_model=TopicAssignmentsResponse,
    summary="Provisional zero-shot topics for one user's captured pages",
)
def topic_assignments(user_id: UUID, request: Request, session: DbSession) -> TopicAssignmentsResponse:
    """The caller-supplied user ID is a scope filter, not authentication. Keep the API local."""
    return assign_user_pages(session, user_id, request.app.state.topic_assigner)


@router.get("/topics/coverage", response_model=TopicCoverageResponse,
            summary="Observed browsing evidence and prerequisite suggestions")
def topic_coverage(user_id: UUID, request: Request, session: DbSession) -> TopicCoverageResponse:
    """Read-only local analytics; user_id scopes data but does not authenticate the caller."""
    return user_topic_coverage(session, user_id, request.app.state.topic_assigner)
