"""
conftest.py - asset-service test fixtures.

The service is exercised two ways here. The pure units (the asset business
logic) are tested directly against a fake repository, so they need no
database at all. The routes are tested through the real ASGI stack on a
file-less SQLite database, because what a route does with a typed error and
the response model is only observable on the stack.

Nothing here needs a container, a network or PostgreSQL.

Author: Colile
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# services/asset-service/ on the path so `import app.main` resolves whichever
# directory pytest chose as the insertion point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings  # noqa: E402
from common.logging import EVENT_STREAM_LOGGER  # noqa: E402
from common.service import create_service_app  # noqa: E402

from app.models import Asset, Base  # noqa: E402
from app.repositories.asset_repository import AssetRepository  # noqa: E402
from app.routers.asset_router import router as asset_router  # noqa: E402
from app.routers.dependencies import get_asset_service  # noqa: E402
from app.services.asset_service import AssetService  # noqa: E402

# One shared in-memory SQLite database, held open by StaticPool so every
# session in a test sees the same schema and rows.
SQLITE_URL = "sqlite+pysqlite:///:memory:"


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
             the service can be built in isolation.
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


class FakeAssetRepository:
    """
    Purpose: stand in for `AssetRepository` so the asset business logic can be
             tested with no database at all - which is the point of keeping
             SQLAlchemy out of app/services/.
    Inputs:  assets - the rows this fake holds.
    Output:  an object with the repository's five methods.
    """

    def __init__(self, assets: list[Asset] | None = None) -> None:
        self._next_id = 1
        self.assets: dict[int, Asset] = {}
        for asset in assets or []:
            self._store(asset)

    def _store(self, asset: Asset) -> Asset:
        """Purpose: assign an id and hold the row. Inputs: asset. Output: asset."""
        if asset.id is None:
            asset.id = self._next_id
            self._next_id += 1
        self.assets[asset.id] = asset
        return asset

    def get(self, asset_id: int) -> Asset | None:
        """Purpose: look an asset up. Inputs: asset_id. Output: Asset or None."""
        return self.assets.get(asset_id)

    def list(self, asset_type: str | None = None) -> list[Asset]:
        """Purpose: every held asset, optionally filtered.
        Inputs: asset_type. Output: a list of Asset."""
        values = sorted(self.assets.values(), key=lambda a: a.id)
        if asset_type is not None:
            values = [a for a in values if a.asset_type == asset_type]
        return values

    def create(self, asset: Asset) -> Asset:
        """Purpose: record a created asset. Inputs: the Asset. Output: the Asset."""
        return self._store(asset)

    def update(self, asset: Asset, changes: dict[str, object]) -> Asset:
        """Purpose: apply field changes. Inputs: asset, changes. Output: Asset."""
        for field, value in changes.items():
            setattr(asset, field, value)
        return asset

    def delete(self, asset: Asset) -> None:
        """Purpose: remove an asset. Inputs: asset. Output: None."""
        self.assets.pop(asset.id, None)


def make_asset(
    name: str = "web-01",
    asset_type: str = "server",
    criticality: str = "LOW",
    owner: str = "platform-team",
    location: str = "eu-west-1",
) -> Asset:
    """
    Purpose: build an unpersisted `Asset` for tests.
    Inputs:  the asset's fields.
    Output:  an `Asset` with no id yet.
    """
    return Asset(
        name=name,
        asset_type=asset_type,
        criticality=criticality,
        owner=owner,
        location=location,
    )


@pytest.fixture
def fake_assets() -> FakeAssetRepository:
    """Purpose: an empty fake repository. Inputs: none. Output: the fake."""
    return FakeAssetRepository()


@pytest.fixture
def asset_service(fake_assets: FakeAssetRepository) -> AssetService:
    """Purpose: the business logic over the fake repository.
    Inputs: fake_assets. Output: an AssetService needing no database."""
    return AssetService(fake_assets)


@pytest.fixture
def captured_events():
    """
    Purpose: collect the security events emitted during a test, as the parsed
             dicts the SOC collector would read - so an assertion tests the
             published contract rather than the wording of a log line.
    Inputs:  none.
    Output:  a list that fills as events are emitted.
    """
    events: list[dict] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            """Purpose: keep the event off one record.
            Inputs: the record. Output: None."""
            event = getattr(record, "securityEvent", None)
            if event is not None:
                events.append(event)

    logger = logging.getLogger(EVENT_STREAM_LOGGER)
    handler = _Collector()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        yield events
    finally:
        logger.removeHandler(handler)


@pytest.fixture
def session_factory():
    """
    Purpose: a SQLite session factory carrying this service's real schema, so
             the repository and the routes run against actual SQL.
    Inputs:  none.
    Output:  a sessionmaker over one shared in-memory database.
    """
    engine = create_engine(
        SQLITE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@pytest.fixture
def db_session(session_factory):
    """Purpose: one session on the SQLite schema, for repository tests.
    Inputs: session_factory. Output: a Session, closed afterwards."""
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def api_client(session_factory, test_settings: Settings):
    """
    Purpose: the whole service over its real ASGI stack, with the database
             pointed at SQLite and Consul disabled.
    Inputs:  the fixtures.
    Output:  a TestClient with an empty asset table.
    """
    app = create_service_app(
        "asset-service", check_database=lambda: True, settings=test_settings
    )
    app.include_router(asset_router)

    def _override_service():
        """Purpose: bind the routes to the SQLite session rather than Postgres.
        Inputs: none. Output: yields an AssetService on a fresh session."""
        request_session = session_factory()
        try:
            yield AssetService(AssetRepository(request_session))
        finally:
            request_session.close()

    app.dependency_overrides[get_asset_service] = _override_service

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def asset_factory():
    """Purpose: hand tests the `make_asset` builder without an import, which
    `--import-mode=importlib` does not provide.
    Inputs: none. Output: the `make_asset` callable."""
    return make_asset
