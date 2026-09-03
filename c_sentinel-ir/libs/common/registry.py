"""
registry.py - Consul self-registration and clean deregistration.

Each service registers itself with Consul at startup, not from a static file,
because the marker wants to watch instances appear in the UI (registry/README).
The registration carries an HTTP health check pointing at the service's own
/health, which Consul then polls.

Discovery is never on the request path: if Consul is unreachable at startup the
service logs a warning and keeps serving. A registry outage must not take the
application down.

Author: Colile
"""

from __future__ import annotations

import logging

import consul as consul_client

from common.config import Settings

_logger = logging.getLogger(__name__)

# How often Consul polls /health, and how long an instance may stay critical
# before Consul removes it. Kept here rather than in a JSON file because the
# Consul container is not built until build step 9; these are the values that
# file will carry.
_HEALTH_CHECK_INTERVAL = "10s"
_HEALTH_CHECK_TIMEOUT = "5s"
_DEREGISTER_CRITICAL_AFTER = "1m"


def _service_id(settings: Settings) -> str:
    """
    Purpose: the unique id for this instance, so several instances of one
             service can register without colliding.
    Inputs:  settings - the service configuration.
    Output:  "<service-name>-<host>-<port>".
    """
    return f"{settings.service_name}-{settings.registry_address}-{settings.service_port}"


def _client(settings: Settings) -> consul_client.Consul:
    """Purpose: a Consul client aimed at the configured agent.
    Inputs: settings. Output: a consul.Consul instance."""
    return consul_client.Consul(host=settings.consul_host, port=settings.consul_port)


def register_service(settings: Settings) -> None:
    """
    Purpose: register this service instance with Consul, with a health check
             against its own /health endpoint.
    Inputs:  settings - carries the service name, the address other containers
             reach it on, the port, and the Consul agent location.
    Output:  None. On any failure, a warning is logged and the service
             continues - discovery is not on the request path.
    """
    if not settings.consul_enabled:
        _logger.info(
            "Consul registration skipped: CONSUL_ENABLED is false",
            extra={"service": settings.service_name},
        )
        return

    address = settings.registry_address
    health_url = f"http://{address}:{settings.service_port}/health"
    try:
        client = _client(settings)
        client.agent.service.register(
            name=settings.service_name,
            service_id=_service_id(settings),
            address=address,
            port=settings.service_port,
            check=consul_client.Check.http(
                health_url,
                interval=_HEALTH_CHECK_INTERVAL,
                timeout=_HEALTH_CHECK_TIMEOUT,
                deregister=_DEREGISTER_CRITICAL_AFTER,
            ),
        )
        _logger.info(
            "Registered with Consul",
            extra={
                "service": settings.service_name,
                "address": f"{address}:{settings.service_port}",
                "healthCheck": health_url,
            },
        )
    except Exception as exc:  # noqa: BLE001 - a registry outage must not crash the service
        _logger.warning(
            "Consul registration failed, continuing without it: %s",
            exc,
            extra={"service": settings.service_name, "consul": settings.consul_host},
        )


def deregister_service(settings: Settings) -> None:
    """
    Purpose: remove this instance from Consul on clean shutdown, so it
             disappears from the UI immediately rather than after the
             deregister-critical timeout.
    Inputs:  settings - as register_service.
    Output:  None. Failure is logged, not raised: the process is stopping.
    """
    if not settings.consul_enabled:
        return
    try:
        _client(settings).agent.service.deregister(_service_id(settings))
        _logger.info(
            "Deregistered from Consul", extra={"service": settings.service_name}
        )
    except Exception as exc:  # noqa: BLE001 - shutdown must not be blocked by Consul
        _logger.warning(
            "Consul deregistration failed: %s",
            exc,
            extra={"service": settings.service_name},
        )
