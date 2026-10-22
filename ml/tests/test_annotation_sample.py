from __future__ import annotations

from copy import deepcopy
from uuid import UUID

import pytest

from ml.annotation_sample import (
    PROVENANCE_FIELDS,
    REVIEW_FIELDS,
    SAMPLE_GROUP_IDS,
    build_sample_rows,
    validate_sample_review,
)


def _uuid(number: int) -> str:
    return str(UUID(int=number))


@pytest.fixture
def sample_inputs() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    page_ids = [_uuid(5000 + index) for index in range(26)]
    source: list[dict[str, str]] = []
    for group_index, group_id in enumerate(SAMPLE_GROUP_IDS):
        target_id = page_ids[group_index]
        for paraphrase in range(2):
            query_id = _uuid(6000 + group_index * 2 + paraphrase)
            query_index = group_index * 2 + paraphrase
            candidate_ids = [target_id]
            for offset in range(26):
                candidate_id = page_ids[(query_index * 5 + offset) % len(page_ids)]
                if candidate_id not in candidate_ids:
                    candidate_ids.append(candidate_id)
                if len(candidate_ids) == 5:
                    break
            for rank, page_id in enumerate(candidate_ids, start=1):
                is_target = page_id == target_id
                source.append({
                    "query_id": query_id,
                    "task_group_id": group_id,
                    "query_text": f"Researcher-authored query {group_index}-{paraphrase}",
                    "target_page_id": target_id,
                    "candidate_page_id": page_id,
                    "is_target": str(is_target).lower(),
                    "relevance_grade": "3" if is_target else "",
                    "label_status": "known_target_by_construction" if is_target else "review_required",
                    "label_provenance": "generated_human_reviewed" if is_target else "",
                    "candidate_provenance": "known_target_by_construction+semantic" if is_target else "semantic",
                    "semantic_status": "ok",
                    "semantic_present": "true",
                    "semantic_page_rank": str(rank),
                    "semantic_score": str(1.0 - rank / 100),
                    "lexical_status": "empty",
                    "lexical_present": "false",
                    "lexical_page_rank": "",
                    "lexical_score": "",
                    "rrf_status": "available",
                    "rrf_rank": str(rank),
                    "rrf_score": str(1.0 / (60 + rank)),
                    "annotation_order": str(rank),
                })
    lookup = [{
        "candidate_page_id": page_id,
        "database_record_found": "True",
        "recovered_title": f"Page title {index}",
        "recovered_canonical_url": f"https://example.org/pages/{index}",
        "recovered_domain": "example.org",
        "short_content_excerpt": f"Stored source passage for candidate page {index}.",
        "content_available": "True",
        "lookup_status": "resolved_with_content",
    } for index, page_id in enumerate(page_ids)]
    return source, lookup


def test_sample_keeps_planned_counts_grouping_and_blinded_fields(sample_inputs) -> None:
    source, lookup = sample_inputs
    review, provenance = build_sample_rows(source, lookup)

    assert len(review) == len(provenance) == 150
    assert len({row["task_group_id"] for row in review}) == 15
    assert len({row["query_id"] for row in review}) == 30
    assert len({row["candidate_page_id"] for row in review}) == 26
    assert all(sum(row["task_group_id"] == group for row in review) == 10 for group in SAMPLE_GROUP_IDS)
    assert all("semantic" not in field and "lexical" not in field and "rrf" not in field for field in REVIEW_FIELDS)
    assert not {"is_target", "target_page_id", "candidate_provenance", "semantic_page_rank", "lexical_page_rank", "rrf_rank"} & set(REVIEW_FIELDS)
    assert all(not row["human_relevance_grade"] for row in review)
    assert all(row["human_label_status"] == "review_required" for row in review)
    assert all(not row["human_annotator_id"] and not row["human_rationale"] for row in review)
    assert set(PROVENANCE_FIELDS).issubset(provenance[0])
    assert sum(row["known_target_by_construction"] == "true" for row in provenance) == 30
    assert sum(bool(row["semantic_page_rank"]) for row in provenance) == 150
    assert all(row["canonical_url"].startswith("https://") and row["content_excerpt"] for row in review)


