from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from ml.annotation import build_annotation_rows, validate_annotation_rows
from ml.prepare_annotation import (
    check_frozen_evaluation,
    read_page_metadata,
    validate_csv,
    write_csv,
)

Q1 = "00000000-0000-0000-0000-000000000001"
TASK = "00000000-0000-0000-0000-000000000002"
TARGET = "00000000-0000-0000-0000-000000000010"
PAGES = [f"00000000-0000-0000-0000-{number:012d}" for number in range(11, 19)]


def query() -> dict:
    return {
        "query_id": Q1,
        "task_group_id": TASK,
        "query_text": "a remembered page about a specific idea",
        "target_page_id": TARGET,
        "query_provenance": "generated_human_reviewed",
    }


def candidate(page: str, *, semantic_rank: int | None = None, lexical_rank: int | None = None) -> dict:
    return {
        "query_id": Q1,
        "task_group_id": TASK,
        "query_text": query()["query_text"],
        "target_page_id": TARGET,
        "candidate_page_id": page,
        "semantic_present": semantic_rank is not None,
        "semantic_rank": semantic_rank,
        "semantic_similarity": 0.9 - semantic_rank / 100 if semantic_rank is not None else None,
        "lexical_present": lexical_rank is not None,
        "lexical_rank": lexical_rank,
        "lexical_score": 0.8 - lexical_rank / 100 if lexical_rank is not None else None,
    }


def status() -> dict:
    return {
        "query_id": Q1,
        "semantic_status": "ok",
        "lexical_status": "ok",
        "feature_status": "ok",
    }


def test_selects_target_four_semantic_non_targets_and_lexical_additions() -> None:
    candidates = [candidate(PAGES[0], semantic_rank=1)]
    candidates += [candidate(page, semantic_rank=rank) for rank, page in enumerate(PAGES[1:7], start=2)]
    candidates += [candidate(PAGES[7], lexical_rank=1)]
    rows = build_annotation_rows([query()], candidates, [status()])
    by_page = {row["candidate_page_id"]: row for row in rows}
    assert set(by_page) == {TARGET, *PAGES[0:4], PAGES[7]}
    assert len(rows) == 6
    assert by_page[TARGET]["label_status"] == "known_target_by_construction"
    assert by_page[TARGET]["relevance_grade"] == 3
    assert by_page[TARGET]["human_relevance_grade"] == ""
    assert by_page[TARGET]["human_label_status"] == "review_required"
    assert by_page[TARGET]["human_relevance_grade"] == ""
    assert by_page[TARGET]["human_label_status"] == "review_required"
    assert by_page[TARGET]["semantic_page_rank"] is None
    assert by_page[PAGES[0]]["semantic_page_rank"] == 1
    assert by_page[PAGES[0]]["rrf_score"] == pytest.approx(1 / 61)
    assert by_page[PAGES[7]]["candidate_provenance"] == "lexical"
    assert all(row["label_status"] == "review_required" for row in rows if not row["is_target"])
    assert all(row["human_relevance_grade"] == "" for row in rows)
    assert all(row["human_relevance_grade"] == "" for row in rows)


def test_target_retrieved_by_both_sources_keeps_page_ranks_and_flags_construction() -> None:
    retrieved = candidate(TARGET, semantic_rank=2, lexical_rank=1)
    rows = build_annotation_rows([query()], [retrieved], [status()])
    target = rows[0]
    assert target["semantic_page_rank"] == 1
    assert target["lexical_page_rank"] == 1
    assert target["candidate_provenance"] == "known_target_by_construction+semantic+lexical"
    assert target["rrf_score"] == pytest.approx(2 / 61)


def test_incomplete_retrieval_has_explicit_missing_rrf_and_no_invented_scores() -> None:
    failed = {**status(), "lexical_status": "failed"}
    rows = build_annotation_rows([query()], [], [failed])
    target = rows[0]
    assert target["semantic_status"] == "ok"
    assert target["lexical_status"] == "failed"
    assert target["semantic_score"] is None
    assert target["lexical_score"] is None
    assert target["rrf_status"] == "unavailable_incomplete_retrieval"
    assert target["rrf_rank"] is None
    assert target["rrf_score"] is None


def test_output_is_deterministic_validates_round_trip_and_matches_frozen_target_ranks(tmp_path: Path) -> None:
    candidates = [candidate(TARGET, semantic_rank=3), candidate(PAGES[0], semantic_rank=1)]
    first = build_annotation_rows([query()], candidates, [status()])
    second = build_annotation_rows([query()], candidates, [status()])
    assert first == second
    validate_annotation_rows(first)
    eval_rows = [{
        "query_id": Q1,
        "semantic_page_rank": 2,
        "lexical_page_rank": None,
        "hybrid_page_rank": 2,
    }]
    check_frozen_evaluation(first, eval_rows)
    path = tmp_path / "annotation.csv"
    write_csv(path, first)
    assert validate_csv(path) == 2

    reviewed = [dict(row) for row in first]
    reviewed[0]["human_relevance_grade"] = 3
    reviewed[0]["human_label_status"] = "independently_judged"
    reviewed[0]["human_label_provenance"] = "annotator-01"
    assert reviewed[0]["relevance_grade"] == first[0]["relevance_grade"]
    validate_annotation_rows(reviewed)

    reviewed = [dict(row) for row in first]
    reviewed[0]["human_relevance_grade"] = 3
    reviewed[0]["human_label_status"] = "independently_judged"
    reviewed[0]["human_label_provenance"] = "annotator-01"
    assert reviewed[0]["relevance_grade"] == first[0]["relevance_grade"]
    validate_annotation_rows(reviewed)


def test_reads_page_metadata_only_from_reviewed_target_sections(tmp_path: Path) -> None:
    review = tmp_path / "review.md"
    review.write_text(
        "## A source title\n**Target page:** `" + TARGET + "` · example.org\n\n### Task\n",
        encoding="utf-8",
    )
    assert read_page_metadata(review) == {
        TARGET: {"title": "A source title", "domain": "example.org"}
    }


def test_rejects_duplicate_query_page_rows_and_metadata_drift() -> None:
    duplicate = candidate(PAGES[0], semantic_rank=1)
    with pytest.raises(ValueError, match="duplicate"):
        build_annotation_rows([query()], [duplicate, duplicate], [status()])
    changed = {**candidate(PAGES[0], semantic_rank=1), "task_group_id": str(UUID(int=3))}
    with pytest.raises(ValueError, match="metadata"):
        build_annotation_rows([query()], [changed], [status()])

