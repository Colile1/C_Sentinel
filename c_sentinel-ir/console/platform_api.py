"""
platform_api.py - the Phase 1 platform screen: registry, containers,
databases and the gateway's enforcement.

Each endpoint answers one section of the Phase 1 demonstration that
otherwise needs a terminal or another tool:

  /registry          section 3 - every Consul-registered instance, its address
                     and its health checks (Consul's own HTTP API)
  /containers        section 4 - `docker compose ps` with each container's image
  /containers/...    sections 3 and 5 - stop or start one service or database
                     container, from a fixed list
  /databases         section 5 - the tables each service's own database holds,
                     which is what shows Database per Service
  /gateway-probe/... section 2 - an unauthenticated call, a wrong-password
                     login, and a burst past the rate limit

Docker is reached through the same `docker compose --env-file deploy/.env -f
deploy/docker-compose.yml` command `start.bat` uses, so the console sees exactly
the project the scripts do.

Author: Colile
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from collections import Counter
from typing import Any

import httpx
from fastapi import APIRouter

from common.errors import DependencyUnavailableError, NotFoundError

from console import settings

router = APIRouter(prefix="/console/api/platform", tags=["platform"])

_COMPOSE = [
    "docker", "compose",
    "--env-file", "deploy/.env",
    "-f", "deploy/docker-compose.yml",
]

#: The containers the screen may stop and start: the three services and their
#: three databases. The gateway, registry, observability and Neo4j are left
#: alone - stopping them would take the console's own view down with them.
CONTROLLABLE = (
    "auth-service", "incident-service", "asset-service",
    "auth-db", "incident-db", "asset-db",
)

#: Each service's database: compose service name and the env variables naming
#: its role and database, as deploy/docker-compose.yml assembles them.
DATABASES = (
    ("auth-service", "auth-db", "AUTH_DB_USER", "auth_service", "AUTH_DB_NAME", "auth_db"),
    ("incident-service", "incident-db", "INCIDENT_DB_USER", "incident_service", "INCIDENT_DB_NAME", "incident_db"),
    ("asset-service", "asset-db", "ASSET_DB_USER", "asset_service", "ASSET_DB_NAME", "asset_db"),
)

#: Kong refuses past 60 requests a minute; 65 lands the tail of a burst on 429.
BURST_SIZE = 65


def _docker(*args: str, timeout: float = 60) -> str:
    """
    Purpose: run one `docker compose` command for this project.
    Inputs:  args - the compose subcommand and its arguments; timeout - seconds.
    Output:  the command's stdout.
    Raises:  `DependencyUnavailableError` (503) when Docker is missing, not
             running, or the command fails - with Docker's own message.
    """
    try:
        completed = subprocess.run(
            [*_COMPOSE, *args],
            cwd=settings.PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        raise DependencyUnavailableError(
            f"docker compose could not run ({type(exc).__name__}). Is Docker Desktop running?",
            {},
        ) from exc
    if completed.returncode != 0:
        raise DependencyUnavailableError(
            f"docker compose {args[0]} failed: {completed.stderr.strip()[:300]}",
            {"command": " ".join(args)},
        )
    return completed.stdout


def _json_lines(text: str) -> list[dict[str, Any]]:
    """
    Purpose: parse Docker's `--format json`, which is one object per line in
             current releases and a single array in older ones.
    Inputs:  text - the command output.
    Output:  a list of dicts.
    """
    text = text.strip()
    if not text:
        return []
    if text.startswith("["):
        return json.loads(text)
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@router.get("/registry", summary="Consul-registered instances and their checks")
async def registry() -> dict[str, Any]:
    """
    Purpose: what Consul knows - every registered service, each instance's
             address and port, and every health check's status.
    Inputs:  none.
    Output:  {consulUrl, services: [{name, instances: [{id, address, port,
             tags, checks}]}]}. 503 when Consul does not answer.
    """
    try:
        async with httpx.AsyncClient(base_url=settings.CONSUL_URL, timeout=3.0) as client:
            catalogue = (await client.get("/v1/catalog/services")).json()
            names = sorted(name for name in catalogue if name != "consul")
            healths = await asyncio.gather(
                *(client.get(f"/v1/health/service/{name}") for name in names)
            )
    except httpx.HTTPError as exc:
        raise DependencyUnavailableError(
            f"Consul at {settings.CONSUL_URL} did not answer ({type(exc).__name__}).", {}
        ) from exc
    services = []
    for name, response in zip(names, healths):
        instances = [
            {
                "id": entry["Service"]["ID"],
                "address": entry["Service"]["Address"] or entry["Node"]["Address"],
                "port": entry["Service"]["Port"],
                "tags": entry["Service"].get("Tags") or [],
                "checks": [
                    {"name": check["Name"], "status": check["Status"],
                     "output": (check.get("Output") or "").strip()[:200]}
                    for check in entry["Checks"]
                ],
            }
            for entry in response.json()
        ]
        services.append({"name": name, "instances": instances})
    return {"consulUrl": settings.CONSUL_URL, "services": services}


def _ports(row: dict[str, Any]) -> list[str]:
    """
    Purpose: a container's published ports as `host:port->container`.
    Inputs:  row - one `docker compose ps` JSON object.
    Output:  sorted strings; empty when nothing is published.
    """
    return sorted({
        f"{p.get('URL') or '0.0.0.0'}:{p['PublishedPort']}->{p['TargetPort']}"
        for p in row.get("Publishers") or []
        if p.get("PublishedPort")
    })


@router.get("/containers", summary="The project's containers and images")
def containers() -> dict[str, Any]:
    """
    Purpose: `docker compose ps -a` with each container's image - one
             container, one image and one lifecycle per service.
    Inputs:  none.
    Output:  {containers: [...], controllable: [...]}. The image name comes
             from the compose file itself (`compose config`): `ps` reports a
             bare sha256 once a built image has been rebuilt, and `compose
             images` leaves the repository blank for the project's own
             images. The image id comes from `compose images`, matched by
             container name.
    """
    rows = _json_lines(_docker("ps", "-a", "--format", "json"))
    configured = json.loads(_docker("config", "--format", "json")).get("services", {})
    image_ids = {
        image.get("ContainerName"): (image.get("ID") or "").removeprefix("sha256:")[:12]
        for image in _json_lines(_docker("images", "--format", "json"))
    }
    listed = [
        {
            "service": row.get("Service") or "",
            "name": row.get("Name"),
            "image": configured.get(row.get("Service"), {}).get("image") or row.get("Image"),
            "imageId": image_ids.get(row.get("Name"), ""),
            "state": row.get("State"),
            "health": row.get("Health") or "",
            "status": row.get("Status"),
            "ports": _ports(row),
        }
        for row in rows
    ]
    return {
        "containers": sorted(listed, key=lambda c: c["service"]),
        "controllable": list(CONTROLLABLE),
    }


@router.post("/containers/{service}/{verb}", summary="Stop or start one container")
def control_container(service: str, verb: str) -> dict[str, Any]:
    """
    Purpose: stop or start one of the six controllable containers - for the
             registry, Database per Service and circuit-breaker demonstrations.
    Inputs:  service - a name in `CONTROLLABLE`; verb - "stop" or "start".
    Output:  {service, verb, seconds}. 404 for anything outside the list.
    """
    if service not in CONTROLLABLE or verb not in ("stop", "start"):
        raise NotFoundError(
            f"cannot {verb} {service!r} from the console", {"service": service, "verb": verb}
        )
    started = time.monotonic()
    _docker(verb, service, timeout=120)
    return {"service": service, "verb": verb, "seconds": round(time.monotonic() - started, 1)}


@router.get("/databases", summary="The tables each service's database holds")
def databases() -> list[dict[str, Any]]:
    """
    Purpose: Database per Service, shown - each service's own database and
             the tables in it, with exact row counts. No database holds another
             service's table, so no cross-service read is possible.
    Inputs:  none.
    Output:  one {service, container, database, role, tables, error} per
             database; a stopped database reports its error instead of tables.
    """
    # An exact count per table in one statement: query_to_xml runs a count(*)
    # for each table name. pg_stat_user_tables.n_live_tup would be cheaper but
    # is an estimate that reads 0 after every database restart.
    query = (
        "SELECT table_name || '|' || (xpath('/row/c/text()', query_to_xml("
        "format('SELECT count(*) AS c FROM %I', table_name), false, true, '')))[1]::text "
        "FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
    )
    result = []
    for service, container, user_var, user_default, db_var, db_default in DATABASES:
        role = os.environ.get(user_var, user_default)
        name = os.environ.get(db_var, db_default)
        entry: dict[str, Any] = {
            "service": service, "container": container, "database": name,
            "role": role, "tables": [], "error": "",
        }
        try:
            output = _docker("exec", "-T", container, "psql", "-U", role, "-d", name,
                             "-At", "-c", query, timeout=30)
            entry["tables"] = [
                {"table": table, "rows": int(rows)}
                for table, rows in (line.split("|", 1) for line in output.splitlines() if "|" in line)
            ]
        except DependencyUnavailableError as exc:
            entry["error"] = exc.message
        result.append(entry)
    return result


def _probe_result(response: httpx.Response) -> dict[str, Any]:
    """
    Purpose: the parts of a gateway response the demo points at.
    Inputs:  response - Kong's answer.
    Output:  {status, correlationId, rateLimitRemaining, body}.
    """
    try:
        body: Any = response.json()
    except ValueError:
        body = response.text[:300]
    return {
        "status": response.status_code,
        "correlationId": response.headers.get("x-correlation-id"),
        "rateLimitRemaining": response.headers.get("ratelimit-remaining"),
        "body": body,
    }


@router.post("/gateway-probe/{kind}", summary="Show the gateway enforcing")
async def gateway_probe(kind: str) -> dict[str, Any]:
    """
    Purpose: the three gateway checks from demo section 2, sent from the
             server exactly as the curl commands send them.
               no-token   GET /incidents with no token     -> 401 from Kong
               bad-login  POST /auth/login, wrong password -> 401 from auth-service
               burst      65 concurrent wrong logins        -> the tail turns 429
    Inputs:  kind - one of the three names above.
    Output:  the probe's request and result; for a burst, the status counts
             and one refused response. 404 for an unknown kind; 503 when the
             gateway does not answer.
    """
    if kind not in ("no-token", "bad-login", "burst"):
        raise NotFoundError(f"no gateway probe named {kind!r}", {"kind": kind})
    login = f"{settings.GATEWAY_URL}/api/v1/auth/login"
    wrong = {"username": settings.BOOTSTRAP_ADMIN_USERNAME, "password": "WRONG"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            if kind == "no-token":
                response = await client.get(f"{settings.GATEWAY_URL}/api/v1/incidents")
                return {"kind": kind, "request": "GET /api/v1/incidents with no Authorization header",
                        **_probe_result(response)}
            if kind == "bad-login":
                response = await client.post(login, json=wrong)
                return {"kind": kind, "request": "POST /api/v1/auth/login with a wrong password",
                        **_probe_result(response)}
            started = time.monotonic()
            responses = await asyncio.gather(
                *(client.post(login, json=wrong) for _ in range(BURST_SIZE)),
                return_exceptions=True,
            )
    except httpx.HTTPError as exc:
        raise DependencyUnavailableError(
            f"the gateway at {settings.GATEWAY_URL} did not answer ({type(exc).__name__}).", {}
        ) from exc
    answered = [r for r in responses if isinstance(r, httpx.Response)]
    counts = Counter(r.status_code for r in answered)
    refused = next((r for r in answered if r.status_code == 429), None)
    return {
        "kind": kind,
        "request": f"{BURST_SIZE} concurrent POST /api/v1/auth/login with a wrong password",
        "seconds": round(time.monotonic() - started, 2),
        "counts": {str(code): n for code, n in sorted(counts.items())},
        "noAnswer": len(responses) - len(answered),
        "sample429": _probe_result(refused) if refused is not None else None,
    }
