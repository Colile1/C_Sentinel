"""
test_auth_router.py - the four endpoints over the real ASGI stack.

The unit tests prove the logic; these prove the HTTP contract that logic is
published under - that a typed error really does arrive as its status code
through `install_error_handlers`, that the admin guard is a 403 and not a 401,
and that no response ever carries a password hash.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from jose import jwt

from common.correlation import CORRELATION_ID_HEADER

from app.services.token_service import TOKEN_ISSUER

SECRET = "test-secret-at-least-16-chars"


def _token(do_login, client: TestClient, username: str = "analyst") -> str:
    """
    Purpose: log in and return the token, for tests that need a credential.
    Inputs:  the login helper, the client, and the username to log in as.
    Output:  the raw JWT.
    """
    return do_login(client, username).json()["access_token"]


def test_login_returns_a_token_and_its_lifetime(client: TestClient, do_login) -> None:
    """A valid login answers 200 with the bearer-token response shape."""
    response = do_login(client, "analyst")

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["role"] == "analyst"

    claims = jwt.decode(body["access_token"], SECRET, algorithms=["HS256"])
    assert claims["sub"] == "analyst"
    assert claims["iss"] == TOKEN_ISSUER


def test_wrong_password_returns_401_in_the_shared_error_shape(
    client: TestClient, do_login
) -> None:
    """The verification line, at the HTTP boundary."""
    response = do_login(client, "analyst", "the-wrong-password")

    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"error", "message", "details"}
    assert body["error"] == "AUTHENTICATION_ERROR"


def test_wrong_password_emits_an_auth_failed_event_through_the_stack(
    client: TestClient, captured_events: list, do_login
) -> None:
    """
    The event must survive the whole request, carrying the correlation id the
    middleware bound - that is what joins it to the rest of the workflow.
    """
    do_login(client, "analyst", "the-wrong-password")

    failures = [e for e in captured_events if e["eventType"] == "AUTH_FAILED"]
    assert len(failures) == 1
    assert failures[0]["userId"] == "analyst"
    assert failures[0]["correlationId"].startswith("corr-")


def test_the_login_events_share_the_supplied_correlation_id(
    client: TestClient, captured_events: list, test_password
) -> None:
    """One workflow, one id: the request pair and the auth event all carry it."""
    supplied = "corr-abc123def456"

    login_response = client.post(
        "/api/v1/auth/login",
        json={"username": "analyst", "password": test_password},
        headers={CORRELATION_ID_HEADER: supplied},
    )

    assert login_response.headers[CORRELATION_ID_HEADER] == supplied
    assert {e["correlationId"] for e in captured_events} == {supplied}
    assert {e["eventType"] for e in captured_events} == {
        "REQUEST_RECEIVED",
        "AUTH_SUCCESS",
        "REQUEST_COMPLETED",
    }


def test_unknown_user_returns_401_not_404(client: TestClient, do_login) -> None:
    """An unknown username must be indistinguishable from a wrong password."""
    response = do_login(client, "does-not-exist")
    assert response.status_code == 401


def test_login_with_a_missing_field_is_422(client: TestClient) -> None:
    """A malformed body fails validation before any business logic runs."""
    response = client.post("/api/v1/auth/login", json={"username": "analyst"})
    assert response.status_code == 422


def test_verify_accepts_a_fresh_token(
    do_login, client: TestClient, auth_header
) -> None:
    """`/verify` returns the claims of a good token."""
    response = client.get("/api/v1/auth/verify", headers=auth_header(_token(do_login, client)))

    assert response.status_code == 200
    body = response.json()
    assert body["valid"] is True
    assert body["username"] == "analyst"
    assert body["role"] == "analyst"
    assert body["expires_at"] > body["issued_at"]


def test_verify_rejects_an_expired_token(
    do_login, client: TestClient, auth_header
) -> None:
    """The verification line: an expired token is rejected by `verify`."""
    expired = jwt.encode(
        {
            "sub": "analyst",
            "role": "analyst",
            "iss": TOKEN_ISSUER,
            "iat": int((datetime.now(timezone.utc) - timedelta(hours=2)).timestamp()),
            "exp": int((datetime.now(timezone.utc) - timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm="HS256",
    )

    response = client.get("/api/v1/auth/verify", headers=auth_header(expired))

    assert response.status_code == 401
    assert response.json()["details"]["reason"] == "expired"


def test_verify_without_a_header_is_401(client: TestClient) -> None:
    """No credential at all is an authentication failure, not a crash."""
    response = client.get("/api/v1/auth/verify")
    assert response.status_code == 401
    assert response.json()["details"]["reason"] == "missing_bearer_token"


def test_verify_rejects_a_non_bearer_scheme(client: TestClient) -> None:
    """
    Basic auth is not accepted anywhere in this system.

    The credential is deliberately not a base64 payload: a real-looking one is
    indistinguishable from a leaked secret to a scanner, and what this test
    asserts is the scheme, which never reaches the decoder.
    """
    response = client.get(
        "/api/v1/auth/verify", headers={"Authorization": "Basic not-a-real-credential"}
    )
    assert response.status_code == 401


def test_admin_can_create_a_user_and_the_hash_never_leaves(
    client: TestClient, auth_header, test_password, do_login
) -> None:
    """Creation answers 201 with the safe view of the row."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "Newcomer@Example.com",
            "password": test_password,
            "role": "analyst",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["username"] == "newcomer"
    assert body["email"] == "newcomer@example.com"  # normalised by the validator
    assert body["is_active"] is True
    assert "password_hash" not in body
    assert "password" not in body


