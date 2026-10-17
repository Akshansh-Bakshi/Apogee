from __future__ import annotations

import json
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError
from uuid import UUID

import pytest
from pydantic import ValidationError

from ml.dataset import (
    CandidateRecord,
    QueryRecord,
    history_features,
    make_candidate_record,
    merge_page_candidates,
)
from ml.prepare_dataset import (
    API_ENDPOINTS,
    post_search,
    prepare_dataset,
    require_user_scoped_pages,
    validate_candidates,
)

USER = UUID("10000000-0000-0000-0000-000000000001")
QUERY = UUID("20000000-0000-0000-0000-000000000001")
TASK = UUID("30000000-0000-0000-0000-000000000001")
PAGE_A = UUID("40000000-0000-0000-0000-000000000001")
PAGE_B = UUID("40000000-0000-0000-0000-000000000002")
SESSION = UUID("50000000-0000-0000-0000-000000000001")
AT = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def query(**updates: object) -> QueryRecord:
    values: dict[str, object] = {
        "query_id": QUERY,
        "task_group_id": TASK,
        "user_id": USER,
        "query_text": "the article about a memory systems paper",
        "query_timestamp": AT,
        "target_page_id": PAGE_A,
        "difficulty": "medium",
        "query_provenance": "manual_authored",
    }
    values.update(updates)
    return QueryRecord.model_validate(values)


def test_query_schema_requires_timezone_and_supported_difficulty() -> None:
    with pytest.raises(ValidationError):
        query(query_timestamp="2026-10-18T12:00:00")
    with pytest.raises(ValidationError):
        query(difficulty="impossible")
    with pytest.raises(ValidationError):
        query(dataset_version="future-version")


def test_merge_deduplicates_pages_and_preserves_best_chunk_ranks_and_hit_counts() -> None:
    candidates = merge_page_candidates(
        [
            {"page_id": str(PAGE_A), "similarity": 0.8},
            {"page_id": str(PAGE_A), "similarity": 0.9},
            {"page_id": str(PAGE_B), "similarity": 0.7},
        ],
        [
            {"page_id": str(PAGE_A), "lexical_score": 0.2},
            {"page_id": str(PAGE_B), "lexical_score": 0.6},
            {"page_id": str(PAGE_A), "lexical_score": 0.5},
        ],
    )
    assert [row["candidate_page_id"] for row in candidates] == [str(PAGE_A), str(PAGE_B)]
    a = candidates[0]
    assert a["semantic_similarity"] == 0.9
    assert a["semantic_rank"] == 2
    assert a["semantic_chunk_hit_count"] == 2
    assert a["lexical_score"] == 0.5
    assert a["lexical_rank"] == 3
    assert a["lexical_chunk_hit_count"] == 2
    assert a["rrf_score"] == pytest.approx(1 / 62 + 1 / 63)


def test_hybrid_score_uses_each_available_source_rank_once() -> None:
    rows = merge_page_candidates(
        [{"page_id": str(PAGE_A), "similarity": 0.3}],
        [{"page_id": str(PAGE_B), "lexical_score": 0.9}],
    )
    assert rows[0]["rrf_score"] == pytest.approx(1 / 61)
    assert rows[1]["rrf_score"] == pytest.approx(1 / 61)


def test_history_features_filter_future_events_and_mark_session_coverage() -> None:
    result = history_features(
        [
            {"occurred_at": "2026-10-18T10:00:00Z", "session_id": str(SESSION)},
            {"occurred_at": "2026-10-18T11:00:00Z", "session_id": None},
            {"occurred_at": "2026-10-18T13:00:00Z", "session_id": str(SESSION)},
        ],
        AT,
    )
    assert result["page_visit_event_count"] == 2
    assert result["most_recent_visit_at"] == datetime(2026, 10, 18, 11, tzinfo=timezone.utc)
    assert result["recency_seconds"] == 3600
    assert result["session_id_count"] == 1
    assert result["session_coverage"] == 0.5
    assert result["session_feature_missing"] is False


