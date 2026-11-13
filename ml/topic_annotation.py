"""Local-only topic annotation records and deterministic evaluation primitives."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any
from uuid import UUID

TAXONOMY_VERSION = "apogee-technical-v1"
TOPIC_IDS = (
    "programming", "algorithms", "databases", "machine-learning",
    "information-retrieval", "cloud-systems", "web-development", "security-privacy",
)
REVIEW_STATUSES = ("unreviewed", "labeled", "uncertain", "not_enough_content", "excluded")

ANNOTATION_FIELDS = (
    "taxonomy_version", "page_id", "safe_title", "safe_domain", "content_excerpt",
    "human_topic", "review_status", "reviewer_id", "reviewer_notes",
)
PREDICTION_FIELDS = (
    "taxonomy_version", "page_id", "prediction_status", "predicted_topic",
    "cosine_similarity", "abstention_reason", "embedding_count",
)


def valid_uuid(value: object, field: str = "page_id") -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"invalid {field}") from exc


def read_csv(path: Path, required_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames != list(required_fields):
            raise ValueError(f"{path.name} header does not match required schema")
        return list(reader)


def write_csv(path: Path, fields: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def validate_annotations(rows: list[dict[str, str]]) -> dict[str, int]:
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("taxonomy_version") != TAXONOMY_VERSION:
            raise ValueError("annotation taxonomy_version mismatch")
        page_id = valid_uuid(row.get("page_id"))
        if page_id in seen:
            raise ValueError(f"duplicate annotation page_id: {page_id}")
        seen.add(page_id)
        status = row.get("review_status", "")
        if status not in REVIEW_STATUSES:
            raise ValueError(f"invalid review_status for page {page_id}")
        topic = row.get("human_topic", "").strip()
        reviewer = row.get("reviewer_id", "").strip()
        notes = row.get("reviewer_notes", "").strip()
        if status == "labeled":
            if topic not in TOPIC_IDS or not reviewer:
                raise ValueError(f"labeled page {page_id} requires one valid topic and reviewer_id")
        else:
            if topic:
                raise ValueError(f"{status} page {page_id} must not have human_topic")
            if status in {"uncertain", "not_enough_content", "excluded"} and (not reviewer or not notes):
                raise ValueError(f"{status} page {page_id} requires reviewer_id and reviewer_notes")
            if status == "unreviewed" and reviewer:
                raise ValueError(f"unreviewed page {page_id} must not have reviewer_id")
        counts[status] += 1
    return dict(counts)


def validate_predictions(rows: list[dict[str, str]]) -> dict[str, int]:
    seen: set[str] = set()
    counts: Counter[str] = Counter()
    for row in rows:
        if row.get("taxonomy_version") != TAXONOMY_VERSION:
            raise ValueError("prediction taxonomy_version mismatch")
        page_id = valid_uuid(row.get("page_id"))
        if page_id in seen:
            raise ValueError(f"duplicate prediction page_id: {page_id}")
        seen.add(page_id)
        status = row.get("prediction_status")
        topic = row.get("predicted_topic", "").strip()
        score = row.get("cosine_similarity", "").strip()
        reason = row.get("abstention_reason", "").strip()
        if status == "suggested":
            if topic not in TOPIC_IDS or reason or not score:
                raise ValueError(f"invalid suggested prediction for page {page_id}")
            try:
                number = float(score)
            except ValueError as exc:
                raise ValueError(f"invalid similarity for page {page_id}") from exc
            if not isfinite(number) or not -1 <= number <= 1:
                raise ValueError(f"invalid similarity for page {page_id}")
        elif status == "unclassified":
            if topic or score or not reason:
                raise ValueError(f"invalid abstention for page {page_id}")
        else:
            raise ValueError(f"invalid prediction_status for page {page_id}")
        counts[status] += 1
    return dict(counts)


def _metric(tp: int, denominator: int) -> float | None:
    return tp / denominator if denominator else None


def evaluate(annotation_rows: list[dict[str, str]],
             prediction_rows: list[dict[str, str]]) -> dict[str, Any]:
    annotation_counts = validate_annotations(annotation_rows)
    prediction_counts = validate_predictions(prediction_rows)
    annotations = {valid_uuid(row["page_id"]): row for row in annotation_rows}
    predictions = {valid_uuid(row["page_id"]): row for row in prediction_rows}
    unknown_annotations = sorted(set(annotations) - set(predictions))
    if unknown_annotations:
        raise ValueError("annotations contain page IDs absent from predictions")

    labeled = [row for row in annotation_rows if row["review_status"] == "labeled"]
    confusion: Counter[tuple[str, str]] = Counter()
    evaluated_predictions = 0
    labeled_abstentions = 0
    for annotation in labeled:
        prediction = predictions[valid_uuid(annotation["page_id"])]
        predicted = prediction["predicted_topic"] if prediction["prediction_status"] == "suggested" else "unclassified"
        confusion[(annotation["human_topic"], predicted)] += 1
        if predicted == "unclassified":
            labeled_abstentions += 1
        else:
            evaluated_predictions += 1

    per_class: dict[str, dict[str, Any]] = {}
    f1_values: list[float] = []
    for topic in TOPIC_IDS:
        support = sum(count for (actual, _), count in confusion.items() if actual == topic)
        predicted_count = sum(count for (_, predicted), count in confusion.items() if predicted == topic)
        tp = confusion[(topic, topic)]
        precision = _metric(tp, predicted_count)
        recall = _metric(tp, support)
        if support:
            # A supported class missed entirely has F1=0. Precision remains undefined when the
            # model never predicts the class, but excluding its F1 would inflate macro-F1.
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision is not None and recall is not None and precision + recall
                else 0.0
            )
            f1_values.append(f1)
        else:
            f1 = None
        per_class[topic] = {
            "support": support, "predicted_count": predicted_count,
            "true_positive": tp, "precision": precision, "recall": recall, "f1": f1,
        }
    confusion_rows = [
        {"human_topic": actual, "predicted_topic": predicted, "count": count}
        for (actual, predicted), count in sorted(confusion.items())
    ]
    return {
        "taxonomy_version": TAXONOMY_VERSION,
        "prediction_count": len(prediction_rows),
        "prediction_abstention_count": prediction_counts.get("unclassified", 0),
        "prediction_abstention_rate": (
            prediction_counts.get("unclassified", 0) / len(prediction_rows)
            if prediction_rows else None
        ),
        "annotation_status_counts": {status: annotation_counts.get(status, 0)
                                     for status in REVIEW_STATUSES},
        "labelled_sample_size": len(labeled),
        "labelled_abstention_count": labeled_abstentions,
        "labelled_abstention_rate": labeled_abstentions / len(labeled) if labeled else None,
        "classified_labelled_sample_size": evaluated_predictions,
        "confusion_counts": confusion_rows,
        "per_class": per_class,
        "macro_f1_supported_classes": len(f1_values),
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "missing_annotation_count": len(set(predictions) - set(annotations)),
        "limitations": [
            "Only review_status=labeled rows are ground truth.",
            "Uncertain, insufficient-content, excluded, and unreviewed rows are excluded from class metrics.",
            "Macro-F1 averages classes represented in human ground truth; a completely missed supported class has F1=0.",
            "The sample is a small local corpus and does not establish generalization.",
        ],
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
