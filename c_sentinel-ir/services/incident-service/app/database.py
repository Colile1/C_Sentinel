"""
database.py - incident-service's own database engine, session factory and probe.

This service holds exactly one connection string, its own `incident_db`, and
never another service's - the Database-per-Service pattern claimed for the
mark. The engine is created lazily so the process can start (and answer
/health/live) even when incident-db is not yet up, and `database_reachable` is
what /health calls to report whether incident-db answers.

Author: Colile
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from common.config import get_settings

from app.models import Base

_logger = logging.getLogger(__name__)

SERVICE_NAME = "incident-service"

# Consul polls /health every 10s; a health check that blocks on a dead database
# for the driver's default timeout would pile requests up. Fail fast instead.
_CONNECT_TIMEOUT_SECONDS = 3


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    Purpose: the single SQLAlchemy engine for incident-db, built once per
             process.
    Inputs:  none; the connection string comes from this service's settings.
    Output:  a SQLAlchemy Engine. `pool_pre_ping` drops connections the
             database closed underneath us rather than handing them out dead.
    """
    settings = get_settings(SERVICE_NAME)
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args=_connect_args(settings.database_url),
    )


def _connect_args(database_url: str) -> dict[str, object]:
    """
    Purpose: the driver-specific connection arguments. `connect_timeout` is a
             libpq keyword; SQLite's driver rejects it outright, and SQLite is
             what the unit tests and a local smoke run use.
    Inputs:  database_url - this service's connection string.
    Output:  the kwargs for `create_engine(connect_args=...)`.
    """
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {"connect_timeout": _CONNECT_TIMEOUT_SECONDS}


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """
    Purpose: the process-wide session factory routes depend on.
    Inputs:  none.
    Output:  a `sessionmaker` bound to this service's engine.
    """
    return sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)


def get_session() -> Iterator[Session]:
    """
    Purpose: the FastAPI dependency giving one request one session, closed when
             the request ends whether it succeeded or raised.
    Inputs:  none.
    Output:  yields a `Session`.
    """
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()


def init_database() -> None:
    """
    Purpose: create this service's tables if they are absent, at startup.
             Alembic owns schema change from the moment there is a second
             revision; until then `create_all` is what makes a fresh container
             usable without a manual step.
    Inputs:  none.
    Output:  None. A database that cannot be reached logs a warning and the
             service still starts, so it can serve /health/live and report the
             real problem through /health rather than crash-looping.
    """
    try:
        Base.metadata.create_all(bind=get_engine())
        _logger.info("Database schema ready: incident_db")
    except Exception as exc:  # noqa: BLE001 - startup must not crash-loop
        _logger.warning("Could not prepare incident_db schema: %s", exc)


def database_reachable() -> bool:
    """
    Purpose: report whether incident-db answers, for the /health endpoint.
    Inputs:  none.
    Output:  True when `SELECT 1` succeeds; False on any connection or query
             error, which /health turns into a 503.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure here means "unreachable"
        _logger.warning("incident-db is unreachable: %s", exc)
        return False
