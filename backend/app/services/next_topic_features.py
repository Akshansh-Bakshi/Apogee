"""Frozen V2 feature projection shared by offline generation and current inference."""
from datetime import datetime
from typing import Any, Mapping
from app.services.topic_taxonomy import TOPICS

FEATURE_VERSION = "apogee-next-topic-features-v2"
FEATURES = (
    "candidate_topic_id", "candidate_page_count", "candidate_visit_count",
    "candidate_recency_days", "candidate_is_observed", "observed_topic_breadth",
    "total_observed_pages", "total_observed_visits", "repeat_visit_ratio",
    "candidate_page_share", "candidate_visit_share", "candidate_prerequisite_count",
    "observed_prerequisite_count", "missing_prerequisite_count",
    "prerequisite_evidence_level", "candidate_is_graph_gap", "candidate_is_direct_extension",
)


def extract_candidate_features(topic_id: str, activity: Mapping[str, Mapping[str, Any]],
                               as_of: datetime, topics=None) -> dict[str, Any]:
    """Production-intended projection from user-scoped assignments and as-of visit aggregates.

    activity maps taxonomy topic IDs to distinct_pages, visits, and last_seen_at. Events after
    as_of must be filtered by the caller before aggregation; recency is clamped at zero.
    """
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of must be timezone-aware")
    if topics is None:
        topics = TOPICS
    graph = {topic.id: topic for topic in topics}
    if topic_id not in graph or set(activity) != set(graph):
        raise ValueError("activity and candidate must match the frozen taxonomy")
    row = activity[topic_id]
    pages, visits = row["distinct_pages"], row["visits"]
    last = row.get("last_seen_at")
    if pages < 0 or visits < 0:
        raise ValueError("page and visit counts must be nonnegative")
    if (visits == 0 and last is not None) or (visits > 0 and last is None):
        raise ValueError("last_seen_at must be present exactly when eligible visits exist")
    if last is not None and (last.tzinfo is None or last > as_of):
        raise ValueError("last_seen_at must be aware and no later than as_of")
    age = None if last is None else max(0, (as_of - last).total_seconds() / 86400)
    observed = {key for key, value in activity.items() if value["distinct_pages"] > 0}
    prereqs = graph[topic_id].prerequisites
    observed_prereqs = sum(parent in observed for parent in prereqs)
    total_pages = sum(value["distinct_pages"] for value in activity.values())
    total_visits = sum(value["visits"] for value in activity.values())
    if not prereqs:
        prereq_level = "not_applicable"
    elif observed_prereqs == 0:
        prereq_level = "none"
    elif observed_prereqs == len(prereqs):
        prereq_level = "complete"
    else:
        prereq_level = "partial"
    observed_dependents = [item.id for item in topics
                           if topic_id in item.prerequisites and item.id in observed]
    return {
        "candidate_topic_id": topic_id,
        "candidate_page_count": pages,
        "candidate_visit_count": visits,
        "candidate_recency_days": None if age is None else round(age, 4),
        "candidate_is_observed": pages > 0,
        "observed_topic_breadth": len(observed),
        "total_observed_pages": total_pages,
        "total_observed_visits": total_visits,
        "repeat_visit_ratio": round(max(0, total_visits-total_pages)/total_visits, 6) if total_visits else 0.0,
        "candidate_page_share": round(pages/total_pages, 6) if total_pages else 0.0,
        "candidate_visit_share": round(visits/total_visits, 6) if total_visits else 0.0,
        "candidate_prerequisite_count": len(prereqs),
        "observed_prerequisite_count": observed_prereqs,
        "missing_prerequisite_count": len(prereqs)-observed_prereqs,
        "prerequisite_evidence_level": prereq_level,
        "candidate_is_graph_gap": pages < 2 and bool(observed_dependents),
        "candidate_is_direct_extension": observed_prereqs > 0,
    }
