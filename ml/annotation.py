"""Build a reproducible, page-level human relevance annotation package."""

from __future__ import annotations

from collections import defaultdict
from hashlib import sha256
from math import isfinite
from typing import Any
from uuid import UUID

from ml.dataset import RRF_K

MAX_SEMANTIC_NON_TARGETS = 4

ANNOTATION_FIELDS = (
    "query_id",
    "task_group_id",
    "query_text",
    "target_page_id",
    "candidate_page_id",
    "candidate_title",
    "candidate_domain",
    "candidate_url",
    "text_preview",
    "annotation_order",
    "is_target",
    "candidate_provenance",
    "semantic_status",
    "semantic_present",
    "semantic_best_chunk_rank",
    "semantic_page_rank",
    "semantic_score",
    "lexical_status",
    "lexical_present",
    "lexical_best_chunk_rank",
    "lexical_page_rank",
    "lexical_score",
    "rrf_status",
    "rrf_rank",
    "rrf_score",
    "relevance_grade",
    "label_status",
    "label_provenance",
    "human_relevance_grade",
    "human_label_status",
    "human_label_provenance",
    "annotation_notes",
)


def _valid_uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def _page_ranks(rows: list[dict[str, Any]], source: str) -> dict[str, int]:
    hits = [row for row in rows if row[f"{source}_present"]]
    hits.sort(key=lambda row: (row[f"{source}_rank"], row["candidate_page_id"]))
    return {row["candidate_page_id"]: rank for rank, row in enumerate(hits, start=1)}


