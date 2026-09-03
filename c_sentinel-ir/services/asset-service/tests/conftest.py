"""
conftest.py - asset-service test fixtures.

Every test here runs the service through its real ASGI stack with a TestClient,
because the skeleton's whole job is what the middleware, the health router and
the instrumentator do to a request - none of which is exercisable off the
stack. Consul registration is disabled and the database check is stubbed, so no
test needs a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# services/asset-service/ on the path so `import app.main` resolves whichever
# directory pytest chose as the insertion point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings  # noqa: E402
from common.logging import EVENT_STREAM_LOGGER  # noqa: E402
from common.service import create_service_app  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_logging():
    """Purpose: stop log handlers leaking between tests, as libs/common does.
    Inputs: none. Output: None."""
    yield
    logging.getLogger().handlers.clear()
    logging.getLogger(EVENT_STREAM_LOGGER).handlers.clear()


@pytest.fixture
def test_settings() -> Settings:
    """
    Purpose: a complete Settings object that never touches the environment, so
             the skeleton can be built in isolation.
    Inputs:  none.
    Output:  Settings with Consul disabled and a dummy database URL.
    """
    return Settings(
        service_name="asset-service",
        database_url="postgresql+psycopg://asset:asset@localhost:5432/asset_db",
        jwt_secret="test-secret-at-least-16-chars",
        consul_enabled=False,
    )


@pytest.fixture
def make_app(test_settings: Settings):
    """
    Purpose: build the asset-service skeleton with a caller-chosen database
             check, so a test can make the database look reachable or not.
    Inputs:  none beyond the fixtures.
    Output:  a factory `make_app(db_ok: bool | None) -> FastAPI`. None means
             "no database configured".
    """

    def _factory(db_ok: bool | None = True) -> FastAPI:
        check = None if db_ok is None else (lambda: bool(db_ok))
        return create_service_app(
            "asset-service", check_database=check, settings=test_settings
        )

    return _factory


@pytest.fixture
def client(make_app) -> TestClient:
    """Purpose: a TestClient over the skeleton with a reachable database.
    Inputs: make_app. Output: TestClient, lifespan run so registration fires."""
    with TestClient(make_app(True)) as test_client:
        yield test_client
