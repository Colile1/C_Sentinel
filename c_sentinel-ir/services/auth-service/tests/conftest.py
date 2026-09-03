"""
conftest.py - auth-service test fixtures.

The service is exercised two ways here. The pure units (passwords, tokens, the
authentication logic) are tested directly against a fake repository, so they
need no database at all. The routes are tested through the real ASGI stack on a
file-less SQLite database, because what a route does with a typed error, the
admin guard and the response model is only observable on the stack.

Nothing here needs a container, a network or PostgreSQL.

Author: Colile
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# services/auth-service/ on the path so `import app.main` resolves whichever
# directory pytest chose as the insertion point.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.config import Settings  # noqa: E402
from common.logging import EVENT_STREAM_LOGGER  # noqa: E402
from common.service import create_service_app  # noqa: E402

from app.models import Base, User  # noqa: E402
from app.repositories.user_repository import UserRepository  # noqa: E402
from app.routers.auth_router import router as auth_router  # noqa: E402
from app.routers.dependencies import (  # noqa: E402
    get_auth_service,
    get_service_settings,
    get_user_admin_service,
)
from app.services.auth_service import AuthService  # noqa: E402
from app.services.user_admin_service import UserAdminService  # noqa: E402
from app.services.password_service import hash_password  # noqa: E402

# The password every seeded test account uses. Comfortably over the eight
# character minimum enforced in password_service.
TEST_PASSWORD = "correct-horse-battery"

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
    Purpose: a complete Settings object that never reads the environment.
    Inputs:  none.
    Output:  Settings with Consul disabled, a dummy database URL and a known
             signing secret, so tokens are reproducible across tests.
    """
    return Settings(
        service_name="auth-service",
        database_url=SQLITE_URL,
        jwt_secret="test-secret-at-least-16-chars",
        jwt_expiry_minutes=60,
        consul_enabled=False,
    )


class FakeUserRepository:
    """
    Purpose: stand in for `UserRepository` so the authentication logic can be
             tested with no database at all - which is the point of keeping
             SQLAlchemy out of app/services/.
    Inputs:  users - the rows this fake holds.
    Output:  an object with the repository's three methods.
    """

    def __init__(self, users: list[User] | None = None) -> None:
        self.users = {user.username: user for user in (users or [])}
        self.created: list[User] = []

    def get_by_username(self, username: str) -> User | None:
        """Purpose: look a user up. Inputs: username. Output: the User or None."""
        return self.users.get(username)

    def list_users(self) -> list[User]:
        """Purpose: every held user. Inputs: none. Output: a list of User."""
        return list(self.users.values())

    def create(self, user: User) -> User:
        """Purpose: record a created user. Inputs: the User. Output: the User."""
        self.users[user.username] = user
        self.created.append(user)
        return user


def make_user(
    username: str = "analyst",
    role: str = "analyst",
    password: str = TEST_PASSWORD,
    is_active: bool = True,
) -> User:
    """
    Purpose: build a `User` carrying a real bcrypt hash, for tests that log in.
    Inputs:  the username, role, plaintext password and active flag.
    Output:  an unpersisted `User`.
    """
    return User(
        username=username,
        email=f"{username}@example.com",
        password_hash=hash_password(password),
        role=role,
        is_active=is_active,
    )


@pytest.fixture
def fake_users() -> FakeUserRepository:
    """Purpose: an empty fake repository. Inputs: none. Output: the fake."""
    return FakeUserRepository()


@pytest.fixture
def auth_service(fake_users: FakeUserRepository, test_settings: Settings) -> AuthService:
    """Purpose: the business logic over the fake repository.
    Inputs: the fixtures. Output: an AuthService needing no database."""
    return AuthService(fake_users, test_settings)


@pytest.fixture
def admin_service(fake_users) -> UserAdminService:
    """Purpose: account management over the fake repository.
    Inputs: fake_users. Output: a UserAdminService needing no database."""
    return UserAdminService(fake_users)


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
def client(session_factory, test_settings: Settings):
    """
    Purpose: the whole service over its real ASGI stack, with the database
             pointed at SQLite and Consul disabled.
    Inputs:  the fixtures.
    Output:  a TestClient. The database is seeded with one admin and one
             analyst, both using TEST_PASSWORD.
    """
    seed_session = session_factory()
    repository = UserRepository(seed_session)
    repository.create(make_user("admin", role="admin"))
    repository.create(make_user("analyst", role="analyst"))
    seed_session.close()

    app = create_service_app(
        "auth-service", check_database=lambda: True, settings=test_settings
    )
    app.include_router(auth_router)

    def _override_service():
        """Purpose: bind the routes to the SQLite session rather than Postgres.
        Inputs: none. Output: yields an AuthService on a fresh session."""
        request_session = session_factory()
        try:
            yield AuthService(UserRepository(request_session), test_settings)
        finally:
            request_session.close()

    def _override_admin_service():
        """Purpose: bind the admin routes to the SQLite session too.
        Inputs: none. Output: yields a UserAdminService on a fresh session."""
        request_session = session_factory()
        try:
            yield UserAdminService(UserRepository(request_session))
        finally:
            request_session.close()

    app.dependency_overrides[get_auth_service] = _override_service
    app.dependency_overrides[get_user_admin_service] = _override_admin_service
    app.dependency_overrides[get_service_settings] = lambda: test_settings

    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def test_password() -> str:
    """Purpose: the password every seeded account uses.
    Inputs: none. Output: the plaintext password."""
    return TEST_PASSWORD


@pytest.fixture
def user_factory():
    """Purpose: hand tests the `make_user` builder without an import, which
    `--import-mode=importlib` does not provide.
    Inputs: none. Output: the `make_user` callable."""
    return make_user


@pytest.fixture
def fake_repository_class():
    """Purpose: hand tests the fake repository type without an import.
    Inputs: none. Output: the `FakeUserRepository` class."""
    return FakeUserRepository


@pytest.fixture
def do_login():
    """Purpose: hand tests the login helper without an import.
    Inputs: none. Output: the `login` callable."""
    return login


@pytest.fixture
def auth_header():
    """Purpose: hand tests the bearer-header helper without an import.
    Inputs: none. Output: the `bearer` callable."""
    return bearer


def login(client: TestClient, username: str, password: str = TEST_PASSWORD):
    """
    Purpose: perform a login through the API, for tests that need a token.
    Inputs:  the client, the username and the password.
    Output:  the httpx Response.
    """
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


def bearer(token: str) -> dict[str, str]:
    """Purpose: the Authorization header for a token.
    Inputs: the raw JWT. Output: a headers dict."""
    return {"Authorization": f"Bearer {token}"}
