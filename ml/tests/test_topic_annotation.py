from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import uuid4

import pytest

from ml.prepare_topic_annotation import (
    CONTENT_ACKNOWLEDGEMENT, MAX_EXCERPT, build_rows, clean_metadata, main as export_main,
)
from ml.topic_annotation import (
    ANNOTATION_FIELDS, PREDICTION_FIELDS, TAXONOMY_VERSION, TOPIC_IDS,
    evaluate, read_csv, validate_annotations, validate_predictions, write_report,
)


def annotation(page_id: str, *, topic: str = "", status: str = "unreviewed",
               reviewer: str = "", notes: str = "") -> dict[str, str]:
    return {
        "taxonomy_version": TAXONOMY_VERSION, "page_id": page_id,
        "safe_title": "Title", "safe_domain": "example.com", "content_excerpt": "",
        "human_topic": topic, "review_status": status, "reviewer_id": reviewer,
        "reviewer_notes": notes,
    }


def prediction(page_id: str, topic: str | None = "algorithms") -> dict[str, str]:
    return {
        "taxonomy_version": TAXONOMY_VERSION, "page_id": page_id,
        "prediction_status": "suggested" if topic else "unclassified",
        "predicted_topic": topic or "", "cosine_similarity": "0.7" if topic else "",
        "abstention_reason": "" if topic else "missing_embeddings", "embedding_count": "2" if topic else "0",
    }


def payload(page_ids: list[str]) -> dict:
    topics = [
        {"id": topic, "name": topic.title(), "description": f"Description for {topic}.",
         "prerequisites": []}
        for topic in TOPIC_IDS
    ]
    return {
        "taxonomy_version": TAXONOMY_VERSION, "topics": topics,
        "assignments": [
            {"page_id": page_id, "status": "suggested", "topic_id": "algorithms",
             "similarity": 0.61, "reason": None, "embedding_count": 2}
            for page_id in page_ids
        ],
    }


def test_export_is_blinded_and_prediction_is_separate() -> None:
    page_id = str(uuid4())
    annotations, predictions, taxonomy = build_rows(
        payload([page_id]),
        {page_id: {"safe_title": "Benign title", "safe_domain": "example.com",
                   "content_excerpt": ""}},
    )
    assert annotations[0]["human_topic"] == ""
    assert annotations[0]["review_status"] == "unreviewed"
    assert "predicted_topic" not in annotations[0]
    assert predictions[0]["predicted_topic"] == "algorithms"
    assert len(taxonomy) == len(TOPIC_IDS)
    assert CONTENT_ACKNOWLEDGEMENT == "I APPROVE LOCAL PAGE EXCERPTS"


def test_metadata_cleanup_and_excerpt_limit() -> None:
    assert clean_metadata("  a\n b  ", 20) == "a b"
    assert len(clean_metadata("x" * 500, MAX_EXCERPT)) == MAX_EXCERPT


def test_annotation_validation_requires_explicit_completed_state() -> None:
    page_id = str(uuid4())
    assert validate_annotations([annotation(page_id)]) == {"unreviewed": 1}
    assert validate_annotations([
        annotation(page_id, topic="algorithms", status="labeled", reviewer="r1")
    ]) == {"labeled": 1}
    with pytest.raises(ValueError, match="one valid topic"):
        validate_annotations([annotation(page_id, topic="two,topics", status="labeled", reviewer="r1")])
    with pytest.raises(ValueError, match="must not have human_topic"):
        validate_annotations([annotation(page_id, topic="algorithms", status="uncertain",
                                         reviewer="r1", notes="Ambiguous")])
    with pytest.raises(ValueError, match="requires reviewer_id and reviewer_notes"):
        validate_annotations([annotation(page_id, status="not_enough_content")])


def test_duplicate_and_invalid_prediction_detection() -> None:
    row = prediction(str(uuid4()))
    with pytest.raises(ValueError, match="duplicate prediction"):
        validate_predictions([row, row.copy()])
    bad = prediction(str(uuid4()))
    bad["predicted_topic"] = "not-a-topic"
    with pytest.raises(ValueError, match="invalid suggested"):
        validate_predictions([bad])
    annotation_row = annotation(str(uuid4()))
    with pytest.raises(ValueError, match="duplicate annotation"):
        validate_annotations([annotation_row, annotation_row.copy()])


def test_excerpt_export_requires_exact_human_acknowledgement(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["prepare_topic_annotation", "--user-id", str(uuid4()), "--include-excerpts"],
    )
    with pytest.raises(SystemExit) as exc:
        export_main()
    assert exc.value.code == 2


def test_metrics_exclude_unreviewed_uncertain_and_abstentions_from_class_prediction() -> None:
    ids = [str(uuid4()) for _ in range(5)]
    annotations = [
        annotation(ids[0], topic="algorithms", status="labeled", reviewer="r"),
        annotation(ids[1], topic="algorithms", status="labeled", reviewer="r"),
        annotation(ids[2], topic="databases", status="labeled", reviewer="r"),
        annotation(ids[3], status="uncertain", reviewer="r", notes="Could be either."),
        annotation(ids[4]),
    ]
    predictions = [
        prediction(ids[0], "algorithms"), prediction(ids[1], "databases"),
        prediction(ids[2], None), prediction(ids[3], "algorithms"),
        prediction(ids[4], "algorithms"),
    ]
    report = evaluate(annotations, predictions)
    assert report["labelled_sample_size"] == 3
    assert report["labelled_abstention_count"] == 1
    assert report["prediction_abstention_count"] == 1
    assert report["per_class"]["algorithms"] == {
        "support": 2, "predicted_count": 1, "true_positive": 1,
        "precision": 1.0, "recall": 0.5, "f1": pytest.approx(2 / 3),
    }
    assert report["per_class"]["databases"]["support"] == 1
    assert report["per_class"]["databases"]["precision"] == 0
    assert report["per_class"]["databases"]["f1"] == 0
    assert report["annotation_status_counts"]["unreviewed"] == 1
    assert report["annotation_status_counts"]["uncertain"] == 1


def test_empty_inputs_and_unknown_annotation_page() -> None:
    report = evaluate([], [])
    assert report["labelled_sample_size"] == 0
    assert report["macro_f1"] is None
    assert report["prediction_abstention_rate"] is None
    with pytest.raises(ValueError, match="absent from predictions"):
        evaluate([annotation(str(uuid4()))], [])


def test_csv_schema_and_json_report(tmp_path: Path) -> None:
    csv_path = tmp_path / "annotations.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS, lineterminator="\n")
        writer.writeheader()
    assert read_csv(csv_path, ANNOTATION_FIELDS) == []
    with pytest.raises(ValueError, match="header"):
        read_csv(csv_path, PREDICTION_FIELDS)
    report_path = tmp_path / "report.json"
    write_report(report_path, evaluate([], []))
    assert json.loads(report_path.read_text(encoding="utf-8"))["macro_f1"] is None
