"""Export blinded local topic review files; page excerpts require explicit human acknowledgement."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from uuid import UUID

from ml.topic_annotation import (
    ANNOTATION_FIELDS, PREDICTION_FIELDS, TAXONOMY_VERSION, TOPIC_IDS, write_csv,
)

CONTENT_ACKNOWLEDGEMENT = "I APPROVE LOCAL PAGE EXCERPTS"
MAX_TITLE = 200
MAX_DOMAIN = 255
MAX_EXCERPT = 280


def clean_metadata(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def fetch_predictions(api_base_url: str, user_id: str) -> dict[str, Any]:
    url = f"{api_base_url.rstrip('/')}/api/v1/topics/assignments?{urlencode({'user_id': user_id})}"
    with urlopen(Request(url, headers={"Accept": "application/json"}), timeout=120) as response:
        return json.load(response)


def _backend_imports():
    backend = Path(__file__).resolve().parents[1] / "backend"
    if str(backend) not in sys.path:
        sys.path.insert(0, str(backend))
    from app.core.config import Settings
    from app.db.session import create_db_engine
    from app.models import Page, PageChunk
    return Settings, create_db_engine, Page, PageChunk


def fetch_page_metadata(user_id: str, page_ids: list[str], include_excerpts: bool) -> dict[str, dict[str, str]]:
    from sqlalchemy import select, text
    from sqlalchemy.orm import Session

    Settings, create_db_engine, Page, PageChunk = _backend_imports()
    engine = create_db_engine(Settings())
    output: dict[str, dict[str, str]] = {}
    try:
        with Session(engine) as session, session.begin():
            session.execute(text("SET TRANSACTION READ ONLY"))
            statement = (
                select(Page.id, Page.title, Page.domain, PageChunk.chunk_index, PageChunk.text)
                .select_from(Page)
                .outerjoin(PageChunk, PageChunk.page_id == Page.id)
                .where(
                    Page.user_id == UUID(user_id),
                    Page.id.in_([UUID(page_id) for page_id in page_ids]),
                )
                .order_by(Page.id, PageChunk.chunk_index)
            )
            for page_id, title, domain, _, chunk_text in session.execute(statement):
                record = output.setdefault(str(page_id), {
                    "safe_title": clean_metadata(title, MAX_TITLE),
                    "safe_domain": clean_metadata(domain, MAX_DOMAIN),
                    "content_excerpt": "",
                })
                if include_excerpts and not record["content_excerpt"] and chunk_text:
                    record["content_excerpt"] = clean_metadata(chunk_text, MAX_EXCERPT)
        return output
    finally:
        engine.dispose()


def build_rows(payload: dict[str, Any], metadata: dict[str, dict[str, str]]):
    if payload.get("taxonomy_version") != TAXONOMY_VERSION:
        raise ValueError("assignment API taxonomy version mismatch")
    api_topics = tuple(topic.get("id") for topic in payload.get("topics", []))
    if set(api_topics) != set(TOPIC_IDS):
        raise ValueError("assignment API taxonomy IDs do not match the frozen workflow")
    annotations, predictions = [], []
    seen: set[str] = set()
    for item in payload.get("assignments", []):
        page_id = str(item["page_id"])
        if page_id in seen:
            raise ValueError("duplicate page ID in assignment API response")
        seen.add(page_id)
        info = metadata.get(page_id, {})
        annotations.append({
            "taxonomy_version": TAXONOMY_VERSION, "page_id": page_id,
            "safe_title": info.get("safe_title", ""), "safe_domain": info.get("safe_domain", ""),
            "content_excerpt": info.get("content_excerpt", ""), "human_topic": "",
            "review_status": "unreviewed", "reviewer_id": "", "reviewer_notes": "",
        })
        predictions.append({
            "taxonomy_version": TAXONOMY_VERSION, "page_id": page_id,
            "prediction_status": item["status"],
            "predicted_topic": item.get("topic_id") or "",
            "cosine_similarity": item.get("similarity") if item.get("similarity") is not None else "",
            "abstention_reason": item.get("reason") or "",
            "embedding_count": item["embedding_count"],
        })
    annotations.sort(key=lambda row: row["page_id"])
    predictions.sort(key=lambda row: row["page_id"])
    taxonomy = [
        {
            "taxonomy_version": TAXONOMY_VERSION, "topic_id": topic["id"],
            "topic_name": topic["name"], "description": topic["description"],
            "prerequisites": "|".join(topic.get("prerequisites", [])),
        }
        for topic in payload["topics"]
    ]
    return annotations, predictions, taxonomy


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--output-dir", type=Path, default=Path("ml/local-data/topic-review-v1"))
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--include-excerpts", action="store_true")
    parser.add_argument("--content-review-acknowledgement")
    args = parser.parse_args()
    if args.include_excerpts and args.content_review_acknowledgement != CONTENT_ACKNOWLEDGEMENT:
        parser.error(
            f"--include-excerpts requires --content-review-acknowledgement "
            f"\"{CONTENT_ACKNOWLEDGEMENT}\" after the reviewer approves local page-text export"
        )
    try:
        payload = fetch_predictions(args.api_base_url, args.user_id)
        page_ids = [str(item["page_id"]) for item in payload.get("assignments", [])]
        metadata = fetch_page_metadata(args.user_id, page_ids, args.include_excerpts)
        annotations, predictions, taxonomy = build_rows(payload, metadata)
        write_csv(args.output_dir / "topic-annotations.csv", ANNOTATION_FIELDS, annotations)
        write_csv(args.output_dir / "topic-predictions.csv", PREDICTION_FIELDS, predictions)
        write_csv(
            args.output_dir / "topic-taxonomy.csv",
            ("taxonomy_version", "topic_id", "topic_name", "description", "prerequisites"),
            taxonomy,
        )
        print(
            f"wrote {len(annotations)} blinded annotation rows and {len(predictions)} "
            f"separate predictions; excerpts={'included' if args.include_excerpts else 'omitted'}"
        )
        return 0
    except (OSError, ValueError) as exc:
        print(f"topic annotation export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
