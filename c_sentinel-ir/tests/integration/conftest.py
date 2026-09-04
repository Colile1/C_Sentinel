"""
conftest.py - fixtures for the end-to-end tests against a running stack.

Every test here is marked `integration` (see `pytest_collection_modifyitems`)
so `python -m pytest` without the stack stays fast and green. The fixtures are
deliberately thin: a gateway URL from the environment, a logged-in token, a
per-test correlation id, and a readiness wait that polls `/health` instead of
sleeping.

Nothing in this folder imports a service package - the tests are outside
callers, exactly like `client/`.

Author: Colile
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = "deploy/docker-compose.yml"
# Kong's rate-limit window is a minute; allow a little over one full window for
# the counter to reset after the burst test.
RATE_LIMIT_WAIT_SECONDS = 75

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000/api/v1")
CONSUL_URL = os.environ.get("CONSUL_URL", "http://localhost:8500")
ADMIN_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "CHANGE_ME_admin_password")

READINESS_TIMEOUT_SECONDS = 60


def pytest_collection_modifyitems(config, items):
    """
    Purpose: mark every test in this directory `integration` so none runs in
             the fast suite even if a file forgets the mark, and sort any test
             marked `stack_mutating` (it stops a container) to the end.
    Inputs:  the pytest config and collected items.
    Output:  None; items are mutated and reordered in place.
    """
    here = Path(__file__).parent
    for item in items:
        if Path(item.fspath).is_relative_to(here):
            item.add_marker(pytest.mark.integration)
    # Three tiers, in order: ordinary tests, then the rate-limit burst, then the
    # stack-mutating test. The burst deliberately exhausts Kong's global limit,
    # so anything logging in after it is refused with a 429 and skips itself -
    # which silently under-reports the suite. Sorting it after the tests that
    # need a working login, but before the container-stopping one, lets a single
    # `pytest tests/integration` run all twelve.
    def _tier(it) -> int:
        if it.get_closest_marker("stack_mutating"):
            return 2
        if it.get_closest_marker("rate_limiting"):
            return 1
        return 0

    items.sort(key=_tier)


def pytest_configure(config):
    """Purpose: register the `stack_mutating` marker so `--strict-markers` is happy.
    Inputs: the pytest config. Output: None."""
    config.addinivalue_line(
        "markers", "stack_mutating: stops or starts a container; must run last"
    )
    config.addinivalue_line(
        "markers",
        "rate_limiting: exhausts the gateway rate limit; runs after normal tests",
    )


def _compose(*args: str) -> subprocess.CompletedProcess:
    """Purpose: run a `docker compose` subcommand at the repo root.
    Inputs: the subcommand and arguments. Output: the completed process."""
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


@pytest.fixture(scope="session")
def compose():
    """Purpose: hand tests the `_compose` runner without an import.
    Inputs: none. Output: the callable."""
    return _compose


@pytest.fixture(scope="session")
def gateway_url() -> str:
    """Purpose: the gateway base URL under test.
    Inputs: none. Output: the URL string."""
    return GATEWAY_URL


@pytest.fixture(scope="session")
def consul_url() -> str:
    """Purpose: the Consul agent URL.
    Inputs: none. Output: the URL string."""
    return CONSUL_URL


@pytest.fixture(scope="session", autouse=True)
def _stack_ready() -> None:
    """
    Purpose: block the session until the gateway can reach every service's
             `/health`, so a slow `docker compose up` does not fail the first
             test. Polls rather than sleeps.
    Inputs:  none.
    Output:  None. Fails the session if the stack is not ready in time.
    """
    deadline = time.time() + READINESS_TIMEOUT_SECONDS
    last_error: str = "not attempted"
    while time.time() < deadline:
        try:
            response = httpx.get(f"{GATEWAY_URL}/health", timeout=5)
            if response.status_code < 500:
                return
            last_error = f"gateway returned {response.status_code}"
        except httpx.HTTPError as exc:
            last_error = str(exc)
        time.sleep(2)
    pytest.fail(
        f"Stack not ready in {READINESS_TIMEOUT_SECONDS}s ({last_error}). "
        f"Start it: docker compose --env-file deploy/.env -f {COMPOSE_FILE} up -d"
    )


@pytest.fixture
def correlation_id() -> str:
    """Purpose: a fresh, log-greppable correlation id per test.
    Inputs: none. Output: e.g. `corr-itest-1a2b3c4d`."""
    return "corr-itest-" + uuid.uuid4().hex[:12]


@pytest.fixture
def anon_client(correlation_id: str):
    """
    Purpose: an httpx client that sends the per-test correlation id and no
             token, for gateway-enforcement tests.
    Inputs:  the correlation id fixture.
    Output:  an httpx.Client, closed after the test.
    """
    with httpx.Client(
        base_url=GATEWAY_URL,
        headers={"X-Correlation-ID": correlation_id},
        timeout=10,
    ) as client:
        yield client


@pytest.fixture
def token(anon_client: httpx.Client) -> str:
    """
    Purpose: a valid admin bearer token, obtained through the gateway.
    Inputs:  the anonymous client.
    Output:  the raw JWT string. Skips the test if login does not return 200,
             so a misconfigured bootstrap admin is a clear skip, not a cascade
             of failures.
    """
    # A 429 here is transient, not a misconfiguration: the rate-limit burst test
    # exhausts Kong's global counter, and the window is a minute. Skipping on it
    # silently drops real coverage, so wait the window out and retry. Any other
    # non-200 is a genuine setup problem and still skips immediately.
    deadline = time.time() + RATE_LIMIT_WAIT_SECONDS
    while True:
        response = anon_client.post(
            "/auth/login",
            json={"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD},
        )
        if response.status_code != 429 or time.time() >= deadline:
            break
        time.sleep(5)

    if response.status_code != 200:
        pytest.skip(
            f"admin login returned {response.status_code}; is BOOTSTRAP_ADMIN_* "
            "set and the stack freshly started?"
        )
    return response.json()["access_token"]


@pytest.fixture
def auth_client(correlation_id: str, token: str):
    """
    Purpose: an httpx client carrying the admin token and the per-test
             correlation id.
    Inputs:  the correlation id and token fixtures.
    Output:  an httpx.Client, closed after the test.
    """
    with httpx.Client(
        base_url=GATEWAY_URL,
        headers={
            "X-Correlation-ID": correlation_id,
            "Authorization": f"Bearer {token}",
        },
        # Sized for the retry budget, not for a healthy call. When the circuit
        # breaker test stops asset-service, the first create still costs
        # RETRY_MAX_ATTEMPTS (3) x DEPENDENCY_TIMEOUT_SECONDS (3.0) plus backoff
        # inside incident-service before the breaker opens - about 9.4s, which
        # a 10s client timeout loses to gateway and app overhead.
        timeout=30,
    ) as client:
        yield client


@pytest.fixture
def seeded_asset_id(auth_client: httpx.Client) -> int:
    """
    Purpose: the id of an asset that exists, so incident tests have something to
             point at whether or not `scripts/seed_data.py` has been run.
    Inputs:  the authenticated client.
    Output:  an asset id. Uses the first listed asset, or creates one.
    """
    listing = auth_client.get("/assets")
    listing.raise_for_status()
    assets = listing.json()
    if assets:
        return assets[0]["id"]
    created = auth_client.post(
        "/assets",
        json={
            "name": f"itest-asset-{uuid.uuid4().hex[:8]}",
            "asset_type": "service",
            "criticality": "LOW",
            "owner": "integration-tests",
            "location": "test",
        },
    )
    created.raise_for_status()
    return created.json()["id"]
