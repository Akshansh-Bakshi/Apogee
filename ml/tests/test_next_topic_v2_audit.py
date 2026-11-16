"""Tests for the label-blind pre-training gate."""
from datetime import datetime, timezone

import pytest

from ml.audit_next_topic_v2 import (
    duplicate_report, observable_profile, profiles_close, read_feature_projection,
)
from ml.synthetic_next_topic_v2 import FEATURES, extract_candidate_features, taxonomy


def scenario(sid, split, age=10, pages=1, family=None):
    _, topics = taxonomy()
    return {"scenario_id": sid, "split": split, "scenario_family": family or sid,
            "as_of": "2026-01-31T00:00:00+00:00",
            "topic_activity": {topic.id: {"distinct_pages": pages, "visits": pages+1,
                "last_seen_at": f"2026-01-{31-age:02}T00:00:00+00:00"} for topic in topics}}


def test_exact_and_near_duplicates_cross_split():
    rows = [scenario("a", "train"), scenario("b", "test"), scenario("c", "validation", age=15)]
    result = duplicate_report(rows)
    assert result["counts"]["exact_cross_split"] == 1
    assert result["counts"]["near_nonexact_cross_split"] == 2
    assert duplicate_report(rows) == result


def test_tolerances_require_every_topic_and_same_missing_mask():
    profile = observable_profile(scenario("a", "train"))
    assert profiles_close(profile, observable_profile(scenario("b", "test", age=17)))
    assert not profiles_close(profile, observable_profile(scenario("b", "test", age=18)))
    assert not profiles_close(profile, ((1, 2, None),) * len(profile))
    assert not profiles_close(profile, observable_profile(scenario("b", "test", pages=3)))


def test_feature_projection_excludes_targets_and_identifiers_from_model_fields(tmp_path):
    import json
    row = {key: None for key in FEATURES}
    row.update({key: "fixture" for key in ("scenario_id", "scenario_family", "split",
                "dataset_version", "feature_schema_version", "taxonomy_version")})
    row.update(synthetic=True, synthetic_usefulness_target=2, narrative="hidden", exploration_state="hidden")
    path = tmp_path / "fixture.jsonl"
    path.write_text(json.dumps(row)+"\n", encoding="utf-8")
    projected = read_feature_projection(path)[0]
    assert "synthetic_usefulness_target" not in projected
    assert "narrative" not in projected and "exploration_state" not in projected
    assert not set(FEATURES) & {"scenario_id", "scenario_family", "split", "synthetic_usefulness_target"}


def test_live_missing_visits_are_supported():
    _, topics = taxonomy()
    activity = {topic.id: {"distinct_pages": 0, "visits": 0, "last_seen_at": None} for topic in topics}
    activity["programming"]["distinct_pages"] = 1
    result = extract_candidate_features("programming", activity, datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert result["candidate_page_count"] == 1
    assert result["candidate_visit_count"] == 0
    assert result["candidate_recency_days"] is None


def test_profile_rejects_future_and_naive_cutoffs():
    row = scenario("a", "train")
    row["as_of"] = "2026-01-01T00:00:00+00:00"
    with pytest.raises(ValueError, match="future"):
        observable_profile(row)
    row["as_of"] = "2026-01-31T00:00:00"
    with pytest.raises(ValueError, match="naive"):
        observable_profile(row)
