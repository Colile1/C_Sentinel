"""
errors.py - the typed error hierarchy shared by every Sentinel-IR service.

Errors are raised as specific types by business logic and mapped to HTTP status
codes in exactly one place, `install_error_handlers`, so no router writes its
own error response. Business logic here never imports FastAPI at module level.

Author: Colile
"""

from __future__ import annotations

from typing import Any


class SentinelError(Exception):
    """
    Base of every error this system raises deliberately.

    Purpose: give every deliberate failure a type, a human-readable message and
             an optional machine-readable detail payload.
    Inputs:  message - one sentence describing what went wrong and where.
             details - optional mapping of structured context, e.g. the field
                       that failed validation.
    Output:  an exception instance. `status_code` and `error_code` are set by
             the subclasses and consumed by `install_error_handlers`.
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict[str, Any]:
        """
        Purpose: render the error as the response body clients receive.
        Inputs:  none beyond the instance.
        Output:  a dict with the error code, the message and any details.
        """
        return {
            "error": self.error_code,
            "message": self.message,
            "details": self.details,
        }


class ConfigurationError(SentinelError):
    """A required setting is missing or invalid. Raised at startup, never per request."""

    status_code = 500
    error_code = "CONFIGURATION_ERROR"


class NotFoundError(SentinelError):
    """The requested entity does not exist."""

    status_code = 404
    error_code = "NOT_FOUND"


class ValidationError(SentinelError):
    """The request was well-formed but its content is not acceptable."""

    status_code = 422
    error_code = "VALIDATION_ERROR"


class AuthenticationError(SentinelError):
    """Credentials are missing, malformed or wrong. The caller is not who they claim."""

    status_code = 401
    error_code = "AUTHENTICATION_ERROR"


class AuthorisationError(SentinelError):
    """The caller is authenticated but not permitted to do this."""

    status_code = 403
    error_code = "AUTHORISATION_ERROR"


class ConflictError(SentinelError):
    """The request conflicts with current state, e.g. a duplicate unique field."""

    status_code = 409
    error_code = "CONFLICT"


class DependencyUnavailableError(SentinelError):
    """
    A downstream service could not be reached, or its circuit breaker is open.

    Raised by `http_client.ResilientClient` only when the caller declared no
    fallback. When a fallback exists the client returns it instead of raising.
    """

    status_code = 503
    error_code = "DEPENDENCY_UNAVAILABLE"
