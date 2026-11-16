"""Label-blind V2 readiness gate. Never trains or reads test target values."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

from ml.synthetic_next_topic_v2 import (
    FEATURES, FEATURE_VERSION, SPLIT_FAMILIES, VERSION,
    extract_candidate_features, taxonomy,
)

# Fixed before running the audit: every topic must have the same missing-recency mask;
# at most one page, two visits, and seven days difference per topic. No fitted scaler.
TOLERANCES = {"pages": 1, "visits": 2, "recency_days": 7}


def observable_profile(scenario):
    as_of = datetime.fromisoformat(scenario["as_of"])
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("naive observation cutoff")
    _, topics = taxonomy()
    values = []
    for topic in topics:
        activity = scenario["topic_activity"][topic.id]
        last = activity["last_seen_at"]
        last = datetime.fromisoformat(last) if last is not None else None
        if last is not None and (last.tzinfo is None or last > as_of):
            raise ValueError("future or naive activity timestamp")
        age = None if last is None else (as_of - last).total_seconds() / 86400
        values.append((activity["distinct_pages"], activity["visits"], age))
    return tuple(values)


def profiles_close(left, right):
    return all(
        abs(a[0] - b[0]) <= TOLERANCES["pages"]
        and abs(a[1] - b[1]) <= TOLERANCES["visits"]
        and ((a[2] is None and b[2] is None) or (
            a[2] is not None and b[2] is not None
            and abs(a[2] - b[2]) <= TOLERANCES["recency_days"]
        ))
        for a, b in zip(left, right)
    )


def duplicate_report(scenarios):
    profiles = [observable_profile(row) for row in scenarios]
    counts = Counter()
    examples = []
    for i, j in combinations(range(len(scenarios)), 2):
        left, right = scenarios[i], scenarios[j]
        exact = profiles[i] == profiles[j]
        near = profiles_close(profiles[i], profiles[j])
        if not near:
            continue
        kind = "exact" if exact else "near_nonexact"
        counts[kind] += 1
        if left["scenario_family"] != right["scenario_family"]:
            counts[f"{kind}_cross_family"] += 1
        if left["split"] != right["split"]:
            counts[f"{kind}_cross_split"] += 1
        if len(examples) < 10:
            examples.append([left["scenario_id"], right["scenario_id"], kind])
    return {"tolerances": TOLERANCES, "pairs_examined": len(scenarios)*(len(scenarios)-1)//2,
            "counts": {name: counts[name] for name in (
                "exact", "near_nonexact", "exact_cross_family", "near_nonexact_cross_family",
                "exact_cross_split", "near_nonexact_cross_split")}, "examples": examples}


def read_feature_projection(path):
    # JSON contains test targets, but no target is accessed, retained, printed or evaluated.
    # Project immediately to feature and grouping fields, then discard the parsed record.
    fields = (*FEATURES, "scenario_id", "scenario_family", "split", "synthetic",
              "dataset_version", "feature_schema_version", "taxonomy_version")
    rows = []
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            parsed = json.loads(line)
            rows.append({field: parsed[field] for field in fields})
    return rows


def audit(directory):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    checksums = {name: hashlib.sha256((directory/name).read_bytes()).hexdigest() == digest
                 for name, digest in manifest["artifacts"].items()}
    scenarios = [json.loads(line) for line in (directory/"scenarios.jsonl").read_text(
        encoding="utf-8").splitlines()]
    candidates = read_feature_projection(directory/"candidates.jsonl")
    by_id = {item["scenario_id"]: item for item in scenarios}
    tax_version, topics = taxonomy()
    topic_ids = {topic.id for topic in topics}
    problems = []
    if not all(checksums.values()):
        problems.append("Artifact checksum mismatch")
    if manifest["feature_fields"] != list(FEATURES):
        problems.append("Frozen feature list mismatch")
    if len(by_id) != len(scenarios) or len(scenarios) != 360 or len(candidates) != 2880:
        problems.append("Scenario/candidate counts or IDs invalid")
    if manifest["dataset_version"] != VERSION or manifest["taxonomy_version"] != tax_version:
        problems.append("Manifest version mismatch")
    split_ids = []
    split_counts = {}
    for split, families in SPLIT_FAMILIES.items():
        payload = json.loads((directory/f"split-{split}.json").read_text(encoding="utf-8"))
        expected = {item["scenario_id"] for item in scenarios if item["split"] == split}
        if set(payload["scenario_ids"]) != expected or payload["scenario_families"] != list(families):
            problems.append(f"Invalid {split} manifest")
        if split == "test" and payload["frozen_before_training"] is not True:
            problems.append("Test freeze flag missing")
        split_ids.extend(payload["scenario_ids"])
        split_counts[split] = {"scenarios": len(expected), "families": len(families)}
    if len(split_ids) != len(set(split_ids)) or set(split_ids) != set(by_id):
        problems.append("Split overlap or missing scenarios")
    pairs = set()
    family_splits = {}
    parity_errors = 0
    for row in candidates:
        pair = row["scenario_id"], row["candidate_topic_id"]
        if pair in pairs or pair[1] not in topic_ids:
            problems.append("Duplicate pair or invalid topic")
        pairs.add(pair)
        scenario = by_id[pair[0]]
        if any(row[key] != scenario[key] for key in ("split", "scenario_family")):
            problems.append("Candidate grouping mismatch")
        if (row["synthetic"] is not True or row["dataset_version"] != VERSION
                or row["feature_schema_version"] != FEATURE_VERSION
                or row["taxonomy_version"] != tax_version):
            problems.append("Candidate metadata mismatch")
        family_splits.setdefault(row["scenario_family"], set()).add(row["split"])
        activity = {key: {**value, "last_seen_at": datetime.fromisoformat(value["last_seen_at"])
                    if value["last_seen_at"] else None} for key, value in scenario["topic_activity"].items()}
        expected = extract_candidate_features(pair[1], activity, datetime.fromisoformat(scenario["as_of"]))
        if any(row[key] != expected[key] for key in FEATURES):
            parity_errors += 1
    if any(len(splits) != 1 for splits in family_splits.values()):
        problems.append("Family split leakage")
    if any({pair[1] for pair in pairs if pair[0] == sid} != topic_ids for sid in by_id):
        problems.append("Incomplete scenario candidate set")
    if parity_errors:
        problems.append("Stored feature/extractor parity mismatch")
    duplicates = duplicate_report(scenarios)
    if duplicates["counts"]["exact_cross_split"] or duplicates["counts"]["near_nonexact_cross_split"]:
        problems.append("Cross-split duplicate observable states")

    # Valid live state: an assigned page can exist without an eligible event at this cutoff.
    activity = {topic.id: {"distinct_pages": 0, "visits": 0, "last_seen_at": None} for topic in topics}
    activity["programming"]["distinct_pages"] = 1
    try:
        extract_candidate_features("programming", activity, datetime(2026, 1, 1, tzinfo=timezone.utc))
        missing_visit_compatible = True
    except ValueError:
        missing_visit_compatible = False
        problems.append("Extractor rejects a live-compatible assigned page with zero eligible visits")
    # Salt changes only synthetic targets. Its provenance is disclosed; it is absent from
    # FEATURES and never enters the production feature extractor.
    return {
        "dataset_version": VERSION, "synthetic": True,
        "gate": "blocked" if problems else "passed", "blockers": sorted(set(problems)),
        "checksums": checksums, "splits": split_counts,
        "feature_fields": list(FEATURES), "feature_parity_errors": parity_errors,
        "candidate_feature_vectors_checked": len(candidates), "duplicates": duplicates,
        "missing_visit_state_compatible": missing_visit_compatible,
        "synthetic_label_noise": "row-position salt affects targets only; excluded from feature inputs",
        "test_label_policy": "This label-blind gate does not access test targets or ranking outcomes",
        "rubric_alignment": "Not evaluated by this production-input gate",
        "family_semantics": "36 numbered batches sampled from the same activity distribution; no distinct family mechanisms",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("ml/synthetic-next-topic-v2/data"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = audit(args.data_dir)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, sort_keys=True)+"\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if report["gate"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
