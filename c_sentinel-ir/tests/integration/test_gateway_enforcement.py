"""
test_gateway_enforcement.py - the gateway blocks before a service is reached.

Two things the mark schedule asks be proven at the gateway, not in a service:
a request with no token to a protected route is refused by Kong (401), and
exceeding the rate limit returns 429. Both responses still carry a correlation
id, so a rejected request stays traceable.

Author: Colile
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

PROTECTED_ROUTES = ("/incidents", "/assets", "/auth/verify", "/auth/users")


@pytest.mark.parametrize("path", PROTECTED_ROUTES)
def test_no_token_is_rejected_at_the_gateway(anon_client, path):
    """
    Purpose: a tokenless request to a protected route returns 401, and the body
             is Kong's own shape (no `error` key), proving no service was
             involved.
    Inputs:  the anonymous client and a protected path.
    Output:  assertions; no return.
    """
    response = anon_client.get(path)
    assert response.status_code == 401
    assert response.headers.get("X-Correlation-ID")
    # Kong's 401 body is `{"message": "..."}` - the services' shape has `error`.
    assert "error" not in response.json()


def test_login_is_reachable_without_a_token(anon_client):
    """
    Purpose: the one public route stays public - a tokenless login is not a 401.
    Inputs:  the anonymous client.
    Output:  assertions; no return.
    """
    response = anon_client.post(
        "/auth/login", json={"username": "nobody", "password": "wrong"}
    )
    # A 401 here is expected and correct - the credentials are deliberately
    # wrong. What must NOT happen is Kong refusing the request itself, which
    # would mean the jwt plugin had leaked onto the public login route (D-21).
    # The discriminator is the body shape, exactly as the test above uses it:
    # Kong sends {"message": ...} with no "error" key; the services send
    # {"error", "message", "details"}. Asserting `!= 401` instead would reject
    # auth-service's own legitimate rejection and can never pass.
    assert response.status_code in (200, 400, 401, 422)
    if response.status_code == 401:
        assert "error" in response.json(), (
            "login was refused by the gateway, not by auth-service"
        )


@pytest.mark.rate_limiting
def test_rate_limit_returns_429(anon_client):
    """
    Purpose: exceeding the configured rate limit returns 429 within a short
             burst. Uses the public login route so no token is needed; the
             limit is global (gateway/kong.yml, D-22).
    Inputs:  the anonymous client.
    Output:  assertions; no return.
    """
    statuses = []
    for _ in range(90):
        statuses.append(
            anon_client.post(
                "/auth/login", json={"username": "burst", "password": "burst"}
            ).status_code
        )
        if 429 in statuses:
            break
    assert 429 in statuses, f"no 429 in a 90-request burst; saw {sorted(set(statuses))}"
