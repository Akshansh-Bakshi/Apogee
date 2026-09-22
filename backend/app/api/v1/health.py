"""GET /api/v1/health: application and database status."""

import logging
from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import __version__
from app.api.deps import AppSettings, DbSession
from app.db.health import probe_database

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

HealthStatus = Literal["ok", "degraded", "unavailable"]


class ApplicationInfo(BaseModel):
    name: str
    version: str
    environment: str


class DatabaseHealth(BaseModel):
    status: HealthStatus
    server_version: str | None = None
    pgvector_version: str | None = None
    latency_ms: float | None = None
    detail: str | None = None


class HealthResponse(BaseModel):
    status: HealthStatus
    application: ApplicationInfo
    database: DatabaseHealth


def _check_database(session: Session) -> DatabaseHealth:
    try:
        probe = probe_database(session)
    except SQLAlchemyError:
        # Log the cause server-side; the response stays generic (no hosts, users, or SQL).
        logger.exception("Database health check failed")
        return DatabaseHealth(
            status="unavailable", detail="Could not connect to or query the database."
        )

    if probe.pgvector_version is None:
        return DatabaseHealth(
            status="degraded",
            server_version=probe.server_version,
            latency_ms=probe.latency_ms,
            detail="Connected, but the pgvector extension is not installed. Run migrations.",
        )
    return DatabaseHealth(
        status="ok",
        server_version=probe.server_version,
        pgvector_version=probe.pgvector_version,
        latency_ms=probe.latency_ms,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    responses={503: {"model": HealthResponse, "description": "Database unreachable or not ready"}},
)
def get_health(response: Response, session: DbSession, settings: AppSettings) -> HealthResponse:
    """Runs a real query against PostgreSQL. Returns 503 unless the database is fully ready."""
    database = _check_database(session)
    if database.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status=database.status,
        application=ApplicationInfo(
            name="Apogee", version=__version__, environment=settings.environment
        ),
        database=database,
    )
