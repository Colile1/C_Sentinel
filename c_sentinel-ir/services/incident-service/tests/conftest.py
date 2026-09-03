"""
conftest.py - incident-service test fixtures.

The service is exercised three ways here. The pure units (the incident
business logic) are tested against a fake repository and a fake asset lookup,
so they need no database and no network. `asset_gateway` itself is tested
against a stub HTTP transport. The routes are tested through the real ASGI
stack on a file-less SQLite database.

Nothing here needs a container, a real network or PostgreSQL.

Author: Colile
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# services/incident-service/ on the path so `import app.main` resolves
# whichever directory pytest chose as the insertion point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings  # noqa: E402
from common.logging import EVENT_STREAM_LOGGER  # noqa: E402
from common.service import create_service_app  # noqa: E402

from app.models import Base, Incident  # noqa: E402
from app.repositories.incident_repository import IncidentRepository  # noqa: E402
from app.routers.dependencies import (  # noqa: E402
    get_incident_service,
    get_service_settings,
)
from app.routers.incident_router import router as incident_router  # noqa: E402
from app.services.asset_gateway import AssetSummary  # noqa: E402
from app.services.incident_service import IncidentService  # noqa: E402

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
             the skeleton can be built in isolation.
    Inputs:  none.
    Output:  Settings with Consul disabled, a dummy database URL and an
             asset-service URL the fake gateway never actually contacts.
    """
    return Settings(
        service_name="incident-service",
        database_url="postgresql+psycopg://incident:incident@localhost:5432/incident_db",
        jwt_secret="test-secret-at-least-16-chars",
        consul_enabled=False,
        asset_service_url="http://asset-service:8003",
    )


@pytest.fixture
def make_app(test_settings: Settings):
    """
    Purpose: build the incident-service skeleton with a caller-chosen database
             check, so a test can make the database look reachable or not.
    Inputs:  none beyond the fixtures.
    Output:  a factory `make_app(db_ok: bool | None) -> FastAPI`. None means
             "no database configured".
    """

    def _factory(db_ok: bool | None = True):
        check = None if db_ok is None else (lambda: bool(db_ok))
        return create_service_app(
            "incident-service", check_database=check, settings=test_settings
        )

    return _factory


@pytest.fixture
def client(make_app) -> TestClient:
    """Purpose: a TestClient over the skeleton with a reachable database.
    Inputs: make_app. Output: TestClient, lifespan run so registration fires."""
    with TestClient(make_app(True)) as test_client:
        yield test_client


class FakeIncidentRepository:
    """
    Purpose: stand in for `IncidentRepository` so the incident business logic
             can be tested with no database at all.
    Inputs:  incidents - the rows this fake holds.
    Output:  an object with the repository's five methods.
    """

    def __init__(self, incidents: list[Incident] | None = None) -> None:
        self._next_id = 1
        self.incidents: dict[int, Incident] = {}
        for incident in incidents or []:
            self._store(incident)

    def _store(self, incident: Incident) -> Incident:
        """Purpose: assign an id and hold the row. Inputs: incident. Output: incident."""
        if incident.id is None:
            incident.id = self._next_id
            self._next_id += 1
        self.incidents[incident.id] = incident
        return incident

    def get(self, incident_id: int) -> Incident | None:
        """Purpose: look an incident up. Inputs: incident_id. Output: Incident or None."""
        return self.incidents.get(incident_id)

    def list(
        self, status: str | None = None, severity: str | None = None
    ) -> list[Incident]:
        """Purpose: every held incident, optionally filtered.
        Inputs: status, severity. Output: a list of Incident."""
        values = sorted(self.incidents.values(), key=lambda i: i.id)
        if status is not None:
            values = [i for i in values if i.status == status]
        if severity is not None:
            values = [i for i in values if i.severity == severity]
        return values

    def create(self, incident: Incident) -> Incident:
        """Purpose: record a created incident. Inputs: the Incident. Output: the Incident."""
        return self._store(incident)

    def update(self, incident: Incident, changes: dict[str, object]) -> Incident:
        """Purpose: apply field changes. Inputs: incident, changes. Output: Incident."""
        for field, value in changes.items():
            setattr(incident, field, value)
        return incident

    def delete(self, incident: Incident) -> None:
        """Purpose: remove an incident. Inputs: incident. Output: None."""
        self.incidents.pop(incident.id, None)


def make_incident(
    title: str = "Suspicious login",
    description: str = "Multiple failed logins from one IP.",
    severity: str = "LOW",
    status: str = "OPEN",
    reported_by: str = "analyst",
    asset_id: int = 1,
    asset_name_snapshot: str = "web-01",
) -> Incident:
    """
    Purpose: build an unpersisted `Incident` for tests.
    Inputs:  the incident's fields.
    Output:  an `Incident` with no id yet.
    """
    return Incident(
        title=title,
        description=description,
        severity=severity,
        status=status,
        reported_by=reported_by,
        asset_id=asset_id,
        asset_name_snapshot=asset_name_snapshot,
    )


def make_fetch_asset(name: str = "web-01", available: bool = True):
    """
    Purpose: a fake asset lookup that never touches the network, for the
             incident-service unit tests.
    Inputs:  name - the asset name to return. available - whether the lookup
             should look like a healthy asset-service.
    Output:  a callable matching `asset_gateway.fetch_asset`'s signature.
    """

    def _fetch(asset_id: int, *, correlation_id: str, **_ignored) -> AssetSummary:
        """Purpose: the fake lookup. Inputs: asset_id, correlation_id.
        Output: an AssetSummary."""
        return AssetSummary(asset_id=asset_id, name=name, available=available)

    return _fetch


@pytest.fixture
def fake_incidents() -> FakeIncidentRepository:
    """Purpose: an empty fake repository. Inputs: none. Output: the fake."""
    return FakeIncidentRepository()


@pytest.fixture
def incident_service(fake_incidents: FakeIncidentRepository) -> IncidentService:
    """Purpose: the business logic over the fake repository and a fake asset
    lookup that always succeeds. Inputs: fake_incidents. Output: an
    IncidentService needing no database or network."""
    return IncidentService(fake_incidents, make_fetch_asset())


@pytest.fixture
def captured_events():
    """
    Purpose: collect the security events emitted during a test, as the parsed
             dicts the SOC collector would read.
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
             pointed at SQLite, Consul disabled and the asset lookup faked so
             no test needs a network.
    Inputs:  the fixtures.
    Output:  a TestClient with an empty incident table.
    """
    app = create_service_app(
        "incident-service", check_database=lambda: True, settings=test_settings
    )
    app.include_router(incident_router)

    def _override_service():
        """Purpose: bind the routes to the SQLite session and a fake asset
        lookup. Inputs: none. Output: yields an IncidentService."""
        request_session = session_factory()
        try:
            yield IncidentService(
                IncidentRepository(request_session), make_fetch_asset()
            )
        finally:
            request_session.close()

    app.dependency_overrides[get_incident_service] = _override_service
    app.dependency_overrides[get_service_settings] = lambda: test_settings

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def incident_factory():
    """Purpose: hand tests the `make_incident` builder without an import.
    Inputs: none. Output: the `make_incident` callable."""
    return make_incident


@pytest.fixture
def fetch_asset_factory():
    """Purpose: hand tests the `make_fetch_asset` builder without an import.
    Inputs: none. Output: the `make_fetch_asset` callable."""
    return make_fetch_asset