def test_missing_history_and_zero_session_coverage_are_explicit() -> None:
    missing = history_features([], AT)
    assert missing["history_missing"] is True
    assert missing["session_id_count"] is None
    assert missing["session_coverage"] is None
    assert missing["session_feature_missing"] is True

    no_sessions = history_features([{"occurred_at": AT, "session_id": None}], AT)
    assert no_sessions["history_missing"] is False
    assert no_sessions["session_id_count"] is None
    assert no_sessions["session_coverage"] == 0
    assert no_sessions["session_feature_missing"] is True


def test_user_scope_rejects_foreign_or_missing_page_ids() -> None:
    require_user_scoped_pages({str(PAGE_A)}, {str(PAGE_A)})
    with pytest.raises(ValueError, match="not owned"):
        require_user_scoped_pages({str(PAGE_A)}, {str(PAGE_B)})


def test_target_is_initialized_positive_and_other_candidates_need_review() -> None:
    merged = merge_page_candidates(
        [{"page_id": str(PAGE_A), "similarity": 0.8}],
        [{"page_id": str(PAGE_B), "lexical_score": 0.4}],
    )
    no_history = history_features([], AT)
    rows = [make_candidate_record(query(), item, no_history) for item in merged]
    by_page = {row["candidate_page_id"]: row for row in rows}
    assert by_page[str(PAGE_A)]["relevance_grade"] == 3
    assert by_page[str(PAGE_A)]["label_status"] == "known_target"
    assert by_page[str(PAGE_B)]["relevance_grade"] is None
    assert by_page[str(PAGE_B)]["label_status"] == "review_required"
    assert CandidateRecord.model_validate(by_page[str(PAGE_A)])


def test_post_search_distinguishes_empty_success_from_http_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        status = 200

        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"results": []}'

    monkeypatch.setattr("ml.prepare_dataset.urlopen", lambda *_args, **_kwargs: Response())
    result = post_search("http://localhost", API_ENDPOINTS["semantic"], query(), 50)
    assert result["status"] == "empty"
    assert result["error"] is None

    def http_failure(*_args: object, **_kwargs: object) -> None:
        raise HTTPError("http://localhost", 503, "unavailable", {}, BytesIO(b"private body"))

    monkeypatch.setattr("ml.prepare_dataset.urlopen", http_failure)
    failed = post_search("http://localhost", API_ENDPOINTS["semantic"], query(), 50)
    assert failed["status"] == "failed"
    assert failed["error"] == "HTTP 503"
    assert failed["results"] == []


def test_export_is_deterministic_and_preserves_failure_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("ml.prepare_dataset._backend_imports", lambda: (lambda: object(), None, None))

    def fake_search(_base: str, endpoint: str, _query: QueryRecord, _limit: int) -> dict[str, object]:
        if endpoint == API_ENDPOINTS["semantic"]:
            return {"status": "empty", "error": None, "results": []}
        return {"status": "failed", "error": "HTTP 503", "results": []}

    monkeypatch.setattr("ml.prepare_dataset.post_search", fake_search)
    output_dir = tmp_path / "local"
    rows, statuses = prepare_dataset([query(target_page_id=None)], api_base_url="http://api", limit=50, output_dir=output_dir)
    first = (output_dir / "query_status.jsonl").read_text(encoding="utf-8")
    prepare_dataset([query(target_page_id=None)], api_base_url="http://api", limit=50, output_dir=output_dir)
    assert (rows, statuses) == (0, 1)
    assert (output_dir / "query_status.jsonl").read_text(encoding="utf-8") == first
    status = json.loads(first)
    assert status["semantic_status"] == "empty"
    assert status["lexical_status"] == "failed"
    assert status["lexical_error"] == "HTTP 503"
    assert validate_candidates(output_dir / "candidates.jsonl") == 0
