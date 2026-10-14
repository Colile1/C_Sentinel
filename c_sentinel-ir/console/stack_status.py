"""
stack_status.py - one health probe per component, run in parallel.

The read-only twin of `scripts/verify_stack.py` for the UI: it changes nothing,
it only asks each component whether it is up. Unlike the preflight it does not
shell out to `docker compose ps` - the console must load on a machine with no
Docker at all and say so plainly, rather than fail.

A probe that gets *any* HTTP answer from the gateway counts it as up: Kong
answering 401 to an unauthenticated call is Kong working (D-21).

Author: Colile
"""

from __future__ import annotations

import asyncio
import os
import socket
from dataclasses import asdict, dataclass
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter

from console import settings

router = APIRouter(prefix="/console/api", tags=["status"])


@dataclass(frozen=True)
class Probe:
    """
    Purpose: one component to check - what it is, which layer it belongs to,
             the URL to probe, and the page a person would open for it.
    Inputs:  set in `PROBES` at module load.
    Output:  consumed by `_check`.
    """

    name: str
    layer: str
    url: str
    link: str
    any_status_is_up: bool = False


PROBES: tuple[Probe, ...] = (
    Probe("Kong gateway", "Edge", f"{settings.GATEWAY_URL}/api/v1/incidents",
          f"{settings.KONG_STATUS_URL}/metrics", any_status_is_up=True),
    *(
        Probe(name, "Services", f"{url}/health", f"{url}/docs")
        for name, url in settings.SERVICE_URLS.items()
    ),
    Probe("Consul registry", "Platform", f"{settings.CONSUL_URL}/v1/status/leader",
          f"{settings.CONSUL_URL}/ui"),
    Probe("Prometheus", "Observability", f"{settings.PROMETHEUS_URL}/-/healthy",
          f"{settings.PROMETHEUS_URL}/targets"),
    Probe("Grafana", "Observability", f"{settings.GRAFANA_URL}/api/health",
          settings.GRAFANA_URL),
    Probe("Neo4j", "Knowledge", settings.NEO4J_BROWSER_URL,
          f"{settings.NEO4J_BROWSER_URL}/browser/"),
)


@dataclass(frozen=True)
class ProbeResult:
    """Purpose: what one probe found. Output: serialised for the UI."""

    name: str
    layer: str
    link: str
    up: bool
    detail: str


async def _check(client: httpx.AsyncClient, probe: Probe) -> ProbeResult:
    """
    Purpose: probe one component.
    Inputs:  client - a shared async client; probe - what to check.
    Output:  a `ProbeResult`; never raises.
    """
    try:
        response = await client.get(probe.url)
    except httpx.HTTPError as exc:
        return ProbeResult(probe.name, probe.layer, probe.link, False,
                           f"no answer ({type(exc).__name__})")
    up = probe.any_status_is_up or response.status_code < 400
    return ProbeResult(probe.name, probe.layer, probe.link, up,
                       f"HTTP {response.status_code}")


def bolt_reachable(timeout: float = 1.0) -> bool:
    """
    Purpose: whether Neo4j's Bolt port accepts a connection - checked before a
             graph call so an offline graph fails in a second, not after the
             driver's long connection timeout.
    Inputs:  timeout - seconds to wait.
    Output:  True when a TCP connection to NEO4J_URI opens.
    """
    parsed = urlparse(os.environ.get("NEO4J_URI", "bolt://localhost:7687"))
    try:
        with socket.create_connection(
            (parsed.hostname or "localhost", parsed.port or 7687), timeout=timeout
        ):
            return True
    except OSError:
        return False


@router.get("/status", summary="Health of every stack component")
async def stack_status() -> dict[str, object]:
    """
    Purpose: probe every component at once for the Overview screen.
    Inputs:  none.
    Output:  {components: [...], up: n, total: n}.
    """
    async with httpx.AsyncClient(timeout=settings.PROBE_TIMEOUT_SECONDS) as client:
        results = await asyncio.gather(*(_check(client, probe) for probe in PROBES))
    return {
        "components": [asdict(result) for result in results],
        "up": sum(result.up for result in results),
        "total": len(results),
    }


@router.get("/config", summary="Links and hints the UI needs")
def console_config() -> dict[str, object]:
    """
    Purpose: the external tool links and the sign-in hint, so no address is
             hardcoded in the browser code.
    Inputs:  none.
    Output:  a JSON object of links plus the bootstrap admin username.
    """
    return {
        "adminUsername": settings.BOOTSTRAP_ADMIN_USERNAME,
        "gatewayUrl": settings.GATEWAY_URL,
        "tools": [
            {"name": "Grafana dashboards", "url": settings.GRAFANA_URL, "icon": "monitoring"},
            {"name": "Prometheus targets", "url": f"{settings.PROMETHEUS_URL}/targets", "icon": "query_stats"},
            {"name": "Consul registry", "url": f"{settings.CONSUL_URL}/ui", "icon": "hub"},
            {"name": "Neo4j Browser", "url": f"{settings.NEO4J_BROWSER_URL}/browser/", "icon": "share"},
            *(
                {"name": f"{name} OpenAPI", "url": f"{url}/docs", "icon": "api"}
                for name, url in settings.SERVICE_URLS.items()
            ),
        ],
    }
