"""Safe artifact loading and current-state model endpoint regression coverage."""
import json
import shutil
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_db_session
from app.main import create_app
from app.services import model_recommendations as service
from app.services.next_topic_model import ARTIFACT_DIR, ArtifactError, load_model, rank, cached_model
from app.services.next_topic_temporal import candidate_features_for_user
from app.services.topic_taxonomy import TOPICS
from tests.factories import make_settings
from tests.test_topic_coverage import assignments

NOW = datetime.now(timezone.utc)


def test_trusted_artifact_and_deterministic_inference():
    model, meta = load_model()
    f = candidate_features_for_user(user_id='a', as_of=NOW, assignments=[], events=[])
    assert rank(model, f) == rank(load_model()[0], f)
    assert len(rank(model, f)) == 8
    assert meta['training_rows'] == 1600
    assert cached_model()[0] is cached_model()[0]


@pytest.mark.parametrize('change,reason', [
    ('missing', 'artifact_missing'), ('bytes', 'artifact_untrusted'),
    ('features', 'schema_mismatch'), ('taxonomy_version', 'schema_mismatch'),
    ('versions', 'runtime_mismatch'), ('invalid', 'artifact_invalid'),
])
def test_rejects_invalid_artifacts_before_unpickle(tmp_path, change, reason, monkeypatch):
    shutil.copytree(ARTIFACT_DIR, tmp_path/'artifact')
    root = tmp_path/'artifact'
    p = root/'manifest.json'
    meta = json.loads(p.read_text())
    if change == 'missing':
        (root/'model.joblib').unlink()
    elif change == 'bytes':
        (root/'model.joblib').write_bytes(b'untrusted')
    else:
        if change == 'versions': meta['versions']['sklearn'] = '0'
        elif change == 'invalid': meta = []
        else: meta[change] = 'wrong'
        p.write_text(json.dumps(meta))
    monkeypatch.setattr('app.services.next_topic_model.joblib.load', lambda *_: pytest.fail('unpickle reached'))
    with pytest.raises(ArtifactError, match=reason):
        load_model(root)


def test_ties_and_invalid_prediction():
    features = {t.id: {} for t in TOPICS}
    from app.services.next_topic_features import FEATURES
    features = {t: {f: 0 for f in FEATURES} for t in features}
    model = SimpleNamespace(predict_proba=lambda _: np.full((8, 3), 1/3))
    assert [t for t, _ in rank(model, features)] == sorted(features)
    model.predict_proba = lambda _: np.full((8, 3), np.nan)
    with pytest.raises(ArtifactError): rank(model, features)


class Session:
    def __init__(self, pages=(), events=()):
        self.results = iter((pages, events))
        self.statements = []
    def execute(self, statement):
        self.statements.append(statement)
        return SimpleNamespace(all=lambda: list(next(self.results)))


@pytest.mark.parametrize('failure', [None, 'artifact_missing', 'runtime_mismatch', 'artifact_untrusted'])
def test_current_counts_and_fallback(monkeypatch, failure):
    user, page = uuid4(), uuid4()
    session = Session([(page, NOW-timedelta(days=1))])
    monkeypatch.setattr(service, 'assign_user_pages', lambda *a, **k: assignments((page, 'algorithms')))
    if failure:
        monkeypatch.setattr(service, 'cached_model', lambda: (None, None, failure))
    response = service.current_recommendations(session, user, SimpleNamespace(topics=TOPICS))
    assert response.assigned_pages == 1 and response.eligible_events == 0
    assert response.rule_recommendations[0].topic_id == 'programming'
    assert response.fallback_reason == failure
    if not failure:
        evidence = next(r.evidence for r in response.ranking if r.topic_id == 'algorithms')
        assert evidence['candidate_page_count'] == 1 and evidence['candidate_visit_count'] == 0
        assert evidence['candidate_recency_days'] is None
    for statement in session.statements:
        assert user in statement.compile().params.values()
        assert 'user_id =' in str(statement)
    assert 'occurred_at <=' in str(session.statements[1])
    assert 'created_at <=' in str(session.statements[1])


def test_empty_user_api_and_existing_paths():
    app = create_app(make_settings())
    # Empty assign_user_pages skips its SELECT; page/event queries still run.
    app.dependency_overrides[get_db_session] = lambda: Session()
    with TestClient(app) as client:
        path = '/api/v1/topics/recommendations/model'
        assert client.get(path, params={'user_id': 'bad'}).status_code == 422
        result = client.get(path, params={'user_id': str(uuid4())})
        assert result.status_code == 200
        assert result.json()['fallback_reason'] == 'insufficient_observation_evidence'
        assert result.json()['ranking'] == []
        paths = client.get('/openapi.json').json()['paths']
        assert '/api/v1/topics/coverage' in paths and '/api/v1/topics/assignments' in paths


@pytest.mark.db
def test_real_database_user_isolation_and_missing_embeddings(db_session):
    from tests.factories import make_user, make_page
    from tests.test_topics import Encoder
    from app.services.topics import TopicAssigner
    owner, other = make_user(db_session), make_user(db_session)
    make_page(db_session, owner, 'https://example.com/owner')
    make_page(db_session, other, 'https://example.com/other')
    assigner = TopicAssigner(Encoder(), topics=TOPICS)
    result = service.current_recommendations(db_session, owner.id, assigner)
    assert result.unclassified_pages == 1 and result.assigned_pages == 0
    assert result.source == 'rule_based'
    empty = service.current_recommendations(db_session, uuid4(), assigner)
    assert empty.unclassified_pages == empty.assigned_pages == 0


@pytest.mark.db
def test_real_event_cutoff_and_feature_parity(db_session, monkeypatch):
    from tests.factories import make_user, make_page, make_device, make_event
    from app.services.next_topic_features import extract_candidate_features
    owner, other = make_user(db_session), make_user(db_session)
    device, foreign_device = make_device(db_session, owner), make_device(db_session, other)
    page = make_page(db_session, owner, 'https://example.com/a')
    second = make_page(db_session, owner, 'https://example.com/b')
    foreign = make_page(db_session, other, 'https://example.com/foreign')
    cutoff = datetime.now(timezone.utc)
    make_event(db_session, owner, device, page=page, at=cutoff)
    make_event(db_session, owner, device, page=page, at=cutoff+timedelta(seconds=1))
    late = make_event(db_session, owner, device, page=page, at=cutoff-timedelta(days=1))
    late.created_at = cutoff+timedelta(seconds=1)
    make_event(db_session, other, foreign_device, page=foreign, at=cutoff)
    db_session.flush()
    class Clock:
        @staticmethod
        def now(tz): return cutoff
    monkeypatch.setattr(service, 'datetime', Clock)
    def scoped_assignments(session, user_id, assigner, *, page_ids):
        assert user_id == owner.id and page_ids == {page.id, second.id}
        return assignments((page.id, 'algorithms'), (second.id, 'algorithms'))
    monkeypatch.setattr(service, 'assign_user_pages', scoped_assignments)
    result = service.current_recommendations(db_session, owner.id, SimpleNamespace(topics=TOPICS))
    assert result.eligible_events == 1
    activity = {t.id: dict(distinct_pages=0, visits=0, last_seen_at=None) for t in TOPICS}
    activity['algorithms'] = dict(distinct_pages=2, visits=1, last_seen_at=cutoff)
    for candidate in result.ranking:
        assert candidate.evidence == extract_candidate_features(candidate.topic_id, activity, cutoff)
