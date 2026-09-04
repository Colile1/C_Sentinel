"""
load_topology.py - source 1 of 3: what the application *is*.

Services and their internal ports, the endpoints the gateway exposes for each
and whether a token is required, the one real `incident-service -> asset-service`
dependency, the seeded user accounts with their roles, and the asset register.

These facts are static configuration - they come from `deploy/docker-compose.yml`,
`gateway/kong.yml` and the seed files, none of which change at runtime - so they
are declared here as data rather than scraped from a running stack. `topology()`
turns them into `Write` operations; a test checks the operations, `main` applies
them.

Author: Colile
"""

from __future__ import annotations

import json
from pathlib import Path

from kg.loader.writes import Write

_SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"
_LOADER = "topology"

# Services, from the Compose file and Kong's upstream ports.
_SERVICES = (
    {"name": "auth-service", "port": 8001,
     "description": "Users, login, JWT issue and verify."},
    {"name": "incident-service", "port": 8002,
     "description": "Incident CRUD and severity workflow. Calls asset-service."},
    {"name": "asset-service", "port": 8003,
     "description": "The asset register."},
    {"name": "api-gateway", "port": 8000,
     "description": "Kong DB-less gateway: routing, JWT validation, rate limiting."},
)

# Endpoints, from gateway/kong.yml routes. `protected` is False only for login,
# the one route that issues tokens and so cannot require one.
_ENDPOINTS = (
    {"path": "/api/v1/auth/login", "method": "POST", "protected": False,
     "service": "auth-service"},
    {"path": "/api/v1/auth/verify", "method": "GET", "protected": True,
     "service": "auth-service"},
    {"path": "/api/v1/auth/users", "method": "POST", "protected": True,
     "service": "auth-service"},
    {"path": "/api/v1/incidents", "method": "GET", "protected": True,
     "service": "incident-service"},
    {"path": "/api/v1/assets", "method": "GET", "protected": True,
     "service": "asset-service"},
)

# The one cross-service call in the system, behind the retry + circuit breaker.
_DEPENDENCIES = (
    {"caller": "incident-service", "callee": "asset-service"},
)


def _merge_service(service: dict) -> Write:
    """Purpose: one `MERGE` for a Service node. Inputs: the service dict.
    Output: a `Write`."""
    return Write(
        "MERGE (s:Service {name: $name}) "
        "SET s.port = $port, s.description = $description",
        dict(service),
        _LOADER,
    )


def _merge_endpoint(endpoint: dict) -> list[Write]:
    """Purpose: an Endpoint node and the `EXPOSES` edge from its service.
    Inputs: the endpoint dict. Output: two `Write`s."""
    return [
        Write(
            "MERGE (e:Endpoint {path: $path}) "
            "SET e.method = $method, e.protected = $protected",
            {"path": endpoint["path"], "method": endpoint["method"],
             "protected": endpoint["protected"]},
            _LOADER,
        ),
        Write(
            "MATCH (s:Service {name: $service}) "
            "MATCH (e:Endpoint {path: $path}) "
            "MERGE (s)-[:EXPOSES]->(e)",
            {"service": endpoint["service"], "path": endpoint["path"]},
            _LOADER,
        ),
    ]


def _merge_dependency(dependency: dict) -> Write:
    """Purpose: the `DEPENDS_ON` edge between two services.
    Inputs: the dependency dict. Output: a `Write`."""
    return Write(
        "MATCH (a:Service {name: $caller}) "
        "MATCH (b:Service {name: $callee}) "
        "MERGE (a)-[:DEPENDS_ON]->(b)",
        dict(dependency),
        _LOADER,
    )


def _merge_user(user: dict) -> list[Write]:
    """Purpose: a User node, its Role node, and the `HAS_ROLE` edge.
    Inputs: a seed user dict. Output: three `Write`s."""
    return [
        Write(
            "MERGE (u:User {username: $username}) SET u.role = $role",
            {"username": user["username"], "role": user["role"]},
            _LOADER,
        ),
        Write("MERGE (:Role {name: $role})", {"role": user["role"]}, _LOADER),
        Write(
            "MATCH (u:User {username: $username}) "
            "MATCH (r:Role {name: $role}) "
            "MERGE (u)-[:HAS_ROLE]->(r)",
            {"username": user["username"], "role": user["role"]},
            _LOADER,
        ),
    ]


def _merge_asset(asset: dict) -> Write:
    """Purpose: one `MERGE` for an Asset node. Inputs: a seed asset dict.
    Output: a `Write`."""
    return Write(
        "MERGE (a:Asset {name: $name}) "
        "SET a.assetType = $asset_type, a.criticality = $criticality",
        {"name": asset["name"], "asset_type": asset["asset_type"],
         "criticality": asset["criticality"]},
        _LOADER,
    )


def _seed_users() -> list[dict]:
    """Purpose: the seeded accounts plus the bootstrap admin, which the seed
    file deliberately omits. Inputs: none. Output: a list of user dicts."""
    users = [{"username": "admin", "role": "admin"}]
    path = _SEED_DIR / "users.json"
    if path.exists():
        users.extend(json.loads(path.read_text(encoding="utf-8"))["users"])
    return users


def _seed_assets() -> list[dict]:
    """Purpose: the seeded asset register. Inputs: none. Output: a list of
    asset dicts, empty if the seed file is absent."""
    path = _SEED_DIR / "assets.json"
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))["assets"]


def topology() -> list[Write]:
    """
    Purpose: the whole application-topology source as idempotent writes -
             services, endpoints and their `EXPOSES` edges, the one
             `DEPENDS_ON` edge, users with roles, and the asset register.
    Inputs:  none; reads the seed files if present.
    Output:  a list of `Write`, in dependency order (nodes before the edges
             that MATCH them).
    """
    writes: list[Write] = [_merge_service(s) for s in _SERVICES]
    for endpoint in _ENDPOINTS:
        writes.extend(_merge_endpoint(endpoint))
    writes.extend(_merge_dependency(d) for d in _DEPENDENCIES)
    for user in _seed_users():
        writes.extend(_merge_user(user))
    writes.extend(_merge_asset(a) for a in _seed_assets())
    return writes
