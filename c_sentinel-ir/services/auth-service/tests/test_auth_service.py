"""
test_auth_service.py - the authentication logic and the events it produces.

The event assertions here are not incidental. Phase 2's first detection rule
counts `AUTH_FAILED` events by username and source IP, so this file pins down
that exactly one is emitted per failed attempt and that it carries the three
fields the rule needs. If these tests are weakened, Rule 1 becomes unwritable.

Every test runs against the fake repository: no database, no network.

Author: Colile
"""

from __future__ import annotations

import pytest
from jose import jwt

from common.errors import AuthenticationError, ValidationError

from app.schemas import Role
from app.services.auth_service import AuthService
from app.services.token_service import decode_token

SECRET = "test-secret-at-least-16-chars"


def _authenticate(service: AuthService, username: str, password: str):
    """
    Purpose: call `authenticate` with the request context every test supplies.
    Inputs:  the service, the username and the password.
    Output:  whatever `authenticate` returns.
    """
    return service.authenticate(
        username=username,
        password=password,
        source_ip="192.168.1.25",
        correlation_id="corr-abc123def456",
    )


def _events_of_type(events: list[dict], event_type: str) -> list[dict]:
    """Purpose: filter the captured stream. Inputs: the events and a type.
    Output: the matching events."""
    return [event for event in events if event["eventType"] == event_type]


def test_valid_login_returns_a_decodable_token(
    fake_users, auth_service: AuthService, user_factory, test_password
) -> None:
    """The happy path: the token decodes and names the right user and role."""
    fake_users.create(user_factory("analyst", role="analyst"))

    token, role, expires_in = _authenticate(auth_service, "analyst", test_password)

    claims = decode_token(token, secret=SECRET, algorithm="HS256")
    assert claims.sub == "analyst"
    assert claims.role == "analyst"
    assert role is Role.ANALYST
    assert expires_in == 3600


def test_valid_login_emits_one_auth_success_event(
    fake_users, auth_service: AuthService, captured_events: list, user_factory, test_password
) -> None:
    """A successful login is the baseline event Phase 2 measures against."""
    fake_users.create(user_factory("analyst"))

    _authenticate(auth_service, "analyst", test_password)

    successes = _events_of_type(captured_events, "AUTH_SUCCESS")
    assert len(successes) == 1
    assert successes[0]["userId"] == "analyst"
    assert successes[0]["statusCode"] == 200
    assert _events_of_type(captured_events, "AUTH_FAILED") == []


def test_wrong_password_raises_401_and_emits_one_auth_failed_event(
    fake_users, auth_service: AuthService, captured_events: list, user_factory
) -> None:
    """
    The build-step-5 verification line: a wrong password returns 401 *and*
    leaves exactly one AUTH_FAILED event carrying the username, source IP and
    correlation id that Rule 1 needs.
    """
    fake_users.create(user_factory("analyst"))

    with pytest.raises(AuthenticationError) as exc:
        _authenticate(auth_service, "analyst", "the-wrong-password")

    assert exc.value.status_code == 401

    failures = _events_of_type(captured_events, "AUTH_FAILED")
    assert len(failures) == 1
    failure = failures[0]
    assert failure["userId"] == "analyst"
    assert failure["sourceIp"] == "192.168.1.25"
    assert failure["correlationId"] == "corr-abc123def456"
    assert failure["statusCode"] == 401
    assert failure["severity"] == "MEDIUM"
    assert failure["serviceName"] == "auth-service"
    assert failure["affectedEntity"] == "login-endpoint"


def test_unknown_user_emits_auth_failed_with_the_attempted_username(
    auth_service: AuthService, captured_events: list, test_password
) -> None:
    """
    A brute-force run against invented names is exactly what Rule 1 must see,
    so the attempted username is recorded even though no such account exists.
    """
    with pytest.raises(AuthenticationError):
        _authenticate(auth_service, "does-not-exist", test_password)

    failures = _events_of_type(captured_events, "AUTH_FAILED")
    assert len(failures) == 1
    assert failures[0]["userId"] == "does-not-exist"


