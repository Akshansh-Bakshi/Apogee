from __future__ import annotations

import csv
import json
from pathlib import Path
from uuid import UUID

import pytest

from ml.annotation import ANNOTATION_FIELDS, build_annotation_rows
from ml.annotation_workflow import (
    REVIEW_FIELDS,
    WORKFLOW_FIELDS,
    _spreadsheet_safe,
    build_review_file,
    export_judgments,
    validate_review,
)
from ml.lookup_annotation_pages import LOOKUP_FIELDS


def _uuid(number: int) -> str:
    return str(UUID(int=number))


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows([
            {key: str(value).lower() if isinstance(value, bool) else value for key, value in row.items()}
            for row in rows
        ])


@pytest.fixture
def workflow_files(tmp_path: Path) -> tuple[Path, Path, Path]:
    queries = []
    statuses = []
    candidates = []
    targets = [_uuid(3000 + index) for index in range(50)]
    alternatives = [_uuid(4000 + index) for index in range(4)]
    for index in range(100):
        query_id = _uuid(1000 + index)
        task_group_id = _uuid(2000 + index // 2)
        queries.append({
            "query_id": query_id,
            "task_group_id": task_group_id,
            "query_text": f"synthetic memory query {index}",
            "target_page_id": targets[index // 2],
            "query_provenance": "generated_human_reviewed",
        })
        statuses.append({
            "query_id": query_id,
            "semantic_status": "ok",
            "lexical_status": "empty",
            "feature_status": "ok",
        })
        candidates.extend({
            "query_id": query_id,
            "task_group_id": task_group_id,
            "query_text": f"synthetic memory query {index}",
            "target_page_id": targets[index // 2],
            "candidate_page_id": page_id,
            "semantic_present": True,
            "semantic_rank": rank,
            "semantic_similarity": 0.9 - rank / 100,
            "lexical_present": False,
            "lexical_rank": None,
            "lexical_score": None,
        } for rank, page_id in enumerate(alternatives, start=1))
    source_rows = build_annotation_rows(queries, candidates, statuses)

    source = tmp_path / "annotation.csv"
    _write_csv(source, ANNOTATION_FIELDS, source_rows)
    lookup = tmp_path / "lookup.csv"
    page_ids = sorted({row["candidate_page_id"] for row in source_rows})
    lookup_rows = [{
        "candidate_page_id": page_id,
        "candidate_title_from_annotation": "",
        "candidate_domain_from_annotation": "",
        "database_record_found": "True",
        "recovered_title": f"Page {page_id[-4:]}",
        "recovered_canonical_url": f"https://example.org/{page_id[-4:]}",
        "recovered_domain": "example.org",
        "first_seen_at": "2026-10-18T10:00:00+00:00",
        "last_seen_at": "2026-10-18T10:00:00+00:00",
        "created_at": "2026-10-18T10:00:00+00:00",
        "updated_at": "2026-10-18T10:00:00+00:00",
        "chunk_count": "1",
        "content_available": "True",
        "short_content_excerpt": f"Stored content for page {page_id[-4:]}",
        "lookup_status": "resolved_with_content",
    } for page_id in page_ids]
    _write_csv(lookup, LOOKUP_FIELDS, lookup_rows)
    review = tmp_path / "review.csv"
    assert build_review_file(source, lookup, review) == 500
    return source, lookup, review


def _read_review(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames or ()) == WORKFLOW_FIELDS
        return list(reader)


def _save_review(path: Path, rows: list[dict[str, str]]) -> None:
    _write_csv(path, WORKFLOW_FIELDS, rows)


def _mark_independent(row: dict[str, str], *, grade: str = "2") -> None:
    row["human_label_status"] = "independently_judged"
    row["human_relevance_grade"] = grade
    row["human_annotator_id"] = "reviewer-01"
    row["human_label_provenance"] = "reviewer-01"
    row["human_rationale"] = "The stored explanation directly supports this recollection."


def test_annotations_persist_and_export_only_independent_human_labels(workflow_files: tuple[Path, Path, Path], tmp_path: Path) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    assert rows[0]["review_title"].startswith("Page ")
    assert rows[0]["canonical_url"].startswith("https://example.org/")
    assert rows[0]["content_excerpt"].startswith("Stored content for page ")
    non_target = next(row for row in rows if row["is_target"] == "false")
    _mark_independent(non_target)
    target = next(row for row in rows if row["is_target"] == "true")
    _mark_independent(target, grade="2")
    uncertain = next(row for row in rows if row["is_target"] == "false" and row["human_label_status"] == "review_required")
    uncertain["human_label_status"] = "uncertain"
    uncertain["human_annotator_id"] = "reviewer-02"
    uncertain["uncertainty_note"] = "Two stored pages appear to explain the same concept."
    _save_review(review, rows)

    assert validate_review(source, lookup, review) == 500
    saved = _read_review(review)
    assert next(row for row in saved if row["candidate_page_id"] == non_target["candidate_page_id"])["human_relevance_grade"] == "2"
    assert next(row for row in saved if row["candidate_page_id"] == uncertain["candidate_page_id"])["human_label_status"] == "uncertain"

    exported = tmp_path / "human-labels.jsonl"
    assert export_judgments(source, lookup, review, exported) == 2
    records = [json.loads(line) for line in exported.read_text(encoding="utf-8").splitlines()]
    exported_target = next(record for record in records if record["source_label_status"] == "known_target_by_construction")
    assert exported_target["source_relevance_grade"] == 3
    assert exported_target["human_relevance_grade"] == 2
    assert exported_target["human_label_status"] == "independently_judged"
    assert all(record["human_annotator_id"] == "reviewer-01" for record in records)
    exported_non_target = next(record for record in records if record["source_label_status"] == "review_required")
    assert exported_non_target["source_relevance_grade"] is None
    assert all("content_excerpt" not in record and "canonical_url" not in record for record in records)


@pytest.mark.parametrize("grade", ["4", "-1", "2.0", "", "three"])
def test_rejects_invalid_or_missing_grade_for_independent_judgment(
    workflow_files: tuple[Path, Path, Path], grade: str
) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    _mark_independent(next(row for row in rows if row["is_target"] == "false"), grade=grade)
    _save_review(review, rows)
    with pytest.raises(ValueError, match="grade"):
        validate_review(source, lookup, review)


def test_unreviewed_grade_and_uncertain_grade_are_rejected(workflow_files: tuple[Path, Path, Path]) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    rows[0]["human_relevance_grade"] = "1"
    _save_review(review, rows)
    with pytest.raises(ValueError, match="review_required"):
        validate_review(source, lookup, review)

    rows = _read_review(review)
    rows[0]["human_relevance_grade"] = ""
    uncertain = next(row for row in rows if row["is_target"] == "false")
    uncertain["human_label_status"] = "uncertain"
    uncertain["human_annotator_id"] = "reviewer-01"
    uncertain["uncertainty_note"] = "Need a second look."
    uncertain["human_relevance_grade"] = "1"
    _save_review(review, rows)
    with pytest.raises(ValueError, match="uncertain rows must not have a relevance grade"):
        validate_review(source, lookup, review)


def test_rejects_missing_duplicate_or_unknown_row_identity(workflow_files: tuple[Path, Path, Path]) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    _save_review(review, rows[:-1])
    with pytest.raises(ValueError, match="missing"):
        validate_review(source, lookup, review)
    rows = _read_review(workflow_files[2])
    rows[-1] = dict(rows[0])
    _save_review(review, rows)
    with pytest.raises(ValueError, match="duplicate"):
        validate_review(source, lookup, review)


@pytest.mark.parametrize("field,value", [
    ("candidate_title", "Changed title"),
    ("label_status", "independently_judged"),
    ("relevance_grade", "0"),
    ("label_provenance", "changed"),
    ("canonical_url", "https://invented.invalid/"),
    ("content_excerpt", "Changed evidence"),
])
def test_preserves_original_source_labels_and_lookup_metadata(
    workflow_files: tuple[Path, Path, Path], field: str, value: str
) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    rows[0][field] = value
    _save_review(review, rows)
    with pytest.raises(ValueError, match="changed"):
        validate_review(source, lookup, review)


def test_uncertain_review_requires_note_and_completed_export_requires_labels(
    workflow_files: tuple[Path, Path, Path], tmp_path: Path
) -> None:
    source, lookup, review = workflow_files
    rows = _read_review(review)
    row = next(item for item in rows if item["is_target"] == "false")
    row["human_label_status"] = "uncertain"
    row["human_annotator_id"] = "reviewer-01"
    _save_review(review, rows)
    with pytest.raises(ValueError, match="uncertain rows require"):
        validate_review(source, lookup, review)
    row["uncertainty_note"] = "Needs a second reviewer."
    _save_review(review, rows)
    with pytest.raises(ValueError, match="no independently judged"):
        export_judgments(source, lookup, review, tmp_path / "empty.jsonl")


def test_workflow_schema_constants_keep_original_columns() -> None:
    assert set(ANNOTATION_FIELDS).issubset(WORKFLOW_FIELDS)
    assert set(REVIEW_FIELDS).issubset(WORKFLOW_FIELDS)


@pytest.mark.parametrize("content", ["=HYPERLINK(\"https://example.org\")", " +SUM(A1:A2)", "@malicious"])
def test_page_derived_strings_are_safe_for_spreadsheet_display(content: str) -> None:
    assert _spreadsheet_safe(content).startswith("'")
