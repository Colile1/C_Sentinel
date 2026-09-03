"""
health.py - the shared /health and /health/live endpoints for every service.

Consul polls /health on the interval in the registry configuration, and the
gateway and the demo both read it. The endpoint reports two things: that the
process is alive, and whether the service's own database answers. A configured
but unreachable database makes the service unhealthy (503) so Consul marks the
instance critical; liveness alone is served separately at /health/live for the
container's own restart policy, which must not flap when the database blips.

Framework-coupled, so it lives here rather than in errors.py or logging.py -
see DECISIONS.md D-06.

Author: Colile
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# A database check is either a plain bool or an async callable returning one.
DatabaseCheck = Callable[[], Awaitable[bool]] | Callable[[], bool]


def build_health_router(
    service_name: str,
    check_database: DatabaseCheck | None = None,
) -> APIRouter:
    """
    Purpose: build the router carrying /health and /health/live, identical
             across all three services.
    Inputs:  service_name - stamped into the response body.
             check_database - optional; returns True when this service's own
                              database is reachable. None means the service has
                              no database yet, and /health reports liveness only.
    Output:  an APIRouter to include on the application with no prefix.
    """
    router = APIRouter(tags=["operational"])

    async def _database_reachable() -> bool:
        """Purpose: run the caller's check, sync or async, as a bool.
        Inputs: none. Output: True when the database answered."""
        if check_database is None:
            return True
        result = check_database()
        if isinstance(result, bool):
            return result
        return await result

    @router.get("/health/live", include_in_schema=False)
    async def health_live() -> dict[str, str]:
        """
        Purpose: bare liveness for the container restart policy. Never touches
                 the database, so a database outage does not restart the app.
        Inputs:  none.
        Output:  {"status": "alive", "service": <name>}.
        """
        return {"status": "alive", "service": service_name}

    @router.get("/health")
    async def health() -> JSONResponse:
        """
        Purpose: the endpoint Consul polls. Reports liveness and database
                 reachability together.
        Inputs:  none.
        Output:  200 with {"status": "healthy", ...} when the database answers
                 or the service has none; 503 with {"status": "unhealthy", ...}
                 when a configured database does not answer.
        """
        has_database = check_database is not None
        reachable = await _database_reachable()
        healthy = reachable or not has_database
        body = {
            "status": "healthy" if healthy else "unhealthy",
            "service": service_name,
            "checks": {
                "database": (
                    "ok" if reachable else "unreachable"
                )
                if has_database
                else "not_configured"
            },
        }
        return JSONResponse(status_code=200 if healthy else 503, content=body)

    return router
