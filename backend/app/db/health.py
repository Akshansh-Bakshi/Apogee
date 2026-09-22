"""Database probe used by the health endpoint."""

import time
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

_PROBE_SQL = text(
    """
    SELECT
        current_setting('server_version') AS server_version,
        (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector_version
    """
)


@dataclass(frozen=True, slots=True)
class DatabaseProbe:
    server_version: str
    pgvector_version: str | None  # None when the extension is not installed in this database
    latency_ms: float


def probe_database(session: Session) -> DatabaseProbe:
    """Run a real round trip against PostgreSQL.

    Raises ``sqlalchemy.exc.SQLAlchemyError`` if the database cannot be reached or queried.
    Latency includes acquiring a pooled connection, which is what a caller would experience.
    """
    started = time.perf_counter()
    row = session.execute(_PROBE_SQL).one()
    latency_ms = (time.perf_counter() - started) * 1000
    return DatabaseProbe(
        server_version=row.server_version,
        pgvector_version=row.pgvector_version,
        latency_ms=round(latency_ms, 2),
    )
