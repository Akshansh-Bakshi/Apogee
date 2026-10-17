"""Collect API candidates and as-of browsing-history features into local JSONL files."""

from __future__ import annotations

import argparse
import json
from math import isfinite
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ml.dataset import (
    DATASET_VERSION,
    CandidateRecord,
    QueryRecord,
    history_features,
    make_candidate_record,
    merge_page_candidates,
)

API_ENDPOINTS = {
    "semantic": "/api/v1/search",
    "lexical": "/api/v1/search/lexical",
}


def require_user_scoped_pages(requested_ids: set[str], owned_ids: set[str]) -> None:
    """Reject candidate or target IDs that are not owned by the query's user."""
    if requested_ids != owned_ids:
        raise ValueError("candidate or target page is not owned by query user")


def read_queries(path: Path) -> list[QueryRecord]:
    queries: list[QueryRecord] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                query = QueryRecord.model_validate_json(line)
            except ValidationError as exc:
                raise ValueError(f"invalid query JSONL at line {line_number}: {exc}") from None
            if str(query.query_id) in seen:
                raise ValueError(f"duplicate query_id at line {line_number}")
            seen.add(str(query.query_id))
            queries.append(query)
    return queries


def post_search(
    api_base_url: str, endpoint: str, query: QueryRecord, limit: int
) -> dict[str, Any]:
    body = json.dumps(
        {"user_id": str(query.user_id), "query": query.query_text, "limit": limit}
    ).encode("utf-8")
    request = Request(
        api_base_url.rstrip("/") + endpoint,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            status_code = response.status
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return {"status": "failed", "error": f"HTTP {exc.code}", "results": []}
    except (URLError, TimeoutError, OSError):
        return {"status": "failed", "error": "network_error", "results": []}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"status": "failed", "error": "invalid_json_response", "results": []}

    if not 200 <= status_code < 300:
        return {"status": "failed", "error": f"HTTP {status_code}", "results": []}
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        return {"status": "failed", "error": "invalid_response_schema", "results": []}
    score_field = "similarity" if endpoint == API_ENDPOINTS["semantic"] else "lexical_score"
    for hit in payload["results"]:
        if not isinstance(hit, dict) or score_field not in hit or "page_id" not in hit:
            return {"status": "failed", "error": "invalid_response_schema", "results": []}
        try:
            UUID(str(hit["page_id"]))
            if not isfinite(float(hit[score_field])):
                raise ValueError("score must be finite")
        except (TypeError, ValueError):
            return {"status": "failed", "error": "invalid_response_schema", "results": []}
    return {
        "status": "ok" if payload["results"] else "empty",
        "error": None,
        "results": payload["results"],
    }


def _backend_imports() -> tuple[Any, Any, Any]:
    """Load project settings/models without duplicating DB configuration in this script."""
    backend_path = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    from app.core.config import Settings
    from app.db.session import create_db_engine
    from app.models import BrowsingEvent, Page

    return Settings, create_db_engine, (BrowsingEvent, Page)


