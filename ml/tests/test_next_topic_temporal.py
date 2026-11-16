from datetime import datetime, timedelta, timezone

from ml.next_topic_temporal import aggregate_topic_activity, candidate_features_for_user

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def assignment(page, topic="programming", user="owner", available=NOW-timedelta(days=2)):
    return dict(page_id=page, topic_id=topic, user_id=user,
                page_available_at=available, assignment_available_at=available)


def event(page, occurred=NOW, created=NOW, user="owner"):
    return dict(page_id=page, user_id=user, occurred_at=occurred, created_at=created)


def test_independent_counts_cutoff_and_user_isolation():
    rows = [assignment("a"), assignment("b"), assignment("c", topic=None),
            assignment("foreign", user="other"), assignment("future", available=NOW+timedelta(days=1))]
    events = [event("a"), event("a"), event("b", occurred=NOW+timedelta(seconds=1)),
              event("b", created=NOW+timedelta(seconds=1)), event("foreign"), event("c")]
    result = candidate_features_for_user(user_id="owner", as_of=NOW,
                                          assignments=rows, events=events)
    programming = result["programming"]
    assert (programming["candidate_page_count"], programming["candidate_visit_count"]) == (2, 2)
    assert programming["candidate_recency_days"] == 0
    assert programming["total_observed_pages"] == 2
    assert programming["candidate_page_share"] == 1


def test_pages_without_visits_and_visits_greater_than_pages():
    rows = [assignment("a"), assignment("b")]
    empty = aggregate_topic_activity(user_id="owner", as_of=NOW, assignments=rows, events=[])
    assert (empty["programming"]["distinct_pages"], empty["programming"]["visits"],
            empty["programming"]["last_seen_at"]) == (2, 0, None)
    three = aggregate_topic_activity(user_id="owner", as_of=NOW, assignments=rows,
                                     events=[event("a"), event("a"), event("a")])
    assert (three["programming"]["distinct_pages"], three["programming"]["visits"]) == (2, 3)


def test_no_pages_or_visits_and_graph_evidence():
    features = candidate_features_for_user(user_id="owner", as_of=NOW, assignments=[], events=[])
    assert features["programming"]["total_observed_pages"] == 0
    assert features["programming"]["candidate_recency_days"] is None
    rows = [assignment("algorithm-page", topic="algorithms"), assignment("unclassified", topic=None)]
    features = candidate_features_for_user(user_id="owner", as_of=NOW, assignments=rows, events=[])
    assert features["programming"]["candidate_is_graph_gap"] is True
    assert features["algorithms"]["candidate_is_direct_extension"] is False
