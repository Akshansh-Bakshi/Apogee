"""Build and validate a local, frozen-source relevance annotation CSV."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import sys
from typing import Any

from ml.annotation import ANNOTATION_FIELDS, build_annotation_rows, validate_annotation_rows


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as stream:
        return [json.loads(line) for line in stream if line.strip()]


def read_page_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Read target IDs, titles, and domains already documented in the review notes."""
    text = path.read_text(encoding="utf-8")
    sections = re.split(r"(?m)^## ", text)[1:]
    metadata: dict[str, dict[str, str]] = {}
    for section in sections:
        lines = section.splitlines()
        if not lines:
            continue
        title = lines[0].strip()
        match = re.search(r"\*\*Target page:\*\* `([^`]+)`.*?·\s*([^\s]+)", section)
        if match:
            metadata[match.group(1)] = {"title": title, "domain": match.group(2)}
    return metadata


def check_frozen_evaluation(rows: list[dict[str, Any]], evaluation: list[dict[str, Any]]) -> None:
    """Check derived target ranks against the already-saved ML-3 outcomes."""
    by_query = {row["query_id"]: row for row in evaluation}
    target_rows = {row["query_id"]: row for row in rows if row["is_target"]}
    if len(by_query) != len(evaluation) or set(by_query) != set(target_rows):
        raise ValueError("frozen evaluation rows do not match annotation query targets")
    for query_id, expected in by_query.items():
        actual = target_rows[query_id]
        for source in ("semantic", "lexical"):
            if actual[f"{source}_page_rank"] != expected[f"{source}_page_rank"]:
                raise ValueError(f"{source} target page rank differs from frozen evaluation")
        if actual["rrf_rank"] != expected["hybrid_page_rank"]:
            raise ValueError("RRF target rank differs from frozen evaluation")


def _parse_csv_row(row: dict[str, str]) -> dict[str, Any]:
    parsed: dict[str, Any] = dict(row)
    for field in ("is_target", "semantic_present", "lexical_present"):
        if parsed[field] not in {"true", "false"}:
            raise ValueError(f"invalid boolean in {field}")
        parsed[field] = parsed[field] == "true"
    for field in (
        "annotation_order", "semantic_best_chunk_rank", "semantic_page_rank",
        "lexical_best_chunk_rank", "lexical_page_rank", "rrf_rank", "relevance_grade",
        "human_relevance_grade",
    ):
        if parsed[field] == "":
            parsed[field] = "" if field in {"relevance_grade", "human_relevance_grade"} else None
        else:
            parsed[field] = int(parsed[field])
    for field in ("semantic_score", "lexical_score", "rrf_score"):
        parsed[field] = float(parsed[field]) if parsed[field] else None
    return parsed


def validate_csv(path: Path) -> int:
    with path.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != ANNOTATION_FIELDS:
            raise ValueError("annotation CSV header does not match the required schema")
        rows = [_parse_csv_row(row) for row in reader]
    validate_annotation_rows(rows)
    return len(rows)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=ANNOTATION_FIELDS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "" if value is None else str(value).lower() if isinstance(value, bool) else value
                             for key, value in row.items()})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path)
    parser.add_argument("--candidates", type=Path)
    parser.add_argument("--statuses", type=Path)
    parser.add_argument("--evaluation", type=Path)
    parser.add_argument("--review", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args()
    try:
        if args.validate:
            print(f"valid annotation rows: {validate_csv(args.validate)}")
            return 0
        required = (args.queries, args.candidates, args.statuses, args.evaluation, args.review, args.output)
        if any(value is None for value in required):
            parser.error("--queries, --candidates, --statuses, --evaluation, --review, and --output are required")
        rows = build_annotation_rows(
            read_jsonl(args.queries), read_jsonl(args.candidates), read_jsonl(args.statuses),
            page_metadata=read_page_metadata(args.review),
        )
        check_frozen_evaluation(rows, read_jsonl(args.evaluation))
        write_csv(args.output, rows)
        count = validate_csv(args.output)
        targets = sum(row["label_status"] == "known_target_by_construction" for row in rows)
        review = count - targets
        print(f"wrote {count} rows: {targets} known targets by construction, {review} requiring review")
        print(f"validated {count} annotation rows against the saved evaluation")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"annotation preparation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
