import json
from pathlib import Path

import pytest

from ml.train_next_topic_v2 import dcg, load_trusted_artifact, matrix, metrics, pipeline, train
from ml.synthetic_next_topic_v2 import FEATURES


def test_dcg_and_scenario_ranking_math():
    assert dcg([2, 0]) == 3
    rows = [{"scenario_id": "s", "scenario_family": "f", "candidate_topic_id": f"topic-{i}",
             "synthetic_usefulness_target": 2 if i == 0 else 0} for i in range(8)]
    result = metrics(rows, [8-i for i in range(8)])
    assert result["overall"] == {"ndcg@3": 1.0, "ndcg@5": 1.0, "precision@3": 0.333333}
    assert metrics(rows, [0]*8)["per_scenario"][0]["top_topic"] == "topic-0"


def test_model_input_projection_requires_frozen_fields():
    row = {field: 0 for field in FEATURES}
    row["candidate_topic_id"] = "programming"
    row["prerequisite_evidence_level"] = "not_applicable"
    row["candidate_recency_days"] = None
    row["synthetic_usefulness_target"] = 2
    row["split"] = "test"
    assert matrix([row]).shape == (1, len(FEATURES))
    assert matrix([row])[0, FEATURES.index("candidate_recency_days")] != row["synthetic_usefulness_target"]
    del row["candidate_page_count"]
    with pytest.raises(ValueError, match="missing frozen model feature"):
        matrix([row])


def test_pipeline_is_seeded_and_loader_rejects_outside_paths(tmp_path: Path):
    assert pipeline(0.1).named_steps["classifier"].random_state == 20261116
    trusted = tmp_path/"trusted"
    trusted.mkdir()
    outside = tmp_path/"outside.joblib"
    outside.write_bytes(b"not a model")
    with pytest.raises(ValueError, match="trusted local"):
        load_trusted_artifact(outside, trusted)


def test_existing_sealed_test_report_cannot_be_overwritten(tmp_path: Path):
    output = tmp_path/"model"
    output.mkdir()
    (output/"evaluation.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileExistsError, match="already evaluated"):
        train(tmp_path/"missing-data", output)


def test_loader_rejects_mismatched_runtime_before_unpickling(tmp_path: Path):
    trusted = tmp_path/"trusted"
    trusted.mkdir()
    artifact = trusted/"model.joblib"
    artifact.write_bytes(b"not a model")
    (trusted/"evaluation.json").write_text(json.dumps({
        "versions": {"python": "0.0.0", "scikit_learn": "0.0.0"},
        "model_sha256": "unused",
    }), encoding="utf-8")
    with pytest.raises(ValueError, match="Python minor version"):
        load_trusted_artifact(artifact, trusted)
