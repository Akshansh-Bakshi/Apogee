"""Read-only, user-scoped as-of aggregation for the V2 offline feature contract."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping

from app.services.next_topic_features import extract_candidate_features
from app.services.topic_taxonomy import TOPICS


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value.utcoffset() is not None


def aggregate_topic_activity(*, user_id: str, as_of: datetime,
                             assignments: Iterable[Mapping], events: Iterable[Mapping],
                             topics=None) -> dict[str, dict]:
    """Consume already scoped page assignments and events; recheck owner and both time axes.

    assignment rows need page_id, user_id, topic_id, page_available_at and
    assignment_available_at; event rows need page_id, user_id, occurred_at and created_at.
    The current assignment may only be used historically if its availability time is known.
    """
    if not _aware(as_of):
        raise ValueError("as_of must be timezone-aware")
    if topics is None:
        topics = TOPICS
    activity = {topic.id: {"distinct_pages": 0, "visits": 0, "last_seen_at": None} for topic in topics}
    eligible_pages = {}
    for row in assignments:
        if str(row["user_id"]) != str(user_id):
            continue
        for key in ("page_available_at", "assignment_available_at"):
            stamp = row[key]
            if not _aware(stamp):
                raise ValueError(f"{key} must be timezone-aware")
        if row["page_available_at"] > as_of or row["assignment_available_at"] > as_of:
            continue
        topic_id = row.get("topic_id")
        if topic_id is None:  # missing embeddings / unclassified pages
            continue
        if topic_id not in activity:
            raise ValueError("unknown assigned topic")
        page_id = str(row["page_id"])
        if page_id in eligible_pages:
            raise ValueError("duplicate scoped page assignment")
        eligible_pages[page_id] = topic_id
        activity[topic_id]["distinct_pages"] += 1
    for event in events:
        if str(event["user_id"]) != str(user_id):
            continue
        occurred, created = event["occurred_at"], event["created_at"]
        if not _aware(occurred) or not _aware(created):
            raise ValueError("event timestamps must be timezone-aware")
        if occurred > as_of or created > as_of:
            continue
        topic_id = eligible_pages.get(str(event.get("page_id")))
        if topic_id is None:
            continue
        item = activity[topic_id]
        item["visits"] += 1
        if item["last_seen_at"] is None or occurred > item["last_seen_at"]:
            item["last_seen_at"] = occurred
    return activity


def candidate_features_for_user(*, user_id: str, as_of: datetime,
                                assignments: Iterable[Mapping], events: Iterable[Mapping],
                                topics=None) -> dict[str, dict]:
    if topics is None:
        topics = TOPICS
    activity = aggregate_topic_activity(user_id=user_id, as_of=as_of,
                                         assignments=assignments, events=events, topics=topics)
    return {topic.id: extract_candidate_features(topic.id, activity, as_of, topics)
            for topic in topics}
