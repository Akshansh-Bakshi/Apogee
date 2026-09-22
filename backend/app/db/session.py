"""Engine and session construction.

Nothing is created at import time. The FastAPI app builds an engine in its lifespan and keeps it
on ``app.state``; tests and scripts can build their own from any ``Settings``.
"""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    # create_engine is lazy: no connection is opened until first use, so the API can start
    # (and report "unavailable" on /health) even when PostgreSQL is down.
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        connect_args={"connect_timeout": settings.db_connect_timeout_seconds},
        # Bound parameters (URLs, titles) must never end up in exception messages or logs.
        hide_parameters=True,
    )


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
