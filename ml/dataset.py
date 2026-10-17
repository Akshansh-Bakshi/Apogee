"""Versioned query and page-candidate contracts for offline Apogee reranking data."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from enum import Enum
from math import isfinite
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

DATASET_VERSION = "apogee-rerank-v1"
RRF_K = 60


class Difficulty(str, Enum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class QueryProvenance(str, Enum):
    MANUAL_AUTHORED = "manual_authored"
    GENERATED_DRAFT = "generated_draft"
    GENERATED_HUMAN_REVIEWED = "generated_human_reviewed"


class QueryRecord(BaseModel):
    """One natural-language recollection task; paraphrases share ``task_group_id``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    query_id: UUID
    task_group_id: UUID
    user_id: UUID
    query_text: str
    query_timestamp: datetime
    target_page_id: UUID | None = None
    difficulty: Difficulty
    query_provenance: QueryProvenance
    dataset_version: str = DATASET_VERSION

    @field_validator("query_text")
    @classmethod
    def query_text_nonempty(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("query_text must not be empty")
        return cleaned

    @field_validator("query_timestamp")
    @classmethod
    def query_timestamp_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("query_timestamp must include a timezone")
        return value

    @field_validator("dataset_version")
    @classmethod
    def supported_dataset_version(cls, value: str) -> str:
        if value != DATASET_VERSION:
            raise ValueError(f"dataset_version must be {DATASET_VERSION}")
        return value


class CandidateRecord(BaseModel):
    """Annotation-ready page candidate, with no page text, URL, or vector material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_version: str
    query_id: UUID
    task_group_id: UUID
    user_id: UUID
    query_text: str
    query_timestamp: datetime
    difficulty: Difficulty
    query_provenance: QueryProvenance
    target_page_id: UUID | None
    candidate_page_id: UUID
    semantic_present: bool
    lexical_present: bool
    semantic_similarity: float | None
    semantic_rank: int | None
    semantic_chunk_hit_count: int
    lexical_score: float | None
    lexical_rank: int | None
    lexical_chunk_hit_count: int
    rrf_score: float
    page_visit_event_count: int
    most_recent_visit_at: datetime | None
    recency_seconds: float | None
    history_missing: bool
    session_id_count: int | None
    session_coverage: float | None
    session_feature_missing: bool
    relevance_grade: int | None
    label_status: Literal["known_target", "review_required", "independently_judged"]
    label_provenance: str | None

    @field_validator("dataset_version")
    @classmethod
    def supported_candidate_version(cls, value: str) -> str:
        if value != DATASET_VERSION:
            raise ValueError(f"dataset_version must be {DATASET_VERSION}")
        return value

    @field_validator("relevance_grade")
    @classmethod
    def valid_relevance_grade(cls, value: int | None) -> int | None:
        if value is not None and value not in (0, 1, 2, 3):
            raise ValueError("relevance_grade must be null or an integer from 0 to 3")
        return value

    @model_validator(mode="after")
    def label_fields_are_consistent(self) -> CandidateRecord:
        if self.label_status == "known_target":
            if self.relevance_grade != 3 or self.target_page_id != self.candidate_page_id:
                raise ValueError("known_target requires the candidate to match target_page_id at grade 3")
        elif self.label_status == "review_required" and self.relevance_grade is not None:
            raise ValueError("review_required candidates must have a null relevance_grade")
        elif self.label_status == "independently_judged":
            if self.relevance_grade is None or not self.label_provenance:
                raise ValueError("independently_judged requires a grade and label_provenance")
        return self


def _finite_number(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"retrieval field {field} must be numeric") from exc
    if not isfinite(number):
        raise ValueError(f"retrieval field {field} must be finite")
    return number


def merge_page_candidates(
    semantic_results: Sequence[Mapping[str, Any]],
    lexical_results: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Union endpoint chunk results by page and preserve each source's best chunk and rank."""
    pages: dict[str, dict[str, Any]] = {}

    def add(results: Sequence[Mapping[str, Any]], source: str) -> None:
        score_field = "similarity" if source == "semantic" else "lexical_score"
        for chunk_rank, hit in enumerate(results, start=1):
            try:
                page_id = str(UUID(str(hit["page_id"])))
                score = _finite_number(hit[score_field], score_field)
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid {source} result at rank {chunk_rank}: {exc}") from exc
            candidate = pages.setdefault(
                page_id,
                {
                    "candidate_page_id": page_id,
                    "semantic_present": False,
                    "lexical_present": False,
                    "semantic_similarity": None,
                    "semantic_rank": None,
                    "semantic_chunk_hit_count": 0,
                    "lexical_score": None,
                    "lexical_rank": None,
                    "lexical_chunk_hit_count": 0,
                },
            )
            present = f"{source}_present"
            best_score = "semantic_similarity" if source == "semantic" else "lexical_score"
            best_rank = f"{source}_rank"
            hit_count = f"{source}_chunk_hit_count"
            candidate[present] = True
            candidate[hit_count] += 1
            if candidate[best_score] is None or score > candidate[best_score]:
                candidate[best_score] = score
                candidate[best_rank] = chunk_rank

    add(semantic_results, "semantic")
    add(lexical_results, "lexical")
    for candidate in pages.values():
        candidate["rrf_score"] = sum(
            1.0 / (RRF_K + candidate[f"{source}_rank"])
            for source in ("semantic", "lexical")
            if candidate[f"{source}_rank"] is not None
        )
    return [pages[page_id] for page_id in sorted(pages)]


def history_features(
    events: Iterable[Mapping[str, Any]], query_timestamp: datetime
) -> dict[str, Any]:
    """Compute event and session summaries from already user/page-scoped as-of events."""
    if query_timestamp.tzinfo is None or query_timestamp.utcoffset() is None:
        raise ValueError("query_timestamp must include a timezone")
    query_utc = query_timestamp.astimezone(timezone.utc)
    eligible: list[tuple[datetime, Any]] = []
    for event in events:
        occurred_at = event["occurred_at"]
        if isinstance(occurred_at, str):
            occurred_at = datetime.fromisoformat(occurred_at.replace("Z", "+00:00"))
        if not isinstance(occurred_at, datetime) or occurred_at.tzinfo is None:
            raise ValueError("history event occurred_at must be timezone-aware")
        occurred_utc = occurred_at.astimezone(timezone.utc)
        if occurred_utc <= query_utc:
            eligible.append((occurred_utc, event.get("session_id")))

    if not eligible:
        return {
            "page_visit_event_count": 0,
            "most_recent_visit_at": None,
            "recency_seconds": None,
            "history_missing": True,
            "session_id_count": None,
            "session_coverage": None,
            "session_feature_missing": True,
        }

    most_recent = max(occurred for occurred, _ in eligible)
    session_ids = {str(session_id) for _, session_id in eligible if session_id is not None}
    has_session = bool(session_ids)
    return {
        "page_visit_event_count": len(eligible),
        "most_recent_visit_at": most_recent,
        "recency_seconds": (query_utc - most_recent).total_seconds(),
        "history_missing": False,
        "session_id_count": len(session_ids) if has_session else None,
        "session_coverage": sum(session_id is not None for _, session_id in eligible)
        / len(eligible),
        "session_feature_missing": not has_session,
    }


def make_candidate_record(
    query: QueryRecord, candidate: Mapping[str, Any], history: Mapping[str, Any]
) -> dict[str, Any]:
    """Combine retrieval and history features; only a declared target gets an initial positive."""
    is_target = query.target_page_id is not None and str(query.target_page_id) == candidate["candidate_page_id"]
    row = {
        "dataset_version": query.dataset_version,
        "query_id": str(query.query_id),
        "task_group_id": str(query.task_group_id),
        "user_id": str(query.user_id),
        "query_text": query.query_text,
        "query_timestamp": query.query_timestamp,
        "difficulty": query.difficulty.value,
        "query_provenance": query.query_provenance.value,
        "target_page_id": str(query.target_page_id) if query.target_page_id else None,
        **candidate,
        **history,
        "relevance_grade": 3 if is_target else None,
        "label_status": "known_target" if is_target else "review_required",
        "label_provenance": query.query_provenance.value if is_target else None,
    }
    return CandidateRecord.model_validate(row).model_dump(mode="json")
