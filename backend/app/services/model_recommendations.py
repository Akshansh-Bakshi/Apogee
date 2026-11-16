"""Read-only current-state adapter; no retrospective topic assignment assumptions."""
from datetime import datetime, timezone

from sqlalchemy import select
from app.models.page import Page
from app.models.browsing_event import BrowsingEvent
from app.schemas.next_topic import ModelRecommendations, RankedTopic
from app.services.next_topic_features import FEATURE_VERSION
from app.services.next_topic_temporal import candidate_features_for_user
from app.services.next_topic_model import cached_model, rank, ArtifactError
from app.services.topic_coverage import build_coverage
from app.services.topics import assign_user_pages


def current_recommendations(session, user_id, assigner):
    # Scope at SQL and adapter boundaries. Never accept a client historical cutoff.
    pages = session.execute(select(Page.id, Page.created_at).where(Page.user_id == user_id)).all()
    assignments = assign_user_pages(session, user_id, assigner, page_ids={p[0] for p in pages})
    as_of = datetime.now(timezone.utc)
    events = session.execute(select(BrowsingEvent.page_id, BrowsingEvent.occurred_at,
        BrowsingEvent.created_at, BrowsingEvent.session_id).where(
        BrowsingEvent.user_id == user_id, BrowsingEvent.occurred_at <= as_of,
        BrowsingEvent.created_at <= as_of)).all()
    created = dict(pages)
    rows = [dict(page_id=a.page_id, user_id=user_id,
                 topic_id=a.topic_id if a.status == 'suggested' else None,
                 page_available_at=created[a.page_id], assignment_available_at=as_of)
            for a in assignments.assignments]
    features = candidate_features_for_user(user_id=user_id, as_of=as_of, assignments=rows,
        events=[dict(page_id=p, user_id=user_id, occurred_at=o, created_at=c) for p,o,c,_ in events],
        topics=assigner.topics)
    coverage = build_coverage(assignments, [(p,o,s) for p,o,_,s in events], assigner.topics, as_of)
    result = ModelRecommendations(source='rule_based', as_of=as_of,
        taxonomy_version=assignments.taxonomy_version, feature_schema_version=FEATURE_VERSION,
        assigned_pages=assignments.suggested_count, unclassified_pages=assignments.unclassified_count,
        eligible_events=len(events), rule_recommendations=coverage.recommendations)
    if not assignments.suggested_count:
        result.fallback_reason = 'insufficient_observation_evidence'
        return result
    model, meta, error = cached_model()
    if error:
        result.fallback_reason = error
        return result
    try:
        ranked = rank(model, features)
    except (ArtifactError, ValueError, TypeError):
        result.fallback_reason = 'prediction_invalid'
        return result
    result.source = 'model'
    result.model_version = meta['model_version']
    graph = {t.id: t for t in assigner.topics}
    for position, (topic, score) in enumerate(ranked, 1):
        f = features[topic]
        parents = ', '.join(graph[topic].prerequisites) or 'none'
        result.ranking.append(RankedTopic(topic_id=topic, rank=position,
            expected_synthetic_grade=score, evidence=f,
            explanation=(f"Observed {f['candidate_page_count']} assigned pages and "
                         f"{f['candidate_visit_count']} eligible visits. Direct prerequisites: {parents}; "
                         f"{f['observed_prerequisite_count']} have captured-page evidence. "
                         "This describes observed inputs, not learned feature importance or a causal explanation.")))
    return result
