from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from ml.generate_synthetic_next_topic import (
    DATASET_VERSION, EXPECTED_CANDIDATES, EXPECTED_SCENARIOS, FROZEN_TEST_FAMILIES,
    GENERATION_SEED, SPLIT_FAMILIES, generate_dataset, validate_dataset,
    validate_output_dir, write_outputs,
)


def manifests(scenarios: list[dict]) -> dict[str, list[str]]:
    return {
        split: [row["scenario_id"] for row in scenarios if row["split"] == split]
        for split in SPLIT_FAMILIES
    }


def test_generated_dataset_has_complete_balanced_candidate_sets() -> None:
    scenarios, candidates = generate_dataset()
    summary = validate_dataset(scenarios, candidates, manifests(scenarios))
    assert summary["scenario_count"] == EXPECTED_SCENARIOS
    assert summary["candidate_count"] == EXPECTED_CANDIDATES
    assert summary["candidate_topics_per_scenario"] == 8
    assert summary["candidate_coverage_by_topic"] == {
        topic: EXPECTED_SCENARIOS for topic in summary["candidate_coverage_by_topic"]
    }
    assert summary["label_distribution"] == {"0": 590, "1": 315, "2": 295}
    assert min(summary["strong_label_distribution_by_topic"].values()) > 0
    assert summary["graph_gap_candidates_labelled_not_useful"] > 0
    assert all(row["synthetic"] is True for row in candidates)
    assert all(row["dataset_version"] == DATASET_VERSION for row in candidates)


def test_generation_and_family_splits_are_deterministic() -> None:
    first = generate_dataset(GENERATION_SEED)
    second = generate_dataset(GENERATION_SEED)
    assert first == second
    scenarios, candidates = first
    family_splits: dict[str, set[str]] = {}
    for row in scenarios:
        family_splits.setdefault(row["scenario_family"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in family_splits.values())
    assert {row["scenario_family"] for row in scenarios if row["split"] == "test"} == set(
        FROZEN_TEST_FAMILIES
    )
    candidate_splits: dict[str, set[str]] = {}
    for row in candidates:
        candidate_splits.setdefault(row["scenario_id"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in candidate_splits.values())


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("duplicate_pair", "duplicate scenario-candidate pairs"),
        ("invalid_label", "target must be 0, 1, or 2"),
        ("missing_feature", "missing required feature"),
        ("duplicate_narrative", "duplicate scenario narratives"),
        ("class_imbalance", "class imbalance"),
    ],
)
def test_validation_rejects_invalid_data(mutation: str, message: str) -> None:
    scenarios, candidates = generate_dataset()
    scenarios = copy.deepcopy(scenarios)
    candidates = copy.deepcopy(candidates)
    if mutation == "duplicate_pair":
        candidates[-1]["scenario_id"] = candidates[0]["scenario_id"]
        candidates[-1]["candidate_topic_id"] = candidates[0]["candidate_topic_id"]
    elif mutation == "invalid_label":
        candidates[0]["synthetic_usefulness_target"] = 3
    elif mutation == "missing_feature":
        candidates[0]["candidate_page_count"] = None
    elif mutation == "duplicate_narrative":
        scenarios[1]["scenario_narrative"] = scenarios[0]["scenario_narrative"]
    elif mutation == "class_imbalance":
        for row in candidates:
            row["synthetic_usefulness_target"] = 0
    with pytest.raises(ValueError, match=message):
        validate_dataset(scenarios, candidates, manifests(scenarios))


def test_validation_rejects_family_leakage() -> None:
    scenarios, candidates = generate_dataset()
    split_rows = manifests(scenarios)
    moved = split_rows["train"].pop(0)
    split_rows["validation"].append(moved)
    with pytest.raises(ValueError, match="splits disagree|scenario-family leakage"):
        validate_dataset(scenarios, candidates, split_rows)


def test_written_outputs_validate_and_review_sample_is_blinded(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    write_outputs(first)
    write_outputs(second)
    assert validate_output_dir(first)["validation_status"] == "passed"
    assert sorted(path.name for path in first.iterdir()) == sorted(path.name for path in second.iterdir())
    for path in first.iterdir():
        assert path.read_bytes() == (second / path.name).read_bytes()

    with (first / "human-review-sample.csv").open(encoding="utf-8", newline="") as stream:
        review = list(csv.DictReader(stream))
    with (first / "human-review-sample-synthetic-label-key.csv").open(
        encoding="utf-8", newline=""
    ) as stream:
        key = list(csv.DictReader(stream))
    assert len(review) == len(key) == 30 * 8
    assert len({row["scenario_id"] for row in review}) == 30
    assert all(row["human_usefulness_target"] == "" for row in review)
    assert "synthetic_usefulness_target" not in review[0]
    assert all(row["synthetic_usefulness_target"] in {"0", "1", "2"} for row in key)

    test_manifest = json.loads((first / "split-test.json").read_text(encoding="utf-8"))
    assert test_manifest["frozen_before_training"] is True
    assert tuple(test_manifest["scenario_families"]) == FROZEN_TEST_FAMILIES
