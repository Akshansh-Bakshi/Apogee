"""Resolve annotation candidate IDs to page metadata and stored chunk excerpts."""

from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
import re
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

LOOKUP_FIELDS = (
    "candidate_page_id",
    "candidate_title_from_annotation",
    "candidate_domain_from_annotation",
    "database_record_found",
    "recovered_title",
    "recovered_canonical_url",
    "recovered_domain",
    "first_seen_at",
    "last_seen_at",
    "created_at",
    "updated_at",
    "chunk_count",
    "content_available",
    "short_content_excerpt",
    "lookup_status",
)
EXCERPT_LIMIT = 360


def read_annotation_pages(path: Path) -> dict[str, dict[str, str]]:
    """Read unique page IDs and nonempty title/domain metadata without query text."""
    pages: dict[str, dict[str, str]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or "candidate_page_id" not in reader.fieldnames:
            raise ValueError("annotation CSV is missing candidate_page_id")
        for row in reader:
            try:
                page_id = str(UUID(row["candidate_page_id"]))
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValueError("annotation CSV contains an invalid candidate_page_id") from exc
            current = pages.setdefault(page_id, {"title": "", "domain": ""})
            for output_field, input_field in (
                ("title", "candidate_title"),
                ("domain", "candidate_domain"),
            ):
                value = (row.get(input_field) or "").strip()
                if value and current[output_field] and value != current[output_field]:
                    raise ValueError(f"conflicting {input_field} values for candidate page")
                if value:
                    current[output_field] = value
    return pages


def _iso(value: Any) -> str:
    return value.isoformat() if isinstance(value, (datetime, date)) else ""


def _excerpt(chunks: list[tuple[int, str]]) -> str:
    for _, value in sorted(chunks, key=lambda item: item[0]):
        if value and value.strip():
            # Captured page text is untrusted. This function only normalizes and truncates it;
            # it never interprets or executes any content.
            normalized = re.sub(r"[\x00-\x1f\x7f]+", " ", value)
            normalized = re.sub(r"\s+", " ", normalized).strip()
            if normalized:
                return normalized[:EXCERPT_LIMIT]
    return ""


def build_lookup_rows(
    annotation_pages: dict[str, dict[str, str]],
    database_pages: dict[str, dict[str, Any]] | None,
    *,
    database_error: str | None = None,
) -> list[dict[str, Any]]:
    """Produce one report row per input page; unknown database state stays explicitly unknown."""
    rows: list[dict[str, Any]] = []
    if database_pages is None and not database_error:
        raise ValueError("database_pages or database_error is required")
    for page_id in sorted(annotation_pages):
        annotation = annotation_pages[page_id]
        base: dict[str, Any] = {
            "candidate_page_id": page_id,
            "candidate_title_from_annotation": annotation.get("title", ""),
            "candidate_domain_from_annotation": annotation.get("domain", ""),
            "database_record_found": "",
            "recovered_title": "",
            "recovered_canonical_url": "",
            "recovered_domain": "",
            "first_seen_at": "",
            "last_seen_at": "",
            "created_at": "",
            "updated_at": "",
            "chunk_count": "",
            "content_available": "",
            "short_content_excerpt": "",
            "lookup_status": f"database_unavailable:{database_error or 'unknown'}",
        }
        if database_pages is not None and page_id not in database_pages:
            base["database_record_found"] = False
            base["chunk_count"] = ""
            base["content_available"] = False
            base["lookup_status"] = "missing_database_record"
        elif database_pages is not None:
            record = database_pages[page_id]
            chunks = record.get("chunks", [])
            excerpt = _excerpt(chunks)
            content_available = bool(excerpt)
            base.update({
                "database_record_found": True,
                "recovered_title": record.get("title") or "",
                "recovered_canonical_url": record.get("canonical_url") or "",
                "recovered_domain": record.get("domain") or "",
                "first_seen_at": _iso(record.get("first_seen_at")),
                "last_seen_at": _iso(record.get("last_seen_at")),
                "created_at": _iso(record.get("created_at")),
                "updated_at": _iso(record.get("updated_at")),
                "chunk_count": len(chunks),
                "content_available": content_available,
                "short_content_excerpt": excerpt,
                "lookup_status": "resolved_with_content" if content_available else "resolved_no_content",
            })
        rows.append(base)
    return rows


def _backend_imports() -> tuple[Any, Any, Any, Any]:
    backend_path = Path(__file__).resolve().parents[1] / "backend"
    if str(backend_path) not in sys.path:
        sys.path.insert(0, str(backend_path))
    from app.core.config import Settings
    from app.db.session import create_db_engine
    from app.models import Page, PageChunk

    return Settings, create_db_engine, Page, PageChunk


def fetch_database_pages(settings: Any, page_ids: list[str]) -> dict[str, dict[str, Any]]:
    """Read selected pages and chunks in an explicitly read-only PostgreSQL transaction."""
    Settings, create_db_engine, Page, PageChunk = _backend_imports()
    del Settings
    if not page_ids:
        return {}
    requested = {UUID(page_id) for page_id in page_ids}
    engine = create_db_engine(settings)
    try:
        with Session(engine) as session:
            with session.begin():
                session.execute(text("SET TRANSACTION READ ONLY"))
                result = session.execute(
                    select(
                        Page.id,
                        Page.title,
                        Page.canonical_url,
                        Page.domain,
                        Page.first_seen_at,
                        Page.last_seen_at,
                        Page.created_at,
                        Page.updated_at,
                        PageChunk.chunk_index,
                        PageChunk.text,
                    )
                    .select_from(Page)
                    .outerjoin(PageChunk, PageChunk.page_id == Page.id)
                    .where(Page.id.in_(requested))
                    .order_by(Page.id, PageChunk.chunk_index)
                )
                pages: dict[str, dict[str, Any]] = {}
                for row in result:
                    page_id = str(row.id)
                    record = pages.setdefault(page_id, {
                        "title": row.title,
                        "canonical_url": row.canonical_url,
                        "domain": row.domain,
                        "first_seen_at": row.first_seen_at,
                        "last_seen_at": row.last_seen_at,
                        "created_at": row.created_at,
                        "updated_at": row.updated_at,
                        "chunks": [],
                    })
                    if row.chunk_index is not None:
                        record["chunks"].append((row.chunk_index, row.text or ""))
                return pages
    finally:
        engine.dispose()


def write_lookup_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=LOOKUP_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _safe_database_reason(exc: Exception) -> str:
    message = str(getattr(exc, "orig", exc)).lower()
    if "connection refused" in message:
        return "connection_refused"
    if "could not translate host name" in message or "name or service not known" in message:
        return "host_resolution_failed"
    if "password authentication failed" in message or "authentication failed" in message:
        return "authentication_failed"
    if "database" in message and "does not exist" in message:
        return "database_not_found"
    if "timeout" in message or "timed out" in message:
        return "connection_timeout"
    return type(exc).__name__


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotation", type=Path, default=Path("ml/local-data/annotation-v1.csv"))
    parser.add_argument("--output", type=Path, default=Path("ml/local-data/annotation-page-lookup-v1.csv"))
    args = parser.parse_args()
    try:
        annotation_pages = read_annotation_pages(args.annotation)
        try:
            Settings, _, _, _ = _backend_imports()
            settings = Settings()
            database_pages = fetch_database_pages(settings, list(annotation_pages))
            rows = build_lookup_rows(annotation_pages, database_pages)
        except Exception as exc:
            # Connection/configuration details can contain private settings; retain only a
            # sanitized reason code, never the exception message or connection URL.
            reason = _safe_database_reason(exc)
            rows = build_lookup_rows(annotation_pages, None, database_error=reason)
            print(f"database lookup unavailable: {reason}", file=sys.stderr)
        write_lookup_csv(args.output, rows)
        resolved = sum(row["database_record_found"] is True for row in rows)
        content = sum(row["content_available"] is True for row in rows)
        missing = sum(row["lookup_status"] == "missing_database_record" for row in rows)
        print(f"wrote {len(rows)} page rows; resolved={resolved}; content_available={content}; missing={missing}")
        return 0
    except (OSError, ValueError) as exc:
        print(f"page lookup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
