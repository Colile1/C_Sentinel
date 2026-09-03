"""
capture_breaker_evidence.py - reproduce the circuit breaker evidence offline.

Drives `ResilientClient` against a dependency that is down and then recovers,
printing the response time of every call and writing the security events to
stdout. The point is the timings: the calls before the breaker opens are slow
because they retry, and the calls after it opens return in roughly zero
milliseconds because no network is touched. That contrast is the observable
signature of an open breaker, and it is what `docs/patterns.md` asks be said
out loud on camera.

This is the offline twin of `break_asset_service.py`, which does the same
against the real stack once step 9 has containers to stop. This one needs no
Docker, so the evidence in `docs/evidence/` is reproducible from a clean
checkout at any time - including while writing the report.

Usage:
    python scripts/capture_breaker_evidence.py > docs/evidence/step8-circuit-breaker-events.jsonl

Author: Colile
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libs"))

import httpx  # noqa: E402

import common.http_client as http_client  # noqa: E402
from common.config import Settings  # noqa: E402
from common.http_client import ResilientClient  # noqa: E402
from common.logging import configure_logging  # noqa: E402

ASSET_PATH = "/api/v1/assets/1"
BASE_URL = "http://asset-service:8003"
CORRELATION_ID = "corr-demo00000001"

# Whether the stand-in asset-service is answering. Flipped part-way through to
# stand for `docker compose start asset-service`.
_dependency_healthy = {"value": False}


def _handler(request: httpx.Request) -> httpx.Response:
    """
    Purpose: stand in for asset-service, refusing connections until the run
             marks it recovered.
    Inputs:  request - the outgoing request.
    Output:  a 200 response once healthy.
    Raises:  `httpx.ConnectError` while the dependency is down.
    """
    if not _dependency_healthy["value"]:
        raise httpx.ConnectError("connection refused", request=request)
    return httpx.Response(200, json={"id": 1, "name": "web-01"})


def _install_stand_in_dependency() -> None:
    """
    Purpose: route the client's real HTTP call path through a mock transport, so
             the run needs no socket and no container while still exercising the
             genuine retry and breaker code.
    Inputs:  none.
    Output:  None.
    """

    def fake_get(url, *, headers, timeout):
        """Purpose: stand in for httpx.get. Inputs: url, headers, timeout.
        Output: an httpx.Response from the mock transport."""
        with httpx.Client(transport=httpx.MockTransport(_handler)) as client:
            return client.get(url, headers=headers, timeout=timeout)

    http_client.httpx.get = fake_get


def _build_client() -> ResilientClient:
    """
    Purpose: a client with demo-paced thresholds - it opens after three failed
             requests and re-tests after a second, so the whole run fits on
             camera.
    Inputs:  none.
    Output:  the `ResilientClient` under demonstration.
    """
    settings = Settings(
        service_name="incident-service",
        database_url="sqlite+pysqlite:///:memory:",
        jwt_secret="demo-secret-at-least-16-chars",
        consul_enabled=False,
        asset_service_url=BASE_URL,
        retry_max_attempts=3,
        retry_backoff_seconds=0.01,
        circuit_fail_max=3,
        circuit_reset_seconds=1.0,
    )
    return ResilientClient(
        service_name="incident-service",
        base_url=BASE_URL,
        dependency="asset-service",
        settings=settings,
    )


def _call(client: ResilientClient, number: int) -> None:
    """
    Purpose: make one call and report its state and elapsed time, which is the
             evidence this script exists to produce.
    Inputs:  client - the client under demonstration. number - the call's
             position in the run, for the printed line.
    Output:  None. One `Description: value` line is written to stderr, so the
             events on stdout stay a clean JSON stream.
    """
    started = time.perf_counter()
    body = client.get(
        ASSET_PATH,
        correlation_id=CORRELATION_ID,
        fallback=lambda: {"name": "unknown", "available": False},
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(
        f"Call {number}: state={client.breaker_state}, "
        f"elapsed_ms={elapsed_ms:.1f}, result={body}",
        file=sys.stderr,
    )


def main() -> None:
    """
    Purpose: run the two phases of the demonstration - the dependency down until
             the breaker opens, then recovered until it closes.
    Inputs:  none.
    Output:  None. Events on stdout, the timing narration on stderr.
    """
    _install_stand_in_dependency()
    configure_logging("incident-service")
    client = _build_client()

    print("Phase: asset-service is down", file=sys.stderr)
    for number in range(1, 6):
        _call(client, number)

    print("Phase: asset-service restarted, waiting out the reset timeout",
          file=sys.stderr)
    _dependency_healthy["value"] = True
    time.sleep(1.1)
    _call(client, 6)


if __name__ == "__main__":
    main()
