"""
test_error_shape.py - every typed error serialises to the one documented shape.

`docs/api.md` fixes the error body as exactly `{"error", "message", "details"}`
with `details` an object, and fixes the status code for each condition. This
asserts every `SentinelError` subclass obeys both.

Runs without a container, a network or a database.

Author: Colile
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "libs"))

from common import errors  # noqa: E402

# The status code docs/api.md documents for each typed error.
DOCUMENTED_STATUS = {
    errors.ConfigurationError: 500,
    errors.NotFoundError: 404,
    errors.ValidationError: 422,
    errors.AuthenticationError: 401,
    errors.AuthorisationError: 403,
    errors.ConflictError: 409,
    errors.DependencyUnavailableError: 503,
}

ALL_ERROR_CLASSES = [
    obj
    for obj in vars(errors).values()
    if isinstance(obj, type)
    and issubclass(obj, errors.SentinelError)
    and obj is not errors.SentinelError
]


@pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
def test_every_error_has_a_documented_status_code(error_class):
    """
    Purpose: no typed error exists without `docs/api.md` fixing its status - an
             added error class fails here until it is documented above.
    Inputs:  each SentinelError subclass.
    Output:  assertions; no return.
    """
    assert error_class in DOCUMENTED_STATUS, (
        f"{error_class.__name__} has no documented status code in this test"
    )
    assert error_class.status_code == DOCUMENTED_STATUS[error_class]


@pytest.mark.parametrize("error_class", ALL_ERROR_CLASSES)
def test_payload_is_exactly_the_documented_shape(error_class):
    """
    Purpose: `to_payload()` returns exactly `error`, `message`, `details`, with
             `details` a dict.
    Inputs:  each SentinelError subclass.
    Output:  assertions; no return.
    """
    payload = error_class("something went wrong", {"field": "x"}).to_payload()
    assert set(payload) == {"error", "message", "details"}
    assert payload["error"] == error_class.error_code
    assert payload["message"] == "something went wrong"
    assert isinstance(payload["details"], dict)


def test_details_defaults_to_an_empty_object_not_none():
    """
    Purpose: an error raised without details still serialises `details` as `{}`,
             which `docs/api.md` requires.
    Inputs:  none.
    Output:  assertions; no return.
    """
    payload = errors.NotFoundError("no such incident").to_payload()
    assert payload["details"] == {}


def test_error_codes_are_unique():
    """
    Purpose: two errors sharing an `error_code` would make the code ambiguous to
             a client.
    Inputs:  none.
    Output:  assertions; no return.
    """
    codes = [cls.error_code for cls in ALL_ERROR_CLASSES]
    assert len(codes) == len(set(codes)), f"duplicate error codes: {codes}"
