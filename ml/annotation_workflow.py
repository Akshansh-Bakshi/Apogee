"""Spreadsheet-based human annotation workflow with immutable-source validation."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
import sys
import tempfile
from typing import Any
from uuid import UUID

from ml.annotation import ANNOTATION_FIELDS, validate_annotation_rows
from ml.lookup_annotation_pages import LOOKUP_FIELDS
from ml.prepare_annotation import _parse_csv_row

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA = ROOT / "ml" / "local-data"
SOURCE_PATH = LOCAL_DATA / "annotation-v1.csv"
LOOKUP_PATH = LOCAL_DATA / "annotation-page-lookup-v1.csv"
REVIEW_PATH = LOCAL_DATA / "annotation-review-v1.csv"
EXPORT_PATH = LOCAL_DATA / "annotation-v1-human-labels.jsonl"

EDITABLE_SOURCE_FIELDS = {
    "human_relevance_grade",
    "human_label_status",
    "human_label_provenance",
}
REVIEW_FIELDS = (
    "review_title",
    "review_domain",
    "canonical_url",
    "content_excerpt",
    "page_lookup_status",
    "page_chunk_count",
    "page_content_available",
    "database_record_found",
    "page_first_seen_at",
    "page_last_seen_at",
    "page_created_at",
    "page_updated_at",
    "human_annotator_id",
    "human_rationale",
    "uncertainty_note",
)
REVIEW_FIRST_FIELDS = (
    "query_text",
    "task_group_id",
    "query_id",
    "candidate_page_id",
    "review_title",
    "canonical_url",
    "review_domain",
    "content_excerpt",
    "page_lookup_status",
    "human_label_status",
    "human_relevance_grade",
    "human_annotator_id",
    "human_rationale",
    "uncertainty_note",
)
WORKFLOW_FIELDS = REVIEW_FIRST_FIELDS + tuple(
    field for field in ANNOTATION_FIELDS if field not in REVIEW_FIRST_FIELDS
) + tuple(
    field for field in REVIEW_FIELDS if field not in REVIEW_FIRST_FIELDS
)


def _spreadsheet_safe(value: str) -> str:
    """Keep untrusted page-derived strings from being interpreted as spreadsheet formulas."""
    if value.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def _read_csv(path: Path) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path.name}")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError(f"CSV row has more fields than its header: {path.name}")
        return tuple(reader.fieldnames), rows


def _uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def _index_by_page(rows: list[dict[str, str]], field: str) -> dict[str, dict[str, str]]:
    indexed: dict[str, dict[str, str]] = {}
    for row in rows:
        page_id = _uuid(row.get(field, ""), field)
        if page_id in indexed:
            raise ValueError(f"duplicate {field} in lookup inputs")
        indexed[page_id] = row
    return indexed


def _metadata_by_page(lookup_rows: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    by_page = _index_by_page(lookup_rows, "candidate_page_id")
    return by_page


def initialize_review_rows(
    source_rows: list[dict[str, str]], lookup_rows: list[dict[str, str]]
) -> list[dict[str, str]]:
    source_by_pair: dict[tuple[str, str], dict[str, str]] = {}
    for source in source_rows:
        pair = (
            _uuid(source.get("query_id", ""), "query_id"),
            _uuid(source.get("candidate_page_id", ""), "candidate_page_id"),
        )
        if pair in source_by_pair:
            raise ValueError("duplicate query-page row in annotation source")
        source_by_pair[pair] = source
    page_metadata = _metadata_by_page(lookup_rows)
    candidate_ids = {page_id for _, page_id in source_by_pair}
    if set(page_metadata) != candidate_ids:
        raise ValueError("page lookup IDs do not exactly match annotation candidate IDs")

    output = []
    for pair in sorted(source_by_pair):
        source = dict(source_by_pair[pair])
        page = page_metadata[pair[1]]
        source.update({
            "review_title": _spreadsheet_safe(page.get("recovered_title") or page.get("candidate_title_from_annotation") or source.get("candidate_title", "")),
            "review_domain": _spreadsheet_safe(page.get("recovered_domain") or page.get("candidate_domain_from_annotation") or source.get("candidate_domain", "")),
            "canonical_url": _spreadsheet_safe(page.get("recovered_canonical_url", "")),
            "content_excerpt": _spreadsheet_safe(page.get("short_content_excerpt", "")),
            "page_lookup_status": page.get("lookup_status", ""),
            "page_chunk_count": page.get("chunk_count", ""),
            "page_content_available": page.get("content_available", ""),
            "database_record_found": page.get("database_record_found", ""),
            "page_first_seen_at": page.get("first_seen_at", ""),
            "page_last_seen_at": page.get("last_seen_at", ""),
            "page_created_at": page.get("created_at", ""),
            "page_updated_at": page.get("updated_at", ""),
            "human_annotator_id": "",
            "human_rationale": "",
            "uncertainty_note": "",
        })
        output.append(source)
    return output


def _editable_annotation(row: dict[str, str]) -> dict[str, Any]:
    projected = {field: row.get(field, "") for field in ANNOTATION_FIELDS}
    for field in ("is_target", "semantic_present", "lexical_present"):
        projected[field] = projected[field].lower()
    parsed = _parse_csv_row(projected)
    return parsed


def _read_validated_source(path: Path) -> list[dict[str, str]]:
    header, rows = _read_csv(path)
    if header != ANNOTATION_FIELDS:
        raise ValueError("annotation source header does not match its frozen schema")
    if len(rows) != 500:
        raise ValueError("expected exactly 500 validated annotation source rows")
    validate_annotation_rows([_editable_annotation(row) for row in rows])
    return rows


def _same_source_value(field: str, actual: str, expected: str) -> bool:
    if field in {"is_target", "semantic_present", "lexical_present", "page_content_available", "database_record_found"}:
        return actual.casefold() == expected.casefold()
    if field in {"semantic_score", "lexical_score", "rrf_score"}:
        if not actual or not expected:
            return actual == expected
        try:
            return math.isclose(float(actual), float(expected), rel_tol=1e-12, abs_tol=1e-15)
        except ValueError:
            return False
    return actual == expected


def _validate_human_fields(row: dict[str, str]) -> None:
    status = row.get("human_label_status", "")
    grade = row.get("human_relevance_grade", "")
    annotator = (row.get("human_annotator_id") or "").strip()
    rationale = (row.get("human_rationale") or "").strip()
    uncertainty = (row.get("uncertainty_note") or "").strip()
    provenance = row.get("human_label_provenance", "")

    if rationale and len(rationale) > 500:
        raise ValueError("human_rationale must be at most 500 characters")
    if uncertainty and len(uncertainty) > 500:
        raise ValueError("uncertainty_note must be at most 500 characters")

    if status == "review_required":
        if grade or provenance or annotator or rationale or uncertainty:
            raise ValueError("review_required rows must remain blank; use uncertain for a pending review note")
    elif status == "uncertain":
        if grade or provenance:
            raise ValueError("uncertain rows must not have a relevance grade")
        if not annotator or not uncertainty:
            raise ValueError("uncertain rows require an annotator ID and uncertainty_note")
    elif status == "independently_judged":
        if grade not in {"0", "1", "2", "3"}:
            raise ValueError("independently_judged rows require grade 0, 1, 2, or 3")
        if not annotator or not rationale:
            raise ValueError("independently_judged rows require an annotator ID and short rationale")
        if provenance != annotator:
            raise ValueError("human_label_provenance must match human_annotator_id")
        if uncertainty:
            raise ValueError("clear uncertainty_note before marking a row independently_judged")
    else:
        raise ValueError("human_label_status must be review_required, uncertain, or independently_judged")


def _check_lookup_header(header: tuple[str, ...]) -> None:
    if header != LOOKUP_FIELDS:
        raise ValueError("page lookup CSV header does not match the expected schema")


def build_review_file(source_path: Path, lookup_path: Path, output_path: Path) -> int:
    if output_path.exists():
        raise FileExistsError("review CSV already exists; it will not be overwritten")
    source_rows = _read_validated_source(source_path)
    lookup_header, lookup_rows = _read_csv(lookup_path)
    _check_lookup_header(lookup_header)
    rows = initialize_review_rows(source_rows, lookup_rows)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=WORKFLOW_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    validate_review(source_path, lookup_path, output_path)
    return len(rows)


def validate_review(source_path: Path, lookup_path: Path, review_path: Path) -> int:
    source_rows = _read_validated_source(source_path)
    lookup_header, lookup_rows = _read_csv(lookup_path)
    review_header, review_rows = _read_csv(review_path)
    _check_lookup_header(lookup_header)
    if review_header != WORKFLOW_FIELDS:
        raise ValueError("review CSV header does not match the workflow schema")

    baseline = initialize_review_rows(source_rows, lookup_rows)
    baseline_by_pair = {
        (row["query_id"], row["candidate_page_id"]): row for row in baseline
    }
    seen: set[tuple[str, str]] = set()
    projected: list[dict[str, Any]] = []
    for row in review_rows:
        pair = (
            _uuid(row.get("query_id", ""), "query_id"),
            _uuid(row.get("candidate_page_id", ""), "candidate_page_id"),
        )
        if pair in seen:
            raise ValueError("duplicate query-page row in review CSV")
        if pair not in baseline_by_pair:
            raise ValueError("review CSV contains an unknown query-page row")
        seen.add(pair)
        frozen = baseline_by_pair[pair]
        for field in ANNOTATION_FIELDS:
            if (field not in EDITABLE_SOURCE_FIELDS
                    and not _same_source_value(field, row.get(field, ""), frozen.get(field, ""))):
                raise ValueError(f"frozen annotation source field changed: {field}")
        for field in REVIEW_FIELDS:
            if field not in {"human_annotator_id", "human_rationale", "uncertainty_note"}:
                if not _same_source_value(field, row.get(field, ""), frozen.get(field, "")):
                    raise ValueError(f"page lookup/source metadata changed: {field}")
        _validate_human_fields(row)
        projected.append(_editable_annotation(row))

    if seen != set(baseline_by_pair):
        raise ValueError("review CSV is missing one or more original query-page rows")
    validate_annotation_rows(projected)
    return len(review_rows)


def export_judgments(source_path: Path, lookup_path: Path, review_path: Path, output_path: Path) -> int:
    if output_path.resolve() in {source_path.resolve(), lookup_path.resolve(), review_path.resolve()}:
        raise ValueError("export output must be different from all input/source files")
    validate_review(source_path, lookup_path, review_path)
    _, rows = _read_csv(review_path)
    judged = [row for row in rows if row["human_label_status"] == "independently_judged"]
    if not judged:
        raise ValueError("no independently judged rows to export")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=output_path.parent, delete=False
    ) as temporary:
        temporary_path = Path(temporary.name)
        for row in sorted(judged, key=lambda item: (item["query_id"], item["candidate_page_id"])):
            record = {
                "query_id": row["query_id"],
                "task_group_id": row["task_group_id"],
                "target_page_id": row["target_page_id"],
                "candidate_page_id": row["candidate_page_id"],
                "source_relevance_grade": int(row["relevance_grade"]) if row["relevance_grade"] else None,
                "source_label_status": row["label_status"],
                "source_label_provenance": row["label_provenance"],
                "human_relevance_grade": int(row["human_relevance_grade"]),
                "human_label_status": row["human_label_status"],
                "human_label_provenance": row["human_label_provenance"],
                "human_annotator_id": row["human_annotator_id"].strip(),
                "human_rationale": row["human_rationale"].strip(),
            }
            temporary.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    temporary_path.replace(output_path)
    return len(judged)


def _require_local_output(path: Path) -> None:
    resolved = path.resolve()
    try:
        resolved.relative_to(LOCAL_DATA.resolve())
    except ValueError as exc:
        raise ValueError("workflow outputs must stay under ml/local-data/") from exc


def _require_distinct_output(path: Path, protected: tuple[Path, ...]) -> None:
    resolved = path.resolve()
    if any(resolved == item.resolve() for item in protected):
        raise ValueError("output path must be different from all input/source files")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init_parser = commands.add_parser("init", help="create an enriched review CSV once")
    init_parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    init_parser.add_argument("--lookup", type=Path, default=LOOKUP_PATH)
    init_parser.add_argument("--output", type=Path, default=REVIEW_PATH)
    validate_parser = commands.add_parser("validate", help="validate a reviewer-edited CSV")
    validate_parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    validate_parser.add_argument("--lookup", type=Path, default=LOOKUP_PATH)
    validate_parser.add_argument("--input", type=Path, default=REVIEW_PATH)
    export_parser = commands.add_parser("export", help="export only independently judged labels")
    export_parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    export_parser.add_argument("--lookup", type=Path, default=LOOKUP_PATH)
    export_parser.add_argument("--input", type=Path, default=REVIEW_PATH)
    export_parser.add_argument("--output", type=Path, default=EXPORT_PATH)
    args = parser.parse_args()
    try:
        if args.command == "init":
            _require_local_output(args.output)
            _require_distinct_output(args.output, (args.source, args.lookup))
            count = build_review_file(args.source, args.lookup, args.output)
            print(f"created review CSV with {count} original query-page rows: {args.output}")
        elif args.command == "validate":
            count = validate_review(args.source, args.lookup, args.input)
            print(f"valid review CSV: {count} rows; source identities and metadata preserved")
        else:
            _require_local_output(args.output)
            _require_distinct_output(args.output, (args.source, args.lookup, args.input))
            count = export_judgments(args.source, args.lookup, args.input, args.output)
            print(f"exported {count} independently judged labels: {args.output}")
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        print(f"annotation workflow failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
