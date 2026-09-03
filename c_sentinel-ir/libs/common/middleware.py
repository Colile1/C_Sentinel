"""
middleware.py - request-scoped correlation and the per-request event pair.

Installed by every service in `app/main.py`. It reads `X-Correlation-ID` from
the incoming request, generates one when the gateway did not supply it, binds
it for the life of the request so every log line and event carries it, and
echoes it on the response so the caller can quote it.

Kept apart from `logging.py` and `correlation.py` so those stay free of any
framework import.

Author: Colile
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from common.correlation import (
    CORRELATION_ID_HEADER,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from common.events import EventType, Severity, build_event
from common.logging import emit_event

# Endpoints that exist for the platform rather than for a user. Emitting a pair
# of events for each would bury the real traffic under Consul's health polling.
_UNTRACKED_PATHS = frozenset({"/health", "/health/live", "/metrics"})

# `statusCode` is required by the schema, but a request that has only just
# arrived has no status yet. 100 Continue is the honest stand-in: it is the HTTP
# code meaning "received, still processing", so REQUEST_RECEIVED carries it and
# Phase 2 can tell an in-flight event from a completed one by the code alone.
_STATUS_IN_FLIGHT = 100


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    """
    Purpose: bind the correlation id for the request and echo it back, so one
             workflow is traceable across the gateway and all three services.
    Inputs:  the ASGI app, supplied by FastAPI when the middleware is installed.
    Output:  a middleware that mutates request state and response headers only.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Purpose: run one request with a correlation id bound to its context.
        Inputs:  request, and the next handler in the chain.
        Output:  the downstream response, carrying the correlation-id header.
        """
        correlation_id = request.headers.get(CORRELATION_ID_HEADER) or new_correlation_id()
        token = set_correlation_id(correlation_id)
        request.state.correlation_id = correlation_id
        try:
            response = await call_next(request)
            response.headers[CORRELATION_ID_HEADER] = correlation_id
            return response
        finally:
            reset_correlation_id(token)


class SecurityEventMiddleware(BaseHTTPMiddleware):
    """
    Purpose: emit the `REQUEST_RECEIVED` and `REQUEST_COMPLETED` baseline pair
             the schema requires of every service, plus `SERVICE_ERROR` on an
             unhandled 5xx. This is what gives Phase 2 its request-rate signal
             without any service writing logging code of its own.
    Inputs:  app - the ASGI app.
             service_name - the emitting service's identity.
    Output:  a middleware that emits events and alters nothing about the
             response.

    Must be installed *inside* `CorrelationIdMiddleware` so the correlation id
    is already bound when these events are built.
    """

    def __init__(self, app: object, service_name: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._service_name = service_name

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """
        Purpose: emit the event pair around one request.
        Inputs:  request, and the next handler in the chain.
        Output:  the downstream response, unmodified.
        """
        path = request.url.path
        if path in _UNTRACKED_PATHS:
            return await call_next(request)

        correlation_id = getattr(request.state, "correlation_id", None) or new_correlation_id()
        source_ip = self._client_ip(request)
        user_id = request.headers.get("X-User-Id")

        emit_event(
            build_event(
                service_name=self._service_name,
                event_type=EventType.REQUEST_RECEIVED,
                severity=Severity.LOW,
                user_id=user_id,
                source_ip=source_ip,
                endpoint=path,
                http_method=request.method,
                status_code=_STATUS_IN_FLIGHT,
                message=f"Request received for {path}",
                correlation_id=correlation_id,
            )
        )

        try:
            response = await call_next(request)
        except Exception:
            emit_event(
                build_event(
                    service_name=self._service_name,
                    event_type=EventType.SERVICE_ERROR,
                    severity=Severity.HIGH,
                    user_id=user_id,
                    source_ip=source_ip,
                    endpoint=path,
                    http_method=request.method,
                    status_code=500,
                    message=f"Unhandled error while serving {path}",
                    correlation_id=correlation_id,
                )
            )
            raise

        if response.status_code >= 500:
            emit_event(
                build_event(
                    service_name=self._service_name,
                    event_type=EventType.SERVICE_ERROR,
                    severity=Severity.HIGH,
                    user_id=user_id,
                    source_ip=source_ip,
                    endpoint=path,
                    http_method=request.method,
                    status_code=response.status_code,
                    message=f"Service returned {response.status_code} for {path}",
                    correlation_id=correlation_id,
                )
            )

        emit_event(
            build_event(
                service_name=self._service_name,
                event_type=EventType.REQUEST_COMPLETED,
                severity=Severity.LOW,
                user_id=user_id,
                source_ip=source_ip,
                endpoint=path,
                http_method=request.method,
                status_code=response.status_code,
                message=f"Request completed for {path} with {response.status_code}",
                correlation_id=correlation_id,
            )
        )
        return response

    @staticmethod
    def _client_ip(request: Request) -> str | None:
        """
        Purpose: find the real client address. Behind Kong the socket peer is
                 the gateway, so the forwarded header is preferred when present.
        Inputs:  request - the incoming request.
        Output:  the client IP, or None when it cannot be determined.
        """
        forwarded = request.headers.get("X-Forwarded-For")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else None
