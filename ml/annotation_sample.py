"""Create and validate a blinded, task-group-stratified annotation sample."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
import sys
from uuid import UUID

from ml.annotation_workflow import _spreadsheet_safe

ROOT = Path(__file__).resolve().parents[1]
LOCAL_DATA = ROOT / "ml" / "local-data"
SOURCE_PATH = LOCAL_DATA / "annotation-v1.csv"
LOOKUP_PATH = LOCAL_DATA / "annotation-page-lookup-v1.csv"
REVIEW_PATH = LOCAL_DATA / "annotation-review-sample-v1.csv"
PROVENANCE_PATH = LOCAL_DATA / "annotation-review-sample-v1-provenance.csv"

SAMPLE_GROUP_IDS = (
    "0d9df87f-cc6b-5466-9dd9-e6f0e1da11ce",
    "3bcc99c3-a606-51c2-8503-92c3fe5ba0f4",
    "61af0672-1f17-57e1-96ab-259de757f2c2",
    "8c6b65b0-b93a-507f-b5c1-94420eadfd12",
    "f499b406-a59a-5492-9d3d-08a4fbfac555",
    "14cf6fd1-31f0-512a-8d0a-26aaae3830bf",
    "1db99e27-df47-5831-bddc-85aef701d194",
    "8287b61f-a75e-5710-86d4-c9d1cec0e991",
    "bf5dc05b-e640-5224-a65d-44d3103adda6",
    "c8d72f84-0200-5104-b336-d328737e9c17",
    "1f9f905b-1019-5552-9c22-2d1d5983942b",
    "73419dd2-ce1f-53f8-97fb-de80ef1a7271",
    "c17e2e24-0ecd-5924-afaf-91d67da55e55",
    "d151052c-7daa-54ad-8c99-4bf5541ffb9d",
    "e798c2ff-360e-5981-90d3-6c99801fdead",
)

REVIEW_FIELDS = (
    "task_group_id",
    "query_id",
    "query_text",
    "candidate_page_id",
    "candidate_title",
    "canonical_url",
    "candidate_domain",
    "content_excerpt",
    "page_lookup_status",
    "human_relevance_grade",
    "human_label_status",
    "human_annotator_id",
    "human_rationale",
    "uncertainty_note",
)

PROVENANCE_FIELDS = (
    "task_group_id",
    "query_id",
    "candidate_page_id",
    "known_target_by_construction",
    "source_relevance_grade",
    "source_label_status",
    "source_label_provenance",
    "candidate_provenance",
    "semantic_status",
    "semantic_present",
    "semantic_page_rank",
    "semantic_score",
    "lexical_status",
    "lexical_present",
    "lexical_page_rank",
    "lexical_score",
    "rrf_status",
    "rrf_rank",
    "rrf_score",
)

IDENTITY_FIELDS = (
    "task_group_id",
    "query_id",
    "query_text",
    "candidate_page_id",
    "candidate_title",
    "canonical_url",
    "candidate_domain",
    "content_excerpt",
    "page_lookup_status",
)
HUMAN_FIELDS = (
    "human_relevance_grade",
    "human_label_status",
    "human_annotator_id",
    "human_rationale",
    "uncertainty_note",
)


def _uuid(value: str, field: str) -> str:
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def _read_csv(path: Path, required_fields: tuple[str, ...] | None = None) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or (required_fields and tuple(reader.fieldnames) != required_fields):
            raise ValueError(f"unexpected CSV header: {path.name}")
        rows = list(reader)
        if any(None in row for row in rows):
            raise ValueError(f"CSV row has more fields than its header: {path.name}")
        return rows


def build_sample_rows(
    source_rows: list[dict[str, str]], lookup_rows: list[dict[str, str]]
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """Return a blind review view and its separate source/rank provenance mapping."""
    lookup: dict[str, dict[str, str]] = {}
    for row in lookup_rows:
        page_id = _uuid(row.get("candidate_page_id", ""), "lookup candidate_page_id")
        if page_id in lookup:
            raise ValueError("duplicate candidate page in lookup report")
        lookup[page_id] = row

    selected: dict[tuple[str, str], dict[str, str]] = {}
    selected_groups: dict[str, set[str]] = {}
    for row in source_rows:
        group_id = _uuid(row.get("task_group_id", ""), "task_group_id")
        if group_id not in SAMPLE_GROUP_IDS:
            continue
        query_id = _uuid(row.get("query_id", ""), "query_id")
        page_id = _uuid(row.get("candidate_page_id", ""), "candidate_page_id")
        pair = (query_id, page_id)
        if pair in selected:
            raise ValueError("duplicate query-page identity in annotation source")
        selected[pair] = row
        selected_groups.setdefault(group_id, set()).add(query_id)

    if set(selected_groups) != set(SAMPLE_GROUP_IDS):
        raise ValueError("annotation source does not contain the 15 planned task groups")
    if len(selected) != 150:
        raise ValueError("planned sample must contain exactly 150 query-page rows")
    if len({page_id for _, page_id in selected}) != 26:
        raise ValueError("planned sample must contain exactly 26 distinct candidate pages")

    for group_id, query_ids in selected_groups.items():
        if len(query_ids) != 2:
            raise ValueError(f"task group must retain exactly two paraphrase queries: {group_id}")
        for query_id in query_ids:
            query_rows = [row for (qid, _), row in selected.items() if qid == query_id]
            if len(query_rows) != 5 or any(row["task_group_id"] != group_id for row in query_rows):
                raise ValueError("each planned query must retain its five original candidate rows")
            targets = {row.get("target_page_id", "") for row in query_rows}
            if len(targets) != 1:
                raise ValueError("query-page rows disagree on their intended target")
            target_id = next(iter(targets))
            target_rows = [row for row in query_rows if row.get("is_target", "").casefold() == "true"]
            if len(target_rows) != 1 or target_rows[0]["candidate_page_id"] != target_id:
                raise ValueError("query must contain exactly its known target page row")

    review_rows: list[dict[str, str]] = []
    provenance_rows: list[dict[str, str]] = []
    ordered_sources = sorted(
        selected.values(),
        key=lambda row: (
            row["task_group_id"],
            row["query_id"],
            int(row.get("annotation_order") or 0),
            row["candidate_page_id"],
        ),
    )
    for source in ordered_sources:
        page = lookup.get(source["candidate_page_id"])
        if page is None:
            raise ValueError("sample candidate page is missing from lookup report")
        if page.get("database_record_found", "").casefold() != "true" or page.get("content_available", "").casefold() != "true":
            raise ValueError("sample candidate page lacks a recovered record or stored content")
        recovered = {
            "candidate_title": page.get("recovered_title", ""),
            "canonical_url": page.get("recovered_canonical_url", ""),
            "candidate_domain": page.get("recovered_domain", ""),
            "content_excerpt": page.get("short_content_excerpt", ""),
        }
        if not all(recovered.values()):
            raise ValueError("sample candidate page is missing title, URL, domain, or content excerpt")
        review = {
            "task_group_id": source["task_group_id"],
            "query_id": source["query_id"],
            "query_text": source["query_text"],
            "candidate_page_id": source["candidate_page_id"],
            **{key: _spreadsheet_safe(value) for key, value in recovered.items()},
            "page_lookup_status": page.get("lookup_status", ""),
            "human_relevance_grade": "",
            "human_label_status": "review_required",
            "human_annotator_id": "",
            "human_rationale": "",
            "uncertainty_note": "",
        }
        review_rows.append(review)
        provenance_rows.append({
            "task_group_id": source["task_group_id"],
            "query_id": source["query_id"],
            "candidate_page_id": source["candidate_page_id"],
            "known_target_by_construction": source["is_target"],
            "source_relevance_grade": source.get("relevance_grade", ""),
            "source_label_status": source.get("label_status", ""),
            "source_label_provenance": source.get("label_provenance", ""),
            "candidate_provenance": source.get("candidate_provenance", ""),
            **{field: source.get(field, "") for field in PROVENANCE_FIELDS[8:]},
        })

    validate_sample_review(review_rows, review_rows)
    return review_rows, provenance_rows


def validate_sample_review(
    rows: list[dict[str, str]], frozen_rows: list[dict[str, str]]
) -> int:
    """Check reviewer edits without exposing or changing frozen source labels."""
    if len(rows) != 150 or len(frozen_rows) != 150:
        raise ValueError("sample review must retain exactly 150 rows")
    expected = {(row["query_id"], row["candidate_page_id"]): row for row in frozen_rows}
    seen: set[tuple[str, str]] = set()
    if len(expected) != 150:
        raise ValueError("frozen sample contains duplicate query-page identities")
    for row in rows:
        if set(row) != set(REVIEW_FIELDS):
            raise ValueError("sample review header does not match blinded schema")
        key = (row["query_id"], row["candidate_page_id"])
        if key in seen or key not in expected:
            raise ValueError("sample review contains duplicate or unknown source identity")
        seen.add(key)
        baseline = expected[key]
        if any(row[field] != baseline[field] for field in IDENTITY_FIELDS):
            raise ValueError("sample identity or recovered page metadata changed")
        status = row["human_label_status"]
        grade = row["human_relevance_grade"].strip()
        annotator = row["human_annotator_id"].strip()
        rationale = row["human_rationale"].strip()
        uncertainty = row["uncertainty_note"].strip()
        if len(rationale) > 500 or len(uncertainty) > 500:
            raise ValueError("rationale and uncertainty note must be at most 500 characters")
        if status == "review_required":
            if grade or annotator or rationale or uncertainty:
                raise ValueError("review_required rows must have blank human judgment fields")
        elif status == "uncertain":
            if grade or not annotator or not uncertainty or rationale:
                raise ValueError("uncertain rows need annotator and uncertainty note, but no grade")
        elif status == "independently_judged":
            if grade not in {"0", "1", "2", "3"} or not annotator or not rationale or uncertainty:
                raise ValueError("independently_judged rows need grade 0-3, annotator, and rationale")
        else:
            raise ValueError("invalid human_label_status")
    if seen != set(expected):
        raise ValueError("sample review is missing one or more original query-page rows")
    return len(rows)


def _write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def build_files(source: Path, lookup: Path, review: Path, provenance: Path) -> int:
    protected = {source.resolve(), lookup.resolve()}
    if review.resolve() == provenance.resolve() or review.resolve() in protected or provenance.resolve() in protected:
        raise ValueError("outputs must be distinct from each other and the frozen inputs")
    if review.exists() or provenance.exists():
        raise FileExistsError("sample output exists; refusing to overwrite review or provenance file")
    review_rows, provenance_rows = build_sample_rows(_read_csv(source), _read_csv(lookup))
    for output in (review, provenance):
        try:
            output.resolve().relative_to(LOCAL_DATA.resolve())
        except ValueError as exc:
            raise ValueError("sample outputs must stay under ml/local-data/") from exc
        output.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(review, REVIEW_FIELDS, review_rows)
    _write_csv(provenance, PROVENANCE_FIELDS, provenance_rows)
    return len(review_rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_PATH)
    parser.add_argument("--lookup", type=Path, default=LOOKUP_PATH)
    parser.add_argument("--review", type=Path, default=REVIEW_PATH)
    parser.add_argument("--provenance", type=Path, default=PROVENANCE_PATH)
    parser.add_argument("--validate", action="store_true", help="validate an edited sample against frozen inputs")
    args = parser.parse_args()
    try:
        if args.validate:
            expected, _ = build_sample_rows(_read_csv(args.source), _read_csv(args.lookup))
            count = validate_sample_review(_read_csv(args.review, REVIEW_FIELDS), expected)
            print(f"valid blinded review sample: {count} rows; identities and recovered content preserved")
            return 0
        count = build_files(args.source, args.lookup, args.review, args.provenance)
        print(f"created blinded review sample ({count} rows) and separate provenance mapping")
        return 0
    except (OSError, ValueError, csv.Error) as exc:
        print(f"annotation sample failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
