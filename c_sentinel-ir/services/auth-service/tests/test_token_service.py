"""
test_token_service.py - the JWT contract.

This is the file the build-step-5 verification rests on: a valid login must
return a decodable HS256 token carrying `sub`, `role` and `exp`, and an expired
token must be rejected. The clock is injected rather than waited on, so expiry
is tested in milliseconds instead of an hour.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from jose import jwt

from common.errors import AuthenticationError

from app.services.token_service import TOKEN_ISSUER, decode_token, issue_token

SECRET = "test-secret-at-least-16-chars"
ALGORITHM = "HS256"


def _issue(**overrides) -> str:
    """
    Purpose: mint a token with the test defaults, overridable per test.
    Inputs:  any keyword `issue_token` accepts.
    Output:  the encoded JWT.
    """
    arguments = {
        "username": "analyst",
        "role": "analyst",
        "secret": SECRET,
        "algorithm": ALGORITHM,
        "expiry_minutes": 60,
    }
    arguments.update(overrides)
    return issue_token(**arguments)


def test_token_is_hs256() -> None:
    """The header must name HS256 - the gateway is configured for it."""
    header = jwt.get_unverified_header(_issue())
    assert header["alg"] == "HS256"


def test_token_carries_sub_role_and_exp() -> None:
    """The three claims the verification and the gateway both require."""
    claims = jwt.decode(_issue(), SECRET, algorithms=[ALGORITHM])
    assert claims["sub"] == "analyst"
    assert claims["role"] == "analyst"
    assert isinstance(claims["exp"], int)


def test_token_carries_the_issuer_kong_matches_on() -> None:
    """
    Kong's JWT plugin looks its signing credential up by `iss`, so the claim is
    part of the contract with gateway/kong.yml, not decoration.
    """
    claims = jwt.decode(_issue(), SECRET, algorithms=[ALGORITHM])
    assert claims["iss"] == TOKEN_ISSUER


def test_expiry_follows_the_configured_lifetime() -> None:
    """Expiry comes from settings, never hardcoded."""
    now = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)
    # `verify_exp` off: this test asserts the ARITHMETIC of iat/exp against a
    # pinned `now`, not that expiry is enforced - which is
    # test_expired_token_is_rejected's job below. Left on, the token issued into
    # a fixed past is already expired against the real clock, so the test passed
    # only in the fifteen minutes after it was written and failed every run
    # since (carried since step 5).
    claims = jwt.decode(
        _issue(expiry_minutes=15, now=now),
        SECRET,
        algorithms=[ALGORITHM],
        options={"verify_exp": False},
    )
    assert claims["iat"] == int(now.timestamp())
    assert claims["exp"] == int((now + timedelta(minutes=15)).timestamp())


def test_decode_returns_the_claims() -> None:
    """A freshly issued token decodes to its own claims."""
    claims = decode_token(_issue(role="admin"), secret=SECRET, algorithm=ALGORITHM)
    assert claims.sub == "analyst"
    assert claims.role == "admin"
    assert claims.iss == TOKEN_ISSUER


def test_expired_token_is_rejected() -> None:
    """
    The build-step-5 verification line. The token is issued into the past, so
    it is already expired by the time it is decoded.
    """
    long_ago = datetime.now(timezone.utc) - timedelta(hours=3)
    expired = _issue(expiry_minutes=1, now=long_ago)
    with pytest.raises(AuthenticationError) as exc:
        decode_token(expired, secret=SECRET, algorithm=ALGORITHM)
    assert exc.value.details["reason"] == "expired"
    assert exc.value.status_code == 401


def test_tampered_signature_is_rejected() -> None:
    """A token re-signed with another key is not ours."""
    forged = jwt.encode(
        {"sub": "attacker", "role": "admin", "iss": TOKEN_ISSUER, "exp": 9999999999},
        "a-different-secret-entirely",
        algorithm=ALGORITHM,
    )
    with pytest.raises(AuthenticationError) as exc:
        decode_token(forged, secret=SECRET, algorithm=ALGORITHM)
    assert exc.value.details["reason"] == "invalid_token"


def test_altered_payload_is_rejected() -> None:
    """Flipping a character in the payload breaks the signature."""
    token = _issue()
    header, payload, signature = token.split(".")
    altered = f"{header}.{payload[:-2]}XY.{signature}"
    with pytest.raises(AuthenticationError):
        decode_token(altered, secret=SECRET, algorithm=ALGORITHM)


def test_token_from_another_issuer_is_rejected() -> None:
    """
    A token correctly signed with our secret but issued by something else is
    still refused: the issuer claim is checked, not merely carried.
    """
    foreign = jwt.encode(
        {
            "sub": "analyst",
            "role": "admin",
            "iss": "some-other-system",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm=ALGORITHM,
    )
    with pytest.raises(AuthenticationError):
        decode_token(foreign, secret=SECRET, algorithm=ALGORITHM)


def test_token_without_expiry_is_rejected() -> None:
    """A token that never expires is not one this system issues."""
    everlasting = jwt.encode(
        {"sub": "analyst", "role": "admin", "iss": TOKEN_ISSUER},
        SECRET,
        algorithm=ALGORITHM,
    )
    with pytest.raises(AuthenticationError):
        decode_token(everlasting, secret=SECRET, algorithm=ALGORITHM)


def test_garbage_and_empty_tokens_are_rejected() -> None:
    """Neither a non-token nor an absent one may decode."""
    for candidate in ("", "not.a.token", "abc"):
        with pytest.raises(AuthenticationError):
            decode_token(candidate, secret=SECRET, algorithm=ALGORITHM)
