"""
verify_stack.py - the pre-demo preflight.

Checks, in order and without changing anything:
  1. every Compose container is running and (where it has one) healthy;
  2. all three services are registered in Consul with passing checks;
  3. every Prometheus scrape target is UP;
  4. the gateway answers on localhost:8000.

Run it before recording, not during. It prints one `Description: value` line
per check and an all-green summary, and exits non-zero if any check fails.

    python scripts/verify_stack.py

Author: Colile
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import httpx

COMPOSE_FILE = "deploy/docker-compose.yml"
ENV_FILE = "deploy/.env"
CONSUL_URL = os.environ.get("CONSUL_URL", "http://localhost:8500")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
GATEWAY_HEALTH_URL = os.environ.get(
    "GATEWAY_HEALTH_URL", "http://localhost:8000/api/v1/health"
)
EXPECTED_SERVICES = ("auth-service", "incident-service", "asset-service")


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line.
    Inputs: label and value. Output: None."""
    print(f"{description}: {value}")


def _check_containers() -> bool:
    """
    Purpose: every container in the Compose project is running, and any with a
             health check reports healthy.
    Inputs:  none; shells out to `docker compose ps --format json`.
    Output:  True when all are up and none is unhealthy.
    """
    result = subprocess.run(
        ["docker", "compose", "--env-file", ENV_FILE, "-f", COMPOSE_FILE,
         "ps", "--format", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        _line("Containers", f"docker compose ps failed: {result.stderr.strip()}")
        return False

    rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
    if not rows:
        _line("Containers", "no containers found - is the stack up?")
        return False

    ok = True
    for row in rows:
        name = row.get("Service", row.get("Name", "?"))
        state = row.get("State", "?")
        health = row.get("Health", "")
        healthy = state == "running" and health in ("", "healthy")
        _line(f"Container {name}", f"{state}{f' ({health})' if health else ''}")
        ok = ok and healthy
    return ok


def _check_consul() -> bool:
    """
    Purpose: all three services are registered in Consul and their checks pass.
    Inputs:  none.
    Output:  True when each expected service has at least one instance and no
             failing check.
    """
    try:
        services = httpx.get(f"{CONSUL_URL}/v1/agent/services", timeout=5).json()
        checks = httpx.get(f"{CONSUL_URL}/v1/agent/checks", timeout=5).json()
    except (httpx.HTTPError, ValueError) as exc:
        _line("Consul", f"unreachable: {exc}")
        return False

    registered = {s.get("Service") for s in services.values()}
    failing = [c["ServiceName"] for c in checks.values() if c.get("Status") != "passing"]

    ok = True
    for name in EXPECTED_SERVICES:
        present = name in registered
        _line(f"Consul {name}", "registered" if present else "MISSING")
        ok = ok and present
    if failing:
        _line("Consul checks failing", ", ".join(sorted(set(failing))))
        ok = False
    return ok


def _check_prometheus() -> bool:
    """
    Purpose: every Prometheus scrape target is UP.
    Inputs:  none.
    Output:  True when no active target is in any state but `up`.
    """
    try:
        payload = httpx.get(
            f"{PROMETHEUS_URL}/api/v1/targets", timeout=5
        ).json()
    except (httpx.HTTPError, ValueError) as exc:
        _line("Prometheus", f"unreachable: {exc}")
        return False

    active = payload.get("data", {}).get("activeTargets", [])
    if not active:
        _line("Prometheus targets", "none reported")
        return False

    ok = True
    for target in active:
        job = target.get("labels", {}).get("job", "?")
        health = target.get("health", "?")
        _line(f"Prometheus target {job}", health)
        ok = ok and health == "up"
    return ok


def _check_gateway() -> bool:
    """
    Purpose: the gateway answers on its public port.
    Inputs:  none.
    Output:  True when GET /api/v1/health through Kong returns a 2xx.
    """
    try:
        response = httpx.get(GATEWAY_HEALTH_URL, timeout=5)
    except httpx.HTTPError as exc:
        _line("Gateway", f"unreachable: {exc}")
        return False
    _line("Gateway /api/v1/health", response.status_code)
    return response.status_code < 300


def main() -> int:
    """
    Purpose: run the four checks and print a summary.
    Inputs:  none.
    Output:  0 when every check passed, 1 otherwise.
    """
    results = {
        "containers": _check_containers(),
        "consul": _check_consul(),
        "prometheus": _check_prometheus(),
        "gateway": _check_gateway(),
    }
    print()
    for name, passed in results.items():
        _line(f"Check {name}", "PASS" if passed else "FAIL")
    all_green = all(results.values())
    _line("Preflight", "all green - safe to record" if all_green else "NOT ready")
    return 0 if all_green else 1


if __name__ == "__main__":
    raise SystemExit(main())
