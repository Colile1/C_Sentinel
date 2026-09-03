"""
test_password_service.py - hashing and verification.

The three things that must hold: a password verifies against its own hash, a
wrong one does not, and bcrypt's 72-byte truncation is refused rather than
applied silently - which is the failure that would otherwise let a long
password share a hash with its own prefix.

Author: Colile
"""

from __future__ import annotations

import pytest

from common.errors import ValidationError

from app.services.password_service import (
    MAX_PASSWORD_BYTES,
    MIN_PASSWORD_LENGTH,
    hash_password,
    verify_password,
)


def test_hash_and_verify_round_trip() -> None:
    """A password verifies against the hash made from it."""
    hashed = hash_password("correct-horse-battery")
    assert verify_password("correct-horse-battery", hashed) is True


def test_wrong_password_fails() -> None:
    """A different password does not verify."""
    hashed = hash_password("correct-horse-battery")
    assert verify_password("Correct-horse-battery", hashed) is False


def test_hash_is_never_the_plaintext() -> None:
    """The stored value must not contain the password."""
    plain = "correct-horse-battery"
    hashed = hash_password(plain)
    assert plain not in hashed
    assert hashed.startswith("$2b$")


def test_same_password_hashes_differently_each_time() -> None:
    """Salting means two hashes of one password differ, and both verify."""
    first = hash_password("correct-horse-battery")
    second = hash_password("correct-horse-battery")
    assert first != second
    assert verify_password("correct-horse-battery", first)
    assert verify_password("correct-horse-battery", second)


def test_short_password_is_rejected() -> None:
    """The minimum length is enforced where hashing happens."""
    with pytest.raises(ValidationError) as exc:
        hash_password("a" * (MIN_PASSWORD_LENGTH - 1))
    assert exc.value.details["field"] == "password"


def test_password_over_the_bcrypt_limit_is_rejected_not_truncated() -> None:
    """
    Bcrypt ignores everything past 72 bytes. Truncating silently would make a
    73-character password interchangeable with its own first 72 characters, so
    the limit is refused explicitly instead.
    """
    with pytest.raises(ValidationError) as exc:
        hash_password("a" * (MAX_PASSWORD_BYTES + 1))
    assert exc.value.details["field"] == "password"


def test_multibyte_password_is_measured_in_bytes() -> None:
    """The limit is bytes, not characters: a 3-byte character counts as three."""
    with pytest.raises(ValidationError):
        hash_password("€" * 25)  # 25 euro signs = 75 bytes


def test_verify_against_a_corrupt_hash_returns_false() -> None:
    """A malformed stored hash fails the login rather than the service."""
    assert verify_password("correct-horse-battery", "not-a-bcrypt-hash") is False


def test_verify_against_empty_values_returns_false() -> None:
    """Neither an empty password nor an empty hash may ever verify."""
    hashed = hash_password("correct-horse-battery")
    assert verify_password("", hashed) is False
    assert verify_password("correct-horse-battery", "") is False
