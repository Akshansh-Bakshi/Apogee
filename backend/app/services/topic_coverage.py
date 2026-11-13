"""Browsing evidence and explicit prerequisite suggestions; no learning or database writes."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from math import exp, log1p
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BrowsingEvent
from app.schemas.topic_coverage import TopicCoverageResponse, TopicEvidence, TopicRecommendation
from app.schemas.topics import TopicAssignmentsResponse
from app.services.topic_taxonomy import Topic
from app.services.topics import TopicAssigner, assign_user_pages

SPARSE_PAGE_LIMIT = 2  # a graph prerequisite with fewer than two captured pages can be suggested


def activity_index(pages: int, visits: int, last_seen_at: datetime | None,
                   observed_subtopics: int, total_subtopics: int, as_of: datetime) -> float:
    """Heuristic browsing activity in [0,1], never a learning or completion percentage."""
    if as_of.tzinfo is None or (last_seen_at is not None and last_seen_at.tzinfo is None):
        raise ValueError("timestamps must be timezone-aware")
    if pages < 0 or visits < 0 or observed_subtopics < 0 or total_subtopics < observed_subtopics:
        raise ValueError("evidence counts must be non-negative and consistent")
    page_part = min(log1p(pages) / log1p(5), 1)
    visit_part = min(log1p(visits) / log1p(8), 1)
    age_days = max(0, (as_of - last_seen_at).total_seconds() / 86400) if last_seen_at else None
    recency_part = exp(-age_days / 30) if age_days is not None and visits else 0
    breadth_part = observed_subtopics / total_subtopics if total_subtopics else 0
    return round(0.45 * page_part + 0.25 * visit_part + 0.20 * recency_part
                 + 0.10 * breadth_part, 4)


def _validate_graph(topics: tuple[Topic, ...]) -> None:
    by_id = {topic.id: topic for topic in topics}
    if len(by_id) != len(topics):
        raise ValueError("duplicate topic IDs")
    active: set[str] = set()
    seen: set[str] = set()

    def visit(topic_id: str) -> None:
        if topic_id in active:
            raise ValueError("cyclic prerequisite graph")
        if topic_id in seen:
            return
        active.add(topic_id)
        for prerequisite in by_id[topic_id].prerequisites:
            if prerequisite not in by_id:
                raise ValueError("unknown prerequisite")
            visit(prerequisite)
        active.remove(topic_id)
        seen.add(topic_id)

    for topic_id in by_id:
        visit(topic_id)


def recommendations(evidence: list[TopicEvidence], topics: tuple[Topic, ...]) -> list[TopicRecommendation]:
    """One strongest observed source per sparse prerequisite, ordered deterministically."""
    _validate_graph(topics)
    by_id = {item.topic_id: item for item in evidence}
    names = {topic.id: topic.name for topic in topics}
    candidates: list[tuple[int, int, str, str, TopicRecommendation]] = []
    for source in topics:
        source_evidence = by_id[source.id]
        if not source_evidence.distinct_pages:
            continue
        for prerequisite in source.prerequisites:
            target = by_id[prerequisite]
            if target.distinct_pages >= SPARSE_PAGE_LIMIT:
                continue
            rec = TopicRecommendation(
                topic_id=prerequisite, name=names[prerequisite],
                source_topic_id=source.id, source_topic_name=source.name,
                source_distinct_pages=source_evidence.distinct_pages,
                target_distinct_pages=target.distinct_pages, target_visits=target.visits,
                explanation=(
                    f"{names[prerequisite]} is a listed prerequisite of {source.name}. "
                    f"Observed evidence: {source_evidence.distinct_pages} captured pages for "
                    f"{source.name}; {target.distinct_pages} pages and {target.visits} visits "
                    f"for {names[prerequisite]}. This suggests a browsing gap, not a knowledge gap."
                ),
                source_page_ids=source_evidence.page_ids,
            )
            candidates.append((target.distinct_pages, -source_evidence.distinct_pages,
                               prerequisite, source.id, rec))
    candidates.sort(key=lambda row: row[:4])
    result: list[TopicRecommendation] = []
    used: set[str] = set()
    for _, _, target_id, _, rec in candidates:
        if target_id not in used:
            result.append(rec)
            used.add(target_id)
    return result


def build_coverage(assignments: TopicAssignmentsResponse,
                   events: list[tuple[UUID | None, datetime, UUID | None]],
                   topics: tuple[Topic, ...], as_of: datetime) -> TopicCoverageResponse:
    """Aggregate distinct assigned pages separately from visit events."""
    _validate_graph(topics)
    by_page = {item.page_id: item.topic_id for item in assignments.assignments
               if item.status == "suggested"}
    pages: dict[str, set[UUID]] = {topic.id: set() for topic in topics}
    for page_id, topic_id in by_page.items():
        if topic_id in pages:
            pages[topic_id].add(page_id)
    visit_counts: dict[str, int] = defaultdict(int)
    latest: dict[str, datetime] = {}
    unassigned_events = 0
    session_events = 0
    for page_id, occurred_at, session_id in events:
        if session_id is not None:
            session_events += 1
        topic_id = by_page.get(page_id)
        if topic_id not in pages:
            unassigned_events += 1
            continue
        visit_counts[topic_id] += 1
        if topic_id not in latest or occurred_at > latest[topic_id]:
            latest[topic_id] = occurred_at
    children: dict[str, set[str]] = {topic.id: set() for topic in topics}
    for topic in topics:
        for prerequisite in topic.prerequisites:
            children[prerequisite].add(topic.id)
    evidence = []
    for topic in topics:
        active_children = sum(bool(pages[child]) for child in children[topic.id])
        margins = [
            item.top_two_cosine_margin
            for item in assignments.assignments
            if item.status == "suggested"
            and item.topic_id == topic.id
            and item.top_two_cosine_margin is not None
        ]
        evidence.append(TopicEvidence(
            topic_id=topic.id, name=topic.name, distinct_pages=len(pages[topic.id]),
            visits=visit_counts[topic.id], last_seen_at=latest.get(topic.id),
            observed_subtopics=active_children, total_subtopics=len(children[topic.id]),
            activity_index=activity_index(
                len(pages[topic.id]), visit_counts[topic.id], latest.get(topic.id),
                active_children, len(children[topic.id]), as_of,
            ),
            page_ids=sorted(pages[topic.id]),
            mean_top_two_cosine_margin=(
                round(sum(margins) / len(margins), 4) if margins else None
            ),
        ))
    suggestions = recommendations(evidence, topics)
    return TopicCoverageResponse(
        taxonomy_version=assignments.taxonomy_version, as_of=as_of,
        total_pages=assignments.page_count, assigned_pages=assignments.suggested_count,
        unclassified_pages=assignments.unclassified_count,
        total_events=len(events), unassigned_events=unassigned_events,
        populated_session_events=session_events, topics=evidence,
        recommendations=suggestions,
        recommendation_status=("insufficient_evidence" if not any(item.distinct_pages for item in evidence)
                               else "suggestions_available" if suggestions else "no_graph_gaps"),
    )


def user_topic_coverage(session: Session, user_id: UUID,
                        assigner: TopicAssigner) -> TopicCoverageResponse:
    """Two user-filtered SELECTs; Stage A assignments are calculated in memory."""
    as_of = datetime.now(UTC)
    assignments = assign_user_pages(session, user_id, assigner)
    events = session.execute(
        select(BrowsingEvent.page_id, BrowsingEvent.occurred_at, BrowsingEvent.session_id)
        .where(BrowsingEvent.user_id == user_id)
        .order_by(BrowsingEvent.occurred_at, BrowsingEvent.id)
    ).all()
    return build_coverage(assignments, events, assigner.topics, as_of)
