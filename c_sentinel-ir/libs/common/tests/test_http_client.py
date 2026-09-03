"""
test_http_client.py - build step 8's verification, the resilience pattern.

`docs/build-order.md` step 8 asks for exactly two proofs, and both are here:
a transient failure is retried and then succeeds, and consecutive failures open
the breaker, return the fallback, and log the state change. The dangerous
failure mode for this step is a breaker that never opens - it passes every
happy-path test and loses the pattern mark - so the tests assert the state
itself, not only the returned value.

No socket is opened: `httpx.get` is replaced by a handler the test controls,
which also lets a test count how many attempts were actually made.

Author: Colile
"""

from __future__ import annotations

import json

import httpx
import pybreaker
import pytest

from common.config import Settings
from common.errors import DependencyUnavailableError
from common.http_client import ResilientClient
from common.logging import EVENT_STREAM_LOGGER, configure_logging

CORRELATION_ID = "corr-test0000001"
ASSET_PATH = "/api/v1/assets/1"
BASE_URL = "http://asset-service:8003"


@pytest.fixture(autouse=True)
def _reset_logging():
    """Purpose: leave the logging module as found, so these tests do not leak
    handlers into one another. Inputs: none. Output: None."""
    import logging

    yield
    logging.getLogger().handlers.clear()
    logging.getLogger(EVENT_STREAM_LOGGER).handlers.clear()


def _settings(**overrides) -> Settings:
    """
    Purpose: settings with fast, deterministic resilience thresholds - the
             backoff is a millisecond so the suite stays quick.
    Inputs:  overrides - any field to change for one test.
    Output:  a Settings instance.
    """
    values = {
        "service_name": "incident-service",
        "database_url": "sqlite+pysqlite:///:memory:",
        "jwt_secret": "test-secret-at-least-16-chars",
        "consul_enabled": False,
        "asset_service_url": BASE_URL,
        "retry_max_attempts": 3,
        "retry_backoff_seconds": 0.001,
        "circuit_fail_max": 3,
        "circuit_reset_seconds": 0.05,
    }
    values.update(overrides)
    return Settings(**values)


def _client(monkeypatch, handler, **overrides) -> ResilientClient:
    """
    Purpose: build a client whose HTTP calls run against a handler the test
             controls rather than a real socket.
    Inputs:  monkeypatch - pytest's fixture. handler - takes an httpx.Request
             and returns an httpx.Response or raises. overrides - settings.
    Output:  the `ResilientClient` under test.
    """

    def _fake_get(url, *, headers, timeout):
        """Purpose: stand in for httpx.get. Inputs: url, headers, timeout.
        Output: an httpx.Response from the mock transport."""
        with httpx.Client(transport=httpx.MockTransport(handler)) as test_client:
            return test_client.get(url, headers=headers, timeout=timeout)

    monkeypatch.setattr("common.http_client.httpx.get", _fake_get)
    return ResilientClient(
        service_name="incident-service",
        base_url=BASE_URL,
        dependency="asset-service",
        settings=_settings(**overrides),
    )


def _events(capsys) -> list[dict]:
    """
    Purpose: read the emitted security events back off stdout, selecting them
             out of the combined stream by the presence of `eventType` - which
             is how Phase 2's collector will pick them out of the same stream.
    Inputs:  capsys.
    Output:  one dict per emitted event line, ordinary log lines dropped.
    """
    output = capsys.readouterr().out.strip()
    lines = [json.loads(line) for line in output.splitlines() if line]
    return [line for line in lines if "eventType" in line]


def _fallback() -> dict:
    """Purpose: the caller's declared degraded result.
    Inputs: none. Output: a marker dict the assertions recognise."""
    return {"name": "unknown", "available": False}


