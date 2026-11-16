"""Offline and deployed inference use the same frozen projection and cutoff adapter."""
from datetime import datetime, timezone, timedelta
from ml.synthetic_next_topic_v2 import extract_candidate_features as offline
from ml.next_topic_temporal import candidate_features_for_user as offline_adapter
from app.services.next_topic_features import extract_candidate_features as live
from app.services.next_topic_temporal import candidate_features_for_user as live_adapter


def test_exact_shared_implementation_and_temporal_parity():
    assert offline is live
    assert offline_adapter is live_adapter
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    args = dict(user_id='a', as_of=now, assignments=[dict(page_id='p', user_id='a',
        topic_id='algorithms', page_available_at=now, assignment_available_at=now)],
        events=[dict(page_id='p', user_id='a', occurred_at=now, created_at=now),
                dict(page_id='p', user_id='a', occurred_at=now+timedelta(seconds=1), created_at=now),
                dict(page_id='p', user_id='other', occurred_at=now, created_at=now)])
    assert offline_adapter(**args) == live_adapter(**args)
    assert live_adapter(**args)['algorithms']['candidate_visit_count'] == 1