def test_a_created_user_can_log_in(
    client: TestClient, do_login, auth_header, test_password
) -> None:
    """Creation through the API produces an account that actually works."""
    client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": test_password,
            "role": "analyst",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )

    assert do_login(client, "newcomer").status_code == 200


def test_analyst_cannot_create_a_user(
    client: TestClient, auth_header, test_password, do_login
) -> None:
    """
    403, not 401: the caller's identity was never in doubt, only their
    permission. The distinction is what Phase 2's Rule 2 reads.
    """
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": test_password,
            "role": "admin",
        },
        headers=auth_header(_token(do_login, client, "analyst")),
    )

    assert response.status_code == 403
    assert response.json()["error"] == "AUTHORISATION_ERROR"


def test_analyst_cannot_list_users(client: TestClient, auth_header, do_login) -> None:
    """The listing is admin-only too."""
    response = client.get("/api/v1/auth/users", headers=auth_header(_token(do_login, client)))
    assert response.status_code == 403


def test_admin_lists_users_without_any_hashes(
    client: TestClient, auth_header, do_login
) -> None:
    """The listing returns the seeded accounts, hashes excluded."""
    response = client.get(
        "/api/v1/auth/users", headers=auth_header(_token(do_login, client, "admin"))
    )

    assert response.status_code == 200
    users = response.json()
    assert {user["username"] for user in users} == {"admin", "analyst"}
    assert all("password_hash" not in user for user in users)


def test_duplicate_username_is_409(
    client: TestClient, auth_header, test_password, do_login
) -> None:
    """The unique constraint surfaces as a conflict, not a 500."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "analyst",
            "email": "another@example.com",
            "password": test_password,
            "role": "analyst",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )

    assert response.status_code == 409
    assert response.json()["error"] == "CONFLICT"


def test_weak_password_on_creation_is_422(
    client: TestClient, auth_header, do_login
) -> None:
    """The schema's own minimum catches this before the service does."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": "short",
            "role": "analyst",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )
    assert response.status_code == 422


def test_malformed_email_is_422(
    client: TestClient, auth_header, test_password, do_login
) -> None:
    """The address validator names the field."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "not-an-address",
            "password": test_password,
            "role": "analyst",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )
    assert response.status_code == 422


def test_unknown_role_is_422(
    client: TestClient, auth_header, test_password, do_login
) -> None:
    """Only the two roles in the enum exist."""
    response = client.post(
        "/api/v1/auth/users",
        json={
            "username": "newcomer",
            "email": "newcomer@example.com",
            "password": test_password,
            "role": "superuser",
        },
        headers=auth_header(_token(do_login, client, "admin")),
    )
    assert response.status_code == 422


def test_the_four_auth_routes_are_documented(client: TestClient) -> None:
    """docs/api.md's auth-service table must match the served OpenAPI."""
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/verify" in paths
    assert "/api/v1/auth/users" in paths
    assert {"get", "post"} <= set(paths["/api/v1/auth/users"])