class TestRetry:
    """A transient failure must be retried, not surfaced to the caller."""

    def test_a_transient_failure_is_retried_and_then_succeeds(self, monkeypatch) -> None:
        """Step 8's second verification: one blip must not degrade the call."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: fail once, then succeed. Inputs: request. Output: response."""
            attempts.append(request)
            if len(attempts) == 1:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(200, json={"id": 1, "name": "web-01"})

        client = _client(monkeypatch, handler)

        body = client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert body["name"] == "web-01"
        assert len(attempts) == 2, "the first failure should have been retried"
        assert client.breaker_state == "closed", "a recovered call is not a failure"

    def test_retry_gives_up_after_the_configured_attempts(self, monkeypatch) -> None:
        """Retry must be bounded, or a dead dependency hangs the caller forever."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: always fail. Inputs: request. Output: never returns."""
            attempts.append(request)
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(monkeypatch, handler, retry_max_attempts=3)

        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert len(attempts) == 3

    def test_a_404_is_not_retried(self, monkeypatch) -> None:
        """A missing asset is a correct answer; retrying it only adds latency."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: answer 404. Inputs: request. Output: a 404 response."""
            attempts.append(request)
            return httpx.Response(404, json={"error": "NOT_FOUND"})

        client = _client(monkeypatch, handler)

        with pytest.raises(httpx.HTTPStatusError):
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert len(attempts) == 1

    def test_the_correlation_id_is_propagated(self, monkeypatch) -> None:
        """The whole event stream is useless if the id stops at the boundary."""
        seen = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: record the header. Inputs: request. Output: 200."""
            seen["id"] = request.headers.get("X-Correlation-ID")
            return httpx.Response(200, json={"id": 1, "name": "web-01"})

        client = _client(monkeypatch, handler)
        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert seen["id"] == CORRELATION_ID


class TestCircuitBreaker:
    """The breaker must actually open - a breaker that never trips is the bug."""

    def test_consecutive_failures_open_the_breaker(self, monkeypatch, capsys) -> None:
        """Step 8's first verification, and the pattern's whole claim."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: a dead dependency. Inputs: request. Output: never returns."""
            raise httpx.ConnectError("connection refused", request=request)

        configure_logging("incident-service")
        client = _client(monkeypatch, handler, circuit_fail_max=3)

        for _ in range(3):
            body = client.get(
                ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback
            )
            assert body["available"] is False

        assert client.breaker_state == "open"

        events = _events(capsys)
        types = [event["eventType"] for event in events]
        assert types.count("DEPENDENCY_FAILURE") == 3, "one per failed request"
        assert "CIRCUIT_OPENED" in types, "the state change must reach the stream"

        opened = next(e for e in events if e["eventType"] == "CIRCUIT_OPENED")
        assert opened["serviceName"] == "incident-service"
        assert opened["affectedEntity"] == "asset-service"
        assert opened["severity"] == "HIGH"

    def test_retries_do_not_count_separately_against_the_threshold(
        self, monkeypatch
    ) -> None:
        """Retry nests inside the breaker, so one request is one failure.

        Nested the other way, a single request's three retries would trip a
        threshold of three and the configured value would mean nothing.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: a dead dependency. Inputs: request. Output: never returns."""
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(
            monkeypatch, handler, circuit_fail_max=3, retry_max_attempts=3
        )

        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert client.breaker_state == "closed", (
            "three retries of one request must count as one failure, not three"
        )

    def test_an_open_breaker_returns_the_fallback_without_calling(
        self, monkeypatch
    ) -> None:
        """The point of the pattern: a fast fallback, no network touched."""
        attempts = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: count attempts and fail. Inputs: request. Output: none."""
            attempts.append(request)
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(monkeypatch, handler, circuit_fail_max=2, retry_max_attempts=1)

        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)
        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)
        assert client.breaker_state == "open"
        attempts_before = len(attempts)

        body = client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert body["available"] is False
        assert len(attempts) == attempts_before, "an open breaker must not call out"

    def test_a_404_never_opens_the_breaker(self, monkeypatch) -> None:
        """A healthy dependency answering 404 must not be taken out of service."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: answer 404. Inputs: request. Output: a 404 response."""
            return httpx.Response(404, json={"error": "NOT_FOUND"})

        client = _client(monkeypatch, handler, circuit_fail_max=2)

        for _ in range(5):
            with pytest.raises(httpx.HTTPStatusError):
                client.get(
                    ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback
                )

        assert client.breaker_state == "closed"

    def test_a_5xx_counts_as_a_failure(self, monkeypatch) -> None:
        """A faulting dependency is an outage whether it answers or not."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: answer 500. Inputs: request. Output: a 500 response."""
            return httpx.Response(500, json={"error": "INTERNAL_ERROR"})

        client = _client(monkeypatch, handler, circuit_fail_max=2, retry_max_attempts=1)

        for _ in range(2):
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert client.breaker_state == "open"

    def test_the_breaker_closes_once_the_dependency_recovers(
        self, monkeypatch, capsys
    ) -> None:
        """CIRCUIT_CLOSED is what the demo shows after restarting the service."""
        healthy = {"value": False}

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: fail until flipped healthy. Inputs: request. Output: response."""
            if not healthy["value"]:
                raise httpx.ConnectError("connection refused", request=request)
            return httpx.Response(200, json={"id": 1, "name": "web-01"})

        configure_logging("incident-service")
        client = _client(
            monkeypatch,
            handler,
            circuit_fail_max=2,
            retry_max_attempts=1,
            circuit_reset_seconds=0.01,
        )

        for _ in range(2):
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)
        assert client.breaker_state == "open"

        healthy["value"] = True
        _wait_for_reset_timeout()

        body = client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        assert body["name"] == "web-01", "the trial call should have reached the service"
        assert client.breaker_state == "closed"

        types = [event["eventType"] for event in _events(capsys)]
        assert "CIRCUIT_OPENED" in types
        assert "CIRCUIT_CLOSED" in types


class TestFallbackContract:
    """What the caller gets back when the dependency is gone."""

    def test_no_fallback_raises_a_typed_503(self, monkeypatch) -> None:
        """A caller with no safe degraded answer gets a mapped error, not a crash."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: a dead dependency. Inputs: request. Output: never returns."""
            raise httpx.ConnectError("connection refused", request=request)

        client = _client(monkeypatch, handler, retry_max_attempts=1)

        with pytest.raises(DependencyUnavailableError) as raised:
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID)

        assert raised.value.status_code == 503
        assert "asset-service" in raised.value.message

    def test_a_dependency_failure_event_carries_the_correlation_id(
        self, monkeypatch, capsys
    ) -> None:
        """Phase 2 joins the failure to the request that provoked it."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: a dead dependency. Inputs: request. Output: never returns."""
            raise httpx.ConnectError("connection refused", request=request)

        configure_logging("incident-service")
        client = _client(monkeypatch, handler, retry_max_attempts=1)

        client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        failure = next(
            e for e in _events(capsys) if e["eventType"] == "DEPENDENCY_FAILURE"
        )
        assert failure["correlationId"] == CORRELATION_ID
        assert failure["affectedEntity"] == "asset-service"
        assert failure["endpoint"] == ASSET_PATH

    def test_an_open_breaker_does_not_flood_the_event_stream(
        self, monkeypatch, capsys
    ) -> None:
        """Suppressed calls never left the process; Rule 4 must not count them."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Purpose: a dead dependency. Inputs: request. Output: never returns."""
            raise httpx.ConnectError("connection refused", request=request)

        configure_logging("incident-service")
        client = _client(monkeypatch, handler, circuit_fail_max=2, retry_max_attempts=1)

        for _ in range(2):
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)
        capsys.readouterr()

        for _ in range(5):
            client.get(ASSET_PATH, correlation_id=CORRELATION_ID, fallback=_fallback)

        types = [event["eventType"] for event in _events(capsys)]
        assert "DEPENDENCY_FAILURE" not in types


def _wait_for_reset_timeout() -> None:
    """Purpose: let the breaker's reset timeout elapse so the next call is the
    half-open trial. Inputs: none. Output: None."""
    import time

    time.sleep(0.05)
