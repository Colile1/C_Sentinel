"""
break_asset_service.py - the ninety seconds that earns the pattern mark.

Against the live stack:
  1. stop `asset-service`;
  2. create incidents through the gateway until the circuit breaker opens,
     printing each response time - the ones before it opens are slow because
     `ResilientClient` retries a dead dependency; the ones after return almost
     instantly because no network is touched;
  3. show that incident creation still SUCCEEDS with the degraded asset summary
     rather than failing with a 500;
  4. restart `asset-service` and wait for `CIRCUIT_CLOSED` in its log.

This is the on-camera twin of `scripts/capture_breaker_evidence.py`, which does
the same offline with a mock transport. Run this one with the stack up:

    python scripts/break_asset_service.py

Author: Colile
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = "deploy/docker-compose.yml"
MAX_CREATE_ATTEMPTS = 8
CLOSE_WAIT_SECONDS = 40

sys.path.insert(0, str(REPO_ROOT / "client"))

from api_client import ApiClient  # noqa: E402

ADMIN_USERNAME = "admin"


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line.
    Inputs: label and value. Output: None."""
    print(f"{description}: {value}")


def _compose(*args: str) -> subprocess.CompletedProcess:
    """Purpose: run one `docker compose` subcommand at the repo root.
    Inputs: the subcommand and its arguments. Output: the completed process."""
    return subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, *args],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )


def _admin_password() -> str:
    """Purpose: the bootstrap admin password, from the environment.
    Inputs: none. Output: the password, with the demo default as fallback."""
    import os

    return os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "CHANGE_ME_admin_password")


def _login() -> ApiClient:
    """Purpose: an admin-authenticated client, or exit on failure.
    Inputs: none. Output: a logged-in ApiClient."""
    client = ApiClient()
    response = client.login(ADMIN_USERNAME, _admin_password())
    if response.status_code != 200:
        _line("Could not log in", f"{response.status_code} {response.text}")
        raise SystemExit(1)
    return client


def _create_incident(client: ApiClient, number: int) -> tuple[int, float, str]:
    """
    Purpose: create one incident and time it.
    Inputs:  the client and the attempt number.
    Output:  (status_code, elapsed_ms, asset_name_snapshot_or_error).
    """
    started = time.perf_counter()
    response = client.create_incident(
        title=f"Breaker probe {number}",
        description="Created while asset-service is down, to trip the breaker.",
        severity="LOW",
        reported_by=ADMIN_USERNAME,
        asset_id=1,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000
    if response.status_code == 201:
        return response.status_code, elapsed_ms, response.json().get("asset_name_snapshot", "?")
    return response.status_code, elapsed_ms, response.text[:120]


def _breaker_closed_in_log() -> bool:
    """Purpose: whether incident-service has logged CIRCUIT_CLOSED recently.
    Inputs: none. Output: True when the token appears in its log tail."""
    result = _compose("logs", "--no-log-prefix", "--tail", "200", "incident-service")
    return "CIRCUIT_CLOSED" in result.stdout


def main() -> int:
    """
    Purpose: run the full stop / trip / recover / close sequence.
    Inputs:  none.
    Output:  0 when the breaker opened while down, creation still succeeded, and
             CIRCUIT_CLOSED appeared after recovery; 1 otherwise. asset-service
             is restarted even if a step fails.
    """
    client = _login()
    _line("Logged in as", ADMIN_USERNAME)

    _line("Stopping", "asset-service")
    if _compose("stop", "asset-service").returncode != 0:
        _line("Stop failed", "is the stack up?")
        return 1

    opened = False
    still_succeeds = False
    try:
        for number in range(1, MAX_CREATE_ATTEMPTS + 1):
            status, elapsed_ms, detail = _create_incident(client, number)
            _line(
                f"Create {number}",
                f"status={status} elapsed_ms={elapsed_ms:.0f} detail={detail}",
            )
            if status == 201:
                still_succeeds = True
            # Once the breaker is open the ret/timeout stops happening and calls
            # return fast; the degraded snapshot is the documented fallback.
            if status == 201 and elapsed_ms < 50 and number >= 3:
                opened = True
                _line("Breaker", "appears OPEN - fast response, degraded asset summary")
                break
    finally:
        _line("Restarting", "asset-service")
        _compose("start", "asset-service")

    _line("Waiting for CIRCUIT_CLOSED", f"up to {CLOSE_WAIT_SECONDS}s")
    closed = False
    deadline = time.time() + CLOSE_WAIT_SECONDS
    while time.time() < deadline:
        # A create attempt is what drives the half-open trial that closes it.
        _create_incident(client, 99)
        if _breaker_closed_in_log():
            closed = True
            break
        time.sleep(3)

    client.close()
    print()
    _line("Breaker opened while asset-service was down", opened)
    _line("Incident creation still returned 201 (degraded)", still_succeeds)
    _line("CIRCUIT_CLOSED seen after recovery", closed)
    ok = opened and still_succeeds and closed
    _line("Circuit-breaker demonstration", "PASS" if ok else "INCOMPLETE - see lines above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