def collect_history(settings: Any, query: QueryRecord, page_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Load user-scoped candidate history, filtering events by the query's as-of timestamp."""
    Settings, create_db_engine, models = _backend_imports()
    del Settings
    BrowsingEvent, Page = models
    requested_ids = set(page_ids)
    if query.target_page_id is not None:
        requested_ids.add(str(query.target_page_id))
    if not requested_ids:
        return {}
    requested_uuids = {UUID(page_id) for page_id in requested_ids}
    candidate_uuids = {UUID(page_id) for page_id in page_ids}

    engine = create_db_engine(settings)
    try:
        with Session(engine) as session:
            owned_ids = {
                str(page_id)
                for page_id in session.scalars(
                    select(Page.id).where(
                        Page.user_id == query.user_id,
                        Page.id.in_(requested_uuids),
                    )
                )
            }
            require_user_scoped_pages(requested_ids, owned_ids)

            rows = session.execute(
                select(
                    BrowsingEvent.page_id,
                    BrowsingEvent.occurred_at,
                    BrowsingEvent.session_id,
                ).where(
                    BrowsingEvent.user_id == query.user_id,
                    BrowsingEvent.page_id.in_(candidate_uuids),
                    BrowsingEvent.occurred_at <= query.query_timestamp,
                )
            ).all()
    finally:
        engine.dispose()

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for page_id, occurred_at, session_id in rows:
        grouped[str(page_id)].append({"occurred_at": occurred_at, "session_id": session_id})
    return {
        page_id: history_features(grouped.get(page_id, []), query.query_timestamp)
        for page_id in page_ids
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        for row in rows:
            temporary.write(
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            )
    temporary_path.replace(path)


def prepare_dataset(
    queries: list[QueryRecord], *, api_base_url: str, limit: int, output_dir: Path
) -> tuple[int, int]:
    Settings, _, _ = _backend_imports()
    settings = Settings()
    candidate_rows: list[dict[str, Any]] = []
    status_rows: list[dict[str, Any]] = []

    for query in queries:
        retrieval = {
            source: post_search(api_base_url, endpoint, query, limit)
            for source, endpoint in API_ENDPOINTS.items()
        }
        merged = merge_page_candidates(
            retrieval["semantic"]["results"], retrieval["lexical"]["results"]
        )
        feature_error = None
        histories: dict[str, dict[str, Any]] = {}
        if merged:
            try:
                histories = collect_history(
                    settings, query, [row["candidate_page_id"] for row in merged]
                )
            except Exception as exc:
                # Error class only: DB exception text may include private connection details.
                feature_error = type(exc).__name__
        if feature_error is None:
            for candidate in merged:
                candidate_rows.append(
                    make_candidate_record(
                        query,
                        candidate,
                        histories[candidate["candidate_page_id"]],
                    )
                )

        status_rows.append(
            {
                "dataset_version": DATASET_VERSION,
                "query_id": str(query.query_id),
                "task_group_id": str(query.task_group_id),
                "semantic_status": retrieval["semantic"]["status"],
                "semantic_error": retrieval["semantic"]["error"],
                "semantic_chunk_result_count": len(retrieval["semantic"]["results"]),
                "lexical_status": retrieval["lexical"]["status"],
                "lexical_error": retrieval["lexical"]["error"],
                "lexical_chunk_result_count": len(retrieval["lexical"]["results"]),
                "candidate_page_count": len(merged),
                "target_retrieved": any(
                    str(query.target_page_id) == row["candidate_page_id"]
                    for row in merged
                )
                if query.target_page_id
                else None,
                "feature_status": "ok" if feature_error is None else "failed",
                "feature_error": feature_error,
            }
        )

    candidate_rows.sort(key=lambda row: (row["query_id"], row["candidate_page_id"]))
    status_rows.sort(key=lambda row: row["query_id"])
    _write_jsonl(output_dir / "candidates.jsonl", candidate_rows)
    _write_jsonl(output_dir / "query_status.jsonl", status_rows)
    return len(candidate_rows), len(status_rows)


def validate_candidates(path: Path) -> int:
    count = 0
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                CandidateRecord.model_validate_json(line)
            except ValidationError as exc:
                raise ValueError(f"invalid candidate JSONL at line {line_number}: {exc}") from None
            count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, help="Input query JSONL")
    parser.add_argument("--output-dir", type=Path, help="Ignored local output directory")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--limit", type=int, default=50, choices=range(1, 51))
    parser.add_argument("--validate", type=Path, help="Validate candidate JSONL only")
    args = parser.parse_args()

    try:
        if args.validate:
            print(f"valid candidate rows: {validate_candidates(args.validate)}")
            return 0
        if not args.queries or not args.output_dir:
            parser.error("--queries and --output-dir are required unless --validate is used")
        queries = read_queries(args.queries)
        rows, query_count = prepare_dataset(
            queries,
            api_base_url=args.api_base_url,
            limit=args.limit,
            output_dir=args.output_dir,
        )
        print(f"wrote {rows} candidate rows and {query_count} query statuses")
        return 0
    except (OSError, ValueError, ValidationError) as exc:
        print(f"dataset preparation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
