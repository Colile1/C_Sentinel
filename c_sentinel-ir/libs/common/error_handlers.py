"""
error_handlers.py - the single place Sentinel-IR errors become HTTP responses.

Kept apart from `errors.py` so the exception types stay importable by business
logic without dragging FastAPI in with them. Every service calls
`install_error_handlers(app)` once, in `app/main.py`, and no router ever builds
an error response by hand.

Author: Colile
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from common.errors import SentinelError

_logger = logging.getLogger(__name__)


def install_error_handlers(app: FastAPI) -> None:
    """
    Purpose: register the handlers that turn exceptions into JSON responses,
             so error shape is identical across all three services.
    Inputs:  app - the FastAPI application to install the handlers onto.
    Output:  None. The app is mutated in place.
    """

    @app.exception_handler(SentinelError)
    async def _handle_sentinel_error(request: Request, exc: SentinelError) -> JSONResponse:
        """Render a deliberate, typed failure at its declared status code."""
        _logger.warning(
            "Handled error: %s",
            exc.message,
            extra={"errorCode": exc.error_code, "path": request.url.path},
        )
        return JSONResponse(status_code=exc.status_code, content=exc.to_payload())

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Give framework-raised HTTP errors the same body shape as our own."""
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": "HTTP_ERROR",
                "message": str(exc.detail),
                "details": {},
            },
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        """
        Catch what nothing else claimed. The cause is logged with its traceback;
        the client is told only that the service failed, never the internals.
        """
        _logger.exception(
            "Unhandled error: %s", exc, extra={"path": request.url.path}
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "INTERNAL_ERROR",
                "message": "The service failed to complete the request.",
                "details": {},
            },
        )
