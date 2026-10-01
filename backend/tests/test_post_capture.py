"""Unit tests for best-effort post-capture embedding orchestration."""

from unittest.mock import MagicMock
import uuid

from app.services.post_capture import embed_page_after_capture


def test_background_embedding_uses_a_fresh_session_and_safely_logs_failure(caplog) -> None:
    session = MagicMock()
    session.__enter__.return_value = session
    session.scalars.side_effect = RuntimeError("private captured text")
    factory = MagicMock(return_value=session)
    page_id = uuid.uuid4()

    embed_page_after_capture(factory, page_id, MagicMock())

    factory.assert_called_once_with()
    session.__exit__.assert_called_once()
    assert f"page_id={page_id}" in caplog.text
    assert "private captured text" not in caplog.text
