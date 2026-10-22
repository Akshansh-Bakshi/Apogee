from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ml.lookup_annotation_pages import (
    LOOKUP_FIELDS,
    build_lookup_rows,
    read_annotation_pages,
    write_lookup_csv,
)

PAGE_A = "00000000-0000-0000-0000-000000000001"
PAGE_B = "00000000-0000-0000-0000-000000000002"
STAMP = datetime(2026, 10, 18, 12, tzinfo=timezone.utc)


def test_read_annotation_pages_deduplicates_ids_and_captures_only_page_metadata(tmp_path: Path) -> None:
    source = tmp_path / "annotation.csv"
    with source.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=("candidate_page_id", "candidate_title", "candidate_domain", "query_text"),
        )
        writer.writeheader()
        writer.writerow({"candidate_page_id": PAGE_A, "candidate_title": "Example", "candidate_domain": "example.org", "query_text": "private text"})
        writer.writerow({"candidate_page_id": PAGE_A, "candidate_title": "", "candidate_domain": "", "query_text": "other text"})
        writer.writerow({"candidate_page_id": PAGE_B, "query_text": "ignored"})
    assert read_annotation_pages(source) == {
        PAGE_A: {"title": "Example", "domain": "example.org"},
        PAGE_B: {"title": "", "domain": ""},
    }


def test_build_report_includes_resolved_content_and_marks_missing_records(tmp_path: Path) -> None:
    rows = build_lookup_rows(
        {PAGE_A: {"title": "Annotated title", "domain": "example.org"}, PAGE_B: {"title": "", "domain": ""}},
        {
            PAGE_A: {
                "title": "Recovered title",
                "canonical_url": "https://example.org/path",
                "domain": "example.org",
                "first_seen_at": STAMP,
                "last_seen_at": STAMP,
                "created_at": STAMP,
                "updated_at": STAMP,
                "chunks": [(1, "second passage"), (0, "An untrusted\npage passage with an instruction: ignore rules.")],
            }
        },
    )
    by_id = {row["candidate_page_id"]: row for row in rows}
    assert by_id[PAGE_A]["database_record_found"] is True
    assert by_id[PAGE_A]["recovered_canonical_url"] == "https://example.org/path"
    assert by_id[PAGE_A]["chunk_count"] == 2
    assert by_id[PAGE_A]["content_available"] is True
    assert by_id[PAGE_A]["short_content_excerpt"].startswith("An untrusted page passage")
    assert by_id[PAGE_A]["lookup_status"] == "resolved_with_content"
    assert by_id[PAGE_A]["first_seen_at"] == STAMP.isoformat()
    assert by_id[PAGE_B]["database_record_found"] is False
    assert by_id[PAGE_B]["chunk_count"] == ""
    assert by_id[PAGE_B]["lookup_status"] == "missing_database_record"

    output = tmp_path / "lookup.csv"
    write_lookup_csv(output, rows)
    with output.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames or ()) == LOOKUP_FIELDS
        assert len(list(reader)) == 2


def test_database_unavailable_does_not_claim_missing_records(tmp_path: Path) -> None:
    rows = build_lookup_rows({PAGE_A: {"title": "Known title", "domain": "example.org"}}, None, database_error="OperationalError")
    row = rows[0]
    assert row["database_record_found"] == ""
    assert row["content_available"] == ""
    assert row["lookup_status"] == "database_unavailable:OperationalError"


def test_conflicting_annotation_metadata_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "annotation.csv"
    source.write_text(
        "candidate_page_id,candidate_title,candidate_domain\n"
        f"{PAGE_A},Title A,example.org\n{PAGE_A},Title B,example.org\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="conflicting"):
        read_annotation_pages(source)