def test_disabled_account_cannot_log_in_and_emits_auth_failed(
    fake_users, auth_service: AuthService, captured_events: list, user_factory, test_password
) -> None:
    """A correct password against a disabled account still fails, and is seen."""
    fake_users.create(user_factory("suspended", is_active=False))

    with pytest.raises(AuthenticationError):
        _authenticate(auth_service, "suspended", test_password)

    assert len(_events_of_type(captured_events, "AUTH_FAILED")) == 1
    assert _events_of_type(captured_events, "AUTH_SUCCESS") == []


def test_every_failure_reason_gives_the_client_the_same_message(
    fake_users, auth_service: AuthService, user_factory, test_password
) -> None:
    """
    Telling a caller apart "no such user" from "wrong password" hands an
    attacker a free username oracle. The event stream records the real reason;
    the client never does.
    """
    fake_users.create(user_factory("analyst"))
    fake_users.create(user_factory("suspended", is_active=False))

    messages = set()
    for username, password in (
        ("analyst", "the-wrong-password"),
        ("does-not-exist", test_password),
        ("suspended", test_password),
    ):
        with pytest.raises(AuthenticationError) as exc:
            _authenticate(auth_service, username, password)
        messages.add(exc.value.message)

    assert len(messages) == 1


def test_failed_logins_emit_one_event_each(
    fake_users, auth_service: AuthService, captured_events: list, user_factory
) -> None:
    """
    Rule 1 counts failures over a window, so the count must be exact: five
    attempts must produce five events, not four and not ten.
    """
    fake_users.create(user_factory("analyst"))

    for _ in range(5):
        with pytest.raises(AuthenticationError):
            _authenticate(auth_service, "analyst", "the-wrong-password")

    assert len(_events_of_type(captured_events, "AUTH_FAILED")) == 5


def test_the_token_never_carries_the_password_hash(
    fake_users, auth_service: AuthService, user_factory, test_password
) -> None:
    """The claim set is closed: only sub, role, iss, iat and exp."""
    user = fake_users.create(user_factory("analyst"))

    token, _, _ = _authenticate(auth_service, "analyst", test_password)

    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert set(claims) == {"sub", "role", "iss", "iat", "exp"}
    assert user.password_hash not in token


def test_admin_role_reaches_the_token(
    fake_users, auth_service: AuthService, user_factory, test_password
) -> None:
    """The role in the row is the role in the token - the admin guard reads it."""
    fake_users.create(user_factory("admin", role="admin"))

    token, role, _ = _authenticate(auth_service, "admin", test_password)

    assert role is Role.ADMIN
    assert decode_token(token, secret=SECRET, algorithm="HS256").role == "admin"


def test_create_user_stores_a_hash_and_never_the_plaintext(
    admin_service, test_password
) -> None:
    """A password entering the system is hashed before it is stored."""
    user = admin_service.create_user(
        username="newcomer",
        email="newcomer@example.com",
        password=test_password,
        role=Role.ANALYST,
    )

    assert user.password_hash != test_password
    assert user.password_hash.startswith("$2b$")


def test_created_user_can_then_log_in(
    admin_service, auth_service: AuthService, test_password
) -> None:
    """Creation and authentication agree on the hashing, end to end."""
    admin_service.create_user(
        username="newcomer",
        email="newcomer@example.com",
        password=test_password,
        role=Role.ANALYST,
    )

    token, role, _ = _authenticate(auth_service, "newcomer", test_password)

    assert role is Role.ANALYST
    assert decode_token(token, secret=SECRET, algorithm="HS256").sub == "newcomer"


def test_create_user_rejects_a_weak_password(admin_service) -> None:
    """The password rules apply to account creation, not only to login."""
    with pytest.raises(ValidationError):
        admin_service.create_user(
            username="newcomer",
            email="newcomer@example.com",
            password="short",
            role=Role.ANALYST,
        )


def test_verify_rejects_a_token_this_service_did_not_issue(
    auth_service: AuthService
) -> None:
    """`verify` is the same decoder the routes use, so it refuses a forgery."""
    forged = jwt.encode({"sub": "attacker", "role": "admin"}, "another-secret-entirely")
    with pytest.raises(AuthenticationError):
        auth_service.verify(forged)
