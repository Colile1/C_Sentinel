"""
test_errors.py - unit tests for the typed error hierarchy.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import (
    AuthenticationError,
    AuthorisationError,
    ConfigurationError,
    ConflictError,
    DependencyUnavailableError,
    NotFoundError,
    SentinelError,
    ValidationError,
)

_EXPECTED_STATUS = [
    (ConfigurationError, 500, "CONFIGURATION_ERROR"),
    (NotFoundError, 404, "NOT_FOUND"),
    (ValidationError, 422, "VALIDATION_ERROR"),
    (AuthenticationError, 401, "AUTHENTICATION_ERROR"),
    (AuthorisationError, 403, "AUTHORISATION_ERROR"),
    (ConflictError, 409, "CONFLICT"),
    (DependencyUnavailableError, 503, "DEPENDENCY_UNAVAILABLE"),
]


@pytest.mark.parametrize(("error_class", "status", "code"), _EXPECTED_STATUS)
def test_each_error_carries_its_status_and_code(
    error_class: type[SentinelError], status: int, code: str
) -> None:
    """The status-to-type mapping is the contract error_handlers relies on."""
    error = error_class("Something specific went wrong")

    assert error.status_code == status
    assert error.error_code == code


@pytest.mark.parametrize(("error_class", "status", "code"), _EXPECTED_STATUS)
def test_every_error_is_a_sentinel_error(
    error_class: type[SentinelError], status: int, code: str
) -> None:
    """One handler registration must catch all of them."""
    assert issubclass(error_class, SentinelError)
    assert isinstance(error_class("message"), Exception)


def test_payload_carries_code_message_and_details() -> None:
    """The response body shape is identical for every service."""
    error = NotFoundError("Asset 7 does not exist", {"assetId": 7})

    assert error.to_payload() == {
        "error": "NOT_FOUND",
        "message": "Asset 7 does not exist",
        "details": {"assetId": 7},
    }


def test_details_default_to_an_empty_mapping() -> None:
    """Callers must never have to guard against a None details field."""
    assert NotFoundError("Not found").to_payload()["details"] == {}


def test_message_is_preserved_as_the_exception_string() -> None:
    """`str(exc)` is what lands in a traceback, so it must carry the message."""
    assert str(AuthenticationError("Wrong password")) == "Wrong password"
