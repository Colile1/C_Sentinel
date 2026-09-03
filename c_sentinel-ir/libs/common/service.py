"""
service.py - the one wiring every Sentinel-IR service shares.

The three services differ only in their routers and their database. Everything
else - JSON logging, the correlation-id and security-event middleware, the
typed-error handlers, the Prometheus /metrics endpoint, the /health router and
Consul self-registration - is identical, and identical things belong in one
place so they cannot drift. `create_service_app` builds that shell; each
service's app/main.py adds only its own routers to it.

This is a mild departure from libs/common/README.md, which puts the wiring in
each app/main.py - see DECISIONS.md D-08.

Author: Colile
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from prometheus_fastapi_instrumentator import Instrumentator

from common.config import Settings, load_settings
from common.error_handlers import install_error_handlers
from common.health import DatabaseCheck, build_health_router
from common.logging import configure_logging
from common.middleware import CorrelationIdMiddleware, SecurityEventMiddleware
from common.registry import deregister_service, register_service


def create_service_app(
    service_name: str,
    *,
    check_database: DatabaseCheck | None = None,
    settings: Settings | None = None,
    on_startup: Callable[[], None] | None = None,
    on_shutdown: Callable[[], None] | None = None,
) -> FastAPI:
    """
    Purpose: build the fully-wired application shell a service starts from, so
             /health, /metrics, structured logging, correlation, the security
             event stream and Consul registration are present before the
             service adds a single route of its own.
    Inputs:  service_name - the service's identity, e.g. "asset-service".
             check_database - optional callable reporting this service's own
                              database reachability, passed straight to the
                              health router. None until the service has a
                              database (build step 6 for asset-service).
             settings - injected in tests to avoid reading the environment;
                        production passes None and the environment is read once.
             on_startup / on_shutdown - optional extra lifespan hooks the
                                        service runs after registration and
                                        before deregistration.
    Output:  a FastAPI app. The caller mounts its routers and nothing else.
    """
    resolved = settings or load_settings(service_name)
    configure_logging(resolved.service_name, resolved.log_level)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Register with Consul on the way up, deregister on the way down."""
        register_service(resolved)
        if on_startup is not None:
            on_startup()
        try:
            yield
        finally:
            if on_shutdown is not None:
                on_shutdown()
            deregister_service(resolved)

    app = FastAPI(
        title=f"Sentinel-IR {service_name}",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Order matters: CorrelationIdMiddleware must run first so the id is bound
    # before SecurityEventMiddleware builds any event. Starlette runs the
    # last-added middleware outermost, so it is added last.
    app.add_middleware(SecurityEventMiddleware, service_name=resolved.service_name)
    app.add_middleware(CorrelationIdMiddleware)

    install_error_handlers(app)

    # /metrics is Prometheus exposition, scraped by nothing but Prometheus. The
    # instrumentator also records request duration and count per handler.
    Instrumentator().instrument(app).expose(app, include_in_schema=False)

    app.include_router(build_health_router(resolved.service_name, check_database))

    return app
