"""
database.py - asset-service's own database engine and its reachability check.

This service holds exactly one connection string, its own, and never another
service's - the Database-per-Service pattern claimed for the mark. The engine
is created lazily so the process can start (and answer /health/live) even when
asset-db is not yet up, and `database_reachable` is what /health calls to
report whether asset-db answers.

The ORM models and session handling arrive at build step 6; this file exists
now only so the skeleton's health check is real.

Author: Colile
"""

from __future__ import annotations

import logging
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from common.config import get_settings

_logger = logging.getLogger(__name__)

_SERVICE_NAME = "asset-service"

# Consul polls /health every 10s; a health check that blocks on a dead database
# for the driver's default timeout would pile requests up. Fail fast instead.
_CONNECT_TIMEOUT_SECONDS = 3


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """
    Purpose: the single SQLAlchemy engine for asset-db, built once per process.
    Inputs:  none; the connection string comes from this service's settings.
    Output:  a SQLAlchemy Engine. `pool_pre_ping` drops connections the
             database closed underneath us rather than handing them out dead.
    """
    settings = get_settings(_SERVICE_NAME)
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": _CONNECT_TIMEOUT_SECONDS},
    )


def database_reachable() -> bool:
    """
    Purpose: report whether asset-db answers, for the /health endpoint.
    Inputs:  none.
    Output:  True when `SELECT 1` succeeds; False on any connection or query
             error, which /health turns into a 503.
    """
    try:
        with get_engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # noqa: BLE001 - any failure here means "unreachable"
        _logger.warning("asset-db is unreachable: %s", exc)
        return False