def build_annotation_rows(
    queries: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    statuses: list[dict[str, Any]],
    *,
    max_semantic_non_targets: int = MAX_SEMANTIC_NON_TARGETS,
    page_metadata: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Select target + semantic top pages + lexical additions, retaining saved evidence."""
    if max_semantic_non_targets < 0:
        raise ValueError("max_semantic_non_targets must be non-negative")
    query_by_id: dict[str, dict[str, Any]] = {}
    for query in queries:
        query_id = _valid_uuid(query.get("query_id"), "query_id")
        if query_id in query_by_id:
            raise ValueError(f"duplicate query_id: {query_id}")
        query_by_id[query_id] = query

    status_by_id: dict[str, dict[str, Any]] = {}
    for status in statuses:
        query_id = _valid_uuid(status.get("query_id"), "status query_id")
        if query_id in status_by_id or query_id not in query_by_id:
            raise ValueError("duplicate or unknown query status")
        for source in ("semantic", "lexical"):
            if status.get(f"{source}_status") not in {"ok", "empty", "failed"}:
                raise ValueError(f"invalid {source} status")
        status_by_id[query_id] = status
    if set(status_by_id) != set(query_by_id):
        raise ValueError("query-status IDs do not match query IDs")

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    seen_pairs: set[tuple[str, str]] = set()
    for candidate in candidates:
        query_id = _valid_uuid(candidate.get("query_id"), "candidate query_id")
        page_id = _valid_uuid(candidate.get("candidate_page_id"), "candidate_page_id")
        if query_id not in query_by_id:
            raise ValueError("candidate refers to unknown query")
        pair = (query_id, page_id)
        if pair in seen_pairs:
            raise ValueError("duplicate query-page candidate")
        seen_pairs.add(pair)
        query = query_by_id[query_id]
        if (candidate.get("task_group_id") != query.get("task_group_id")
                or candidate.get("target_page_id") != query.get("target_page_id")
                or candidate.get("query_text") != query.get("query_text")):
            raise ValueError("candidate metadata does not match frozen query")
        for source in ("semantic", "lexical"):
            present = candidate.get(f"{source}_present")
            rank = candidate.get(f"{source}_rank")
            score = candidate.get("semantic_similarity" if source == "semantic" else "lexical_score")
            if not isinstance(present, bool) or present != (rank is not None):
                raise ValueError(f"{source} presence/rank mismatch")
            if rank is not None and (not isinstance(rank, int) or rank < 1):
                raise ValueError(f"invalid {source} chunk rank")
            if score is not None and (not isinstance(score, (int, float)) or not isfinite(score)):
                raise ValueError(f"invalid {source} score")
        grouped[query_id].append(candidate)

    output: list[dict[str, Any]] = []
    page_metadata = page_metadata or {}
    for query_id, query in query_by_id.items():
        status = status_by_id[query_id]
        rows = grouped.get(query_id, [])
        ranks = {source: _page_ranks(rows, source) for source in ("semantic", "lexical")}
        rrf_complete = (
            status.get("feature_status") == "ok"
            and status["semantic_status"] in {"ok", "empty"}
            and status["lexical_status"] in {"ok", "empty"}
        )
        rrf_scores: dict[str, float] = defaultdict(float)
        if rrf_complete:
            for source in ("semantic", "lexical"):
                for page_id, page_rank in ranks[source].items():
                    rrf_scores[page_id] += 1.0 / (RRF_K + page_rank)
            ordered_rrf = sorted(rrf_scores, key=lambda page_id: (-rrf_scores[page_id], page_id))
            rrf_ranks = {page_id: rank for rank, page_id in enumerate(ordered_rrf, start=1)}
        else:
            rrf_ranks = {}

        by_page = {row["candidate_page_id"]: row for row in rows}
        selected: set[str] = set()
        target_id = query.get("target_page_id")
        if target_id is not None:
            target_id = _valid_uuid(target_id, "target_page_id")
            selected.add(target_id)
        semantic_order = sorted(ranks["semantic"], key=lambda page_id: ranks["semantic"][page_id])
        selected.update(
            page_id for page_id in semantic_order if page_id != target_id
        )
        semantic_non_targets = [page_id for page_id in semantic_order if page_id != target_id]
        selected = ({target_id} if target_id is not None else set()) | set(
            semantic_non_targets[:max_semantic_non_targets]
        )
        selected.update(
            page_id for page_id in ranks["lexical"] if page_id != target_id
        )

        for page_id in sorted(selected):
            candidate = by_page.get(page_id)
            is_target = page_id == target_id
            provenance = []
            if is_target:
                provenance.append("known_target_by_construction")
            if candidate and candidate["semantic_present"]:
                provenance.append("semantic")
            if candidate and candidate["lexical_present"]:
                provenance.append("lexical")
            provenance_value = "+".join(provenance) if provenance else "known_target_by_construction"
            semantic_rank = ranks["semantic"].get(page_id)
            lexical_rank = ranks["lexical"].get(page_id)
            output.append({
                "query_id": query_id,
                "task_group_id": str(query["task_group_id"]),
                "query_text": query["query_text"],
                "target_page_id": target_id or "",
                "candidate_page_id": page_id,
                "candidate_title": page_metadata.get(page_id, {}).get("title", ""),
                "candidate_domain": page_metadata.get(page_id, {}).get("domain", ""),
                "candidate_url": "",
                "text_preview": "",
                "annotation_order": int.from_bytes(sha256(f"{query_id}:{page_id}".encode()).digest()[:4], "big"),
                "is_target": is_target,
                "candidate_provenance": provenance_value,
                "semantic_status": status["semantic_status"],
                "semantic_present": bool(candidate and candidate["semantic_present"]),
                "semantic_best_chunk_rank": candidate["semantic_rank"] if candidate else None,
                "semantic_page_rank": semantic_rank,
                "semantic_score": candidate["semantic_similarity"] if candidate else None,
                "lexical_status": status["lexical_status"],
                "lexical_present": bool(candidate and candidate["lexical_present"]),
                "lexical_best_chunk_rank": candidate["lexical_rank"] if candidate else None,
                "lexical_page_rank": lexical_rank,
                "lexical_score": candidate["lexical_score"] if candidate else None,
                "rrf_status": "available" if rrf_complete else "unavailable_incomplete_retrieval",
                "rrf_rank": rrf_ranks.get(page_id),
                "rrf_score": rrf_scores.get(page_id) if rrf_complete else None,
                "relevance_grade": 3 if is_target else "",
                "label_status": "known_target_by_construction" if is_target else "review_required",
                "label_provenance": query.get("query_provenance", "") if is_target else "",
                "human_relevance_grade": "",
                "human_label_status": "review_required",
                "human_label_provenance": "",
                "annotation_notes": "",
            })

    output.sort(key=lambda row: (row["query_id"], row["annotation_order"], row["candidate_page_id"]))
    validate_annotation_rows(output)
    return output


def validate_annotation_rows(rows: list[dict[str, Any]]) -> None:
    """Validate the CSV contract and make target construction explicit."""
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if set(row) != set(ANNOTATION_FIELDS):
            raise ValueError("annotation row has missing or unexpected fields")
        pair = (_valid_uuid(row["query_id"], "query_id"), _valid_uuid(row["candidate_page_id"], "candidate_page_id"))
        _valid_uuid(row["task_group_id"], "task_group_id")
        if pair in seen:
            raise ValueError("duplicate query-page annotation row")
        seen.add(pair)
        if row["target_page_id"]:
            _valid_uuid(row["target_page_id"], "target_page_id")
        if row["is_target"] != (bool(row["target_page_id"]) and row["candidate_page_id"] == row["target_page_id"]):
            raise ValueError("target flag does not match target_page_id")
        expected_sources = []
        if row["is_target"]:
            expected_sources.append("known_target_by_construction")
        if row["semantic_present"]:
            expected_sources.append("semantic")
        if row["lexical_present"]:
            expected_sources.append("lexical")
        expected_provenance = "+".join(expected_sources) if expected_sources else "known_target_by_construction"
        if row["candidate_provenance"] != expected_provenance:
            raise ValueError("candidate provenance does not match row inclusion sources")
        if row["label_status"] == "known_target_by_construction":
            if (not row["is_target"] or row["relevance_grade"] != 3
                    or row["candidate_page_id"] != row["target_page_id"] or not row["label_provenance"]):
                raise ValueError("constructed target label is inconsistent")
        elif row["label_status"] == "review_required":
            if row["is_target"] or row["relevance_grade"] != "" or row["label_provenance"]:
                raise ValueError("unreviewed candidates must have a blank grade")
        elif row["label_status"] == "independently_judged":
            if row["relevance_grade"] not in (0, 1, 2, 3) or not row["label_provenance"]:
                raise ValueError("independent judgment requires a grade and provenance")
        else:
            raise ValueError("invalid label_status")
        if row["relevance_grade"] != "" and row["relevance_grade"] not in (0, 1, 2, 3):
            raise ValueError("relevance_grade must be blank or an integer from 0 to 3")
        for source in ("semantic", "lexical"):
            if row[f"{source}_present"] != (row[f"{source}_page_rank"] is not None):
                raise ValueError(f"{source} presence/page rank mismatch")
            status = row[f"{source}_status"]
            if status not in {"ok", "empty", "failed"}:
                raise ValueError(f"invalid {source} endpoint status")
            score_field = f"{source}_score"
            if row[f"{source}_present"] != (row[score_field] is not None):
                raise ValueError(f"{source} presence/score mismatch")
            if row[score_field] is not None and (
                not isinstance(row[score_field], (int, float)) or not isfinite(row[score_field])
            ):
                raise ValueError(f"invalid {source} score")
        if row["rrf_status"] not in {"available", "unavailable_incomplete_retrieval"}:
            raise ValueError("invalid rrf_status")
        if (row["rrf_rank"] is None) != (row["rrf_score"] is None):
            raise ValueError("RRF rank and score must both be present or both blank")
        if row["rrf_status"] == "unavailable_incomplete_retrieval" and row["rrf_rank"] is not None:
            raise ValueError("incomplete RRF rows must have blank rank and score")
        if row["rrf_score"] is not None and (
            not isinstance(row["rrf_score"], (int, float)) or not isfinite(row["rrf_score"])
        ):
            raise ValueError("invalid RRF score")
        if row["human_label_status"] == "review_required":
            if row["human_relevance_grade"] != "" or row["human_label_provenance"]:
                raise ValueError("review_required human labels must be blank")
        elif row["human_label_status"] == "independently_judged":
            if row["human_relevance_grade"] not in (0, 1, 2, 3) or not row["human_label_provenance"]:
                raise ValueError("human judgments require a grade and provenance")
        elif row["human_label_status"] == "uncertain":
            if row["human_relevance_grade"] != "" or row["human_label_provenance"]:
                raise ValueError("uncertain candidates must remain ungraded")
        else:
            raise ValueError("invalid human_label_status")