def test_source_identity_and_target_metadata_are_preserved_separately(sample_inputs) -> None:
    source, lookup = sample_inputs
    review, provenance = build_sample_rows(source, lookup)
    src_by_pair = {(row["query_id"], row["candidate_page_id"]): row for row in source if row["task_group_id"] in SAMPLE_GROUP_IDS}
    map_by_pair = {(row["query_id"], row["candidate_page_id"]): row for row in provenance}

    assert set(map_by_pair) == set(src_by_pair)
    for row in review:
        source_row = src_by_pair[(row["query_id"], row["candidate_page_id"])]
        mapping = map_by_pair[(row["query_id"], row["candidate_page_id"])]
        assert row["task_group_id"] == source_row["task_group_id"]
        assert row["query_text"] == source_row["query_text"]
        assert mapping["known_target_by_construction"] == source_row["is_target"]
        assert mapping["source_relevance_grade"] == source_row["relevance_grade"]
    baseline = deepcopy(review)
    changed = deepcopy(review)
    changed[0]["query_text"] += " changed"
    with pytest.raises(ValueError, match="metadata changed"):
        validate_sample_review(changed, baseline)


@pytest.mark.parametrize("grade", ["0", "1", "2", "3"])
def test_accepts_independent_grade_with_annotator_and_rationale(sample_inputs, grade: str) -> None:
    review, _ = build_sample_rows(*sample_inputs)
    edited = deepcopy(review)
    edited[0].update({
        "human_relevance_grade": grade,
        "human_label_status": "independently_judged",
        "human_annotator_id": "reviewer-01",
        "human_rationale": "Stored passage answers the information need.",
    })
    assert validate_sample_review(edited, review) == 150


@pytest.mark.parametrize("grade", ["4", "-1", "2.0", "", "three"])
def test_rejects_invalid_independent_grade(sample_inputs, grade: str) -> None:
    review, _ = build_sample_rows(*sample_inputs)
    edited = deepcopy(review)
    edited[0].update({
        "human_relevance_grade": grade,
        "human_label_status": "independently_judged",
        "human_annotator_id": "reviewer-01",
        "human_rationale": "Reviewed the stored page.",
    })
    with pytest.raises(ValueError, match="grade 0-3"):
        validate_sample_review(edited, review)


def test_unreviewed_and_uncertain_rows_cannot_carry_grades(sample_inputs) -> None:
    review, _ = build_sample_rows(*sample_inputs)
    edited = deepcopy(review)
    edited[0]["human_relevance_grade"] = "0"
    with pytest.raises(ValueError, match="review_required"):
        validate_sample_review(edited, review)

    edited = deepcopy(review)
    edited[0].update({
        "human_relevance_grade": "2",
        "human_label_status": "uncertain",
        "human_annotator_id": "reviewer-01",
        "uncertainty_note": "Two pages could satisfy this broad wording.",
    })
    with pytest.raises(ValueError, match="uncertain rows"):
        validate_sample_review(edited, review)


def test_uncertain_rows_require_explanation_and_judged_rows_require_rationale(sample_inputs) -> None:
    review, _ = build_sample_rows(*sample_inputs)
    edited = deepcopy(review)
    edited[0].update({
        "human_label_status": "uncertain",
        "human_annotator_id": "reviewer-01",
    })
    with pytest.raises(ValueError, match="uncertain rows"):
        validate_sample_review(edited, review)

    edited = deepcopy(review)
    edited[0].update({
        "human_relevance_grade": "1",
        "human_label_status": "independently_judged",
        "human_annotator_id": "reviewer-01",
    })
    with pytest.raises(ValueError, match="grade 0-3"):
        validate_sample_review(edited, review)
