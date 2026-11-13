"""Bounded, user-scoped browsing timeline using existing provisional topic assignments."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.models import BrowsingEvent, Page
from app.schemas.history import HistoryEvent, HistoryQuery, HistoryResponse, HistoryTopicOption
from app.schemas.topics import TopicAssignmentsResponse
from app.services.topic_taxonomy import TAXONOMY_VERSION
from app.services.topics import TopicAssigner, assign_user_pages

TOPIC_FILTER_SCAN_LIMIT = 500


def assemble_history(
    rows: list[Any],
    assignments: TopicAssignmentsResponse,
    query: HistoryQuery,
    *,
    scan_truncated: bool,
) -> HistoryResponse:
    """Attach provisional topics, retain deterministic order, and apply an optional topic filter."""
    by_page = {item.page_id: item for item in assignments.assignments}
    output: list[HistoryEvent] = []
    omitted_timestamps = 0
    # Database ordering is authoritative; sorting again makes the tie-breaker explicit for tests
    # and protects callers that provide materialized rows.
    ordered = sorted(
        rows,
        key=lambda row: (
            row.occurred_at is not None,
            row.occurred_at if row.occurred_at is not None else query.start_at,
            row.event_id,
        ),
        reverse=True,
    )
    for row in ordered:
        if row.occurred_at is None:
            omitted_timestamps += 1
            continue
        assignment = by_page.get(row.page_id)
        if query.topic_id is not None and (
            assignment is None
            or assignment.status != "suggested"
            or assignment.topic_id != query.topic_id
        ):
            continue
        if assignment is None:
            topic_status, topic_id, score, margin, reason = (
                "unavailable", None, None, None, "missing_page",
            )
        else:
            topic_status = assignment.status
            topic_id = assignment.topic_id
            score = assignment.similarity
            margin = assignment.top_two_cosine_margin
            reason = assignment.reason
        output.append(
            HistoryEvent(
                event_id=row.event_id,
                occurred_at=row.occurred_at,
                page_id=row.page_id,
                canonical_url=row.page_canonical_url or row.event_url,
                title=row.page_title or row.event_title,
                domain=row.page_domain or row.event_domain,
                topic_status=topic_status,
                provisional_topic_id=topic_id,
                topic_cosine_similarity=score,
                top_two_cosine_margin=margin,
                topic_reason=reason,
            )
        )
    more_matches = len(output) > query.limit
    output = output[: query.limit]
    return HistoryResponse(
        taxonomy_version=TAXONOMY_VERSION,
        start_at=query.start_at,
        end_at=query.end_at,
        topic_filter=query.topic_id,
        limit=query.limit,
        candidate_event_count=len(rows),
        result_count=len(output),
        omitted_invalid_timestamp_count=omitted_timestamps,
        truncated=scan_truncated or more_matches,
        topics=[HistoryTopicOption(id=topic.id, name=topic.name) for topic in assignments.topics],
        events=output,
    )


def get_user_history(
    session: Session, assigner: TopicAssigner, query: HistoryQuery
) -> HistoryResponse:
    """Run at most one bounded event query and one batched page-assignment query."""
    event = BrowsingEvent
    page = Page
    scan_limit = TOPIC_FILTER_SCAN_LIMIT if query.topic_id is not None else query.limit
    statement = (
        select(
            event.id.label("event_id"),
            event.occurred_at,
            event.page_id,
            event.url.label("event_url"),
            event.title.label("event_title"),
            event.domain.label("event_domain"),
            page.canonical_url.label("page_canonical_url"),
            page.title.label("page_title"),
            page.domain.label("page_domain"),
        )
        .select_from(event)
        .outerjoin(
            page,
            and_(page.id == event.page_id, page.user_id == query.user_id),
        )
        .where(event.user_id == query.user_id)
    )
    if query.start_at is not None:
        statement = statement.where(event.occurred_at >= query.start_at)
    if query.end_at is not None:
        statement = statement.where(event.occurred_at < query.end_at)
    rows = session.execute(
        statement.order_by(event.occurred_at.desc(), event.id.desc()).limit(scan_limit + 1)
    ).all()
    scan_truncated = len(rows) > scan_limit
    rows = rows[:scan_limit]
    page_ids = {row.page_id for row in rows if row.page_id is not None}
    assignments = assign_user_pages(
        session, query.user_id, assigner, page_ids=page_ids
    )
    return assemble_history(rows, assignments, query, scan_truncated=scan_truncated)
