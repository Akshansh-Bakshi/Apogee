from datetime import datetime, timedelta, timezone

import pytest

from ml.synthetic_next_topic_v2 import FEATURES, extract_candidate_features, generate, taxonomy, validate


def fixture_activity(topics):
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    return now, {topic.id: {"distinct_pages": 0, "visits": 0, "last_seen_at": None} for topic in topics}


def test_feature_extractor_matches_live_activity_and_graph_semantics():
    _, topics = taxonomy()
    now, activity = fixture_activity(topics)
    activity["programming"] = {"distinct_pages": 1, "visits": 2, "last_seen_at": now-timedelta(days=3)}
    activity["algorithms"] = {"distinct_pages": 1, "visits": 1, "last_seen_at": now-timedelta(days=1)}
    got = extract_candidate_features("programming", activity, now, topics)
    assert set(got) == set(FEATURES)
    assert got["candidate_is_graph_gap"] is True
    assert got["candidate_is_direct_extension"] is False
    assert got["candidate_recency_days"] == 3
    assert got["candidate_visit_count"] == 2
    assert got["total_observed_visits"] == 3


def test_feature_extractor_rejects_naive_or_future_timestamps():
    _, topics = taxonomy()
    now, activity = fixture_activity(topics)
    activity["programming"] = {"distinct_pages": 1, "visits": 1, "last_seen_at": now+timedelta(days=1)}
    with pytest.raises(ValueError):
        extract_candidate_features("programming", activity, now, topics)
    with pytest.raises(ValueError):
        extract_candidate_features("programming", activity, datetime(2026, 1, 1), topics)


def test_v2_generation_has_family_isolation_and_all_candidates():
    scenarios, candidates = generate()
    summary = validate(scenarios, candidates)
    assert (summary["scenario_count"], summary["candidate_count"]) == (360, 2880)
    assert summary["split_scenarios"] == {"train": 200, "validation": 60, "test": 100}
