"""V2 synthetic next-topic feature contract and reproducible data generator.

No database, API, model, or personal browsing data is accessed. Labels are rubric simulations.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

VERSION = "apogee-synthetic-next-topic-v2"
FEATURE_VERSION = "apogee-next-topic-features-v2"
RUBRIC_VERSION = "synthetic-next-topic-rubric-v2"
SEED = 20261116
SPLIT_FAMILIES = {
    "train": tuple(f"family-{i:02}" for i in range(1, 21)),
    "validation": tuple(f"family-{i:02}" for i in range(21, 27)),
    "test": tuple(f"family-{i:02}" for i in range(27, 37)),
}



def taxonomy():
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.services.topic_taxonomy import TAXONOMY_VERSION, TOPICS
    return TAXONOMY_VERSION, TOPICS


# Keep the existing offline import interface while sharing production code exactly.
taxonomy()
from app.services.next_topic_features import FEATURES, extract_candidate_features


def _synthetic_judgment(feature: Mapping[str, Any], salt: int) -> int:
    """Ordinal fictional rubric; branch rules intentionally are not a production preference model."""
    if feature["candidate_is_graph_gap"] and feature["candidate_page_count"] == 0:
        grade = 0
    elif feature["candidate_page_count"] >= 4 and feature["candidate_recency_days"] is not None \
            and feature["candidate_recency_days"] < 3:
        grade = 0
    elif feature["candidate_is_direct_extension"] and feature["candidate_page_count"] < 2:
        grade = 2
    elif feature["candidate_page_count"] == 0 and feature["observed_topic_breadth"] <= 2:
        grade = 2
    elif feature["candidate_page_count"] == 0 or feature["candidate_is_graph_gap"]:
        grade = 1
    else:
        grade = 0
    # Deterministic ambiguity perturbation, independent of topic identity and split.
    if salt % 13 == 0 and grade == 2:
        return 1
    if salt % 17 == 0 and grade == 0:
        return 1
    return grade


def generate(seed: int = SEED):
    tax_version, topics = taxonomy()
    rng = random.Random(seed)
    anchor = datetime(2026, 1, 1, tzinfo=timezone.utc)
    scenarios, candidates = [], []
    for index in range(360):
        family_num = index // 10 + 1
        family = f"family-{family_num:02}"
        split = next(part for part, names in SPLIT_FAMILIES.items() if family in names)
        state = rng.choice(("sparse", "focused", "broad", "returning", "repeated"))
        as_of = anchor + timedelta(days=rng.randrange(365))
        activity = {}
        for topic in topics:
            pages = rng.choices((0, 1, 2, 3, 5), weights=(38, 26, 20, 11, 5))[0]
            visits = pages + (rng.randrange(0, 8) if pages else 0)
            days = rng.randrange(0, 181) if pages else None
            activity[topic.id] = {
                "distinct_pages": pages, "visits": visits,
                "last_seen_at": None if days is None else as_of-timedelta(days=days),
            }
        scenario_id = f"v2-syn-{index+1:04}"
        scenarios.append({
            "dataset_version": VERSION, "taxonomy_version": tax_version, "synthetic": True,
            "scenario_id": scenario_id, "scenario_family": family, "split": split,
            "as_of": as_of.isoformat(), "synthetic_context_for_review_only": state,
            "topic_activity": {key: {"distinct_pages": value["distinct_pages"],
                                      "visits": value["visits"],
                                      "last_seen_at": None if value["last_seen_at"] is None else value["last_seen_at"].isoformat()}
                               for key, value in activity.items()},
        })
        for topic in topics:
            features = extract_candidate_features(topic.id, activity, as_of, topics)
            salt = index * 8 + list(topics).index(topic)
            candidates.append({
                "dataset_version": VERSION, "feature_schema_version": FEATURE_VERSION,
                "taxonomy_version": tax_version, "synthetic": True,
                "scenario_id": scenario_id, "scenario_family": family, "split": split,
                **features, "synthetic_usefulness_target": _synthetic_judgment(features, salt),
                "label_provenance": RUBRIC_VERSION,
                "label_disclaimer": "Synthetic rubric imitation; not real user preference or empirical ground truth.",
            })
    return scenarios, candidates


def validate(scenarios, candidates):
    _, topics = taxonomy()
    ids = [row["scenario_id"] for row in scenarios]
    if len(ids) != len(set(ids)) or len(scenarios) != 360 or len(candidates) != 2880:
        raise ValueError("wrong or duplicate dataset shape")
    by_id = {row["scenario_id"]: row for row in scenarios}
    family_splits = {}
    pairs = set()
    per_scenario = Counter()
    for row in candidates:
        pair = (row["scenario_id"], row["candidate_topic_id"])
        if pair in pairs:
            raise ValueError("duplicate scenario-topic pair")
        pairs.add(pair)
        per_scenario[pair[0]] += 1
        source = by_id[row["scenario_id"]]
        if row["split"] != source["split"] or row["scenario_family"] != source["scenario_family"]:
            raise ValueError("scenario and candidate metadata mismatch")
        family_splits.setdefault(row["scenario_family"], set()).add(row["split"])
        if row["synthetic_usefulness_target"] not in (0, 1, 2):
            raise ValueError("invalid label")
        for feature in FEATURES:
            if feature not in row:
                raise ValueError(f"missing feature {feature}")
        if row["candidate_recency_days"] is not None and row["candidate_recency_days"] < 0:
            raise ValueError("future information present")
    if any(len(value) != 1 for value in family_splits.values()):
        raise ValueError("family leakage")
    if any(count != len(topics) for count in per_scenario.values()):
        raise ValueError("not eight candidate topics per scenario")
    if {row["candidate_topic_id"] for row in candidates} != {topic.id for topic in topics}:
        raise ValueError("taxonomy mismatch")
    for part, families in SPLIT_FAMILIES.items():
        found = {row["scenario_family"] for row in scenarios if row["split"] == part}
        if found != set(families):
            raise ValueError(f"split family mismatch: {part}")
    return {
        "dataset_version": VERSION, "synthetic": True,
        "scenario_count": len(scenarios), "candidate_count": len(candidates),
        "family_count": len(family_splits),
        "split_scenarios": dict(Counter(row["split"] for row in scenarios)),
        "split_families": {key: len(value) for key, value in SPLIT_FAMILIES.items()},
        "labels": dict(Counter(str(row["synthetic_usefulness_target"]) for row in candidates)),
        "label_by_topic": {topic.id: dict(Counter(str(row["synthetic_usefulness_target"])
            for row in candidates if row["candidate_topic_id"] == topic.id)) for topic in topics},
        "validation": "passed",
        "limitations": ["Labels imitate explicit synthetic rules; no real feedback exists.",
                        "The fixed rubric is not an estimate of user preference."]
    }


def dump_jsonl(path, rows):
    path.write_text("".join(json.dumps(row, sort_keys=True, default=str)+"\n" for row in rows), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=Path("ml/synthetic-next-topic-v2/data"))
    args = parser.parse_args()
    scenarios, candidates = generate()
    report = validate(scenarios, candidates)
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    dump_jsonl(out/"scenarios.jsonl", scenarios)
    dump_jsonl(out/"candidates.jsonl", candidates)
    review_rng = random.Random(SEED + 1)
    selected = set()
    for family in sorted({item["scenario_family"] for item in scenarios}):
        family_ids = [item["scenario_id"] for item in scenarios if item["scenario_family"] == family]
        selected.update(review_rng.sample(family_ids, 2))
    sample = [item for item in candidates if item["scenario_id"] in selected]
    review_fields = ("scenario_id", "scenario_family", "candidate_topic_id", "candidate_page_count",
                     "candidate_visit_count", "candidate_recency_days", "candidate_is_graph_gap",
                     "human_usefulness_target", "reviewer_id", "reviewer_notes")
    with (out/"human-review-sample.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=review_fields, lineterminator="\n")
        writer.writeheader()
        for item in sample:
            writer.writerow({**{field:item.get(field,"") for field in review_fields},
                             "human_usefulness_target":"", "reviewer_id":"", "reviewer_notes":""})
    with (out/"human-review-sample-label-key.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("scenario_id", "candidate_topic_id", "synthetic_usefulness_target"), lineterminator="\n")
        writer.writeheader()
        for item in sample:
            writer.writerow({field:item[field] for field in writer.fieldnames})
    for split, families in SPLIT_FAMILIES.items():
        rows = [s for s in scenarios if s["split"] == split]
        (out/f"split-{split}.json").write_text(json.dumps({"synthetic":True,"split":split,
            "frozen_before_training":split=="test","scenario_families":families,
            "scenario_ids":[r["scenario_id"] for r in rows]},indent=2)+"\n",encoding="utf-8")
    (out/"generation-statistics.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    artifacts = [p for p in out.iterdir() if p.is_file() and p.name != "manifest.json"]
    manifest = {"synthetic":True,"dataset_version":VERSION,"feature_schema_version":FEATURE_VERSION,
      "taxonomy_version":scenarios[0]["taxonomy_version"],"seed":SEED,"feature_fields":FEATURES,
      "target_field":"synthetic_usefulness_target","group_field":"scenario_id",
      "artifacts":{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts}}
    (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(f"generated {report['scenario_count']} scenarios, {report['candidate_count']} candidate rows")


if __name__ == "__main__":
    main()
