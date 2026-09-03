"""
token_service.py - issue and decode the HS256 JWTs the whole system trusts.

auth-service is the only issuer. The gateway validates these same tokens itself
against the shared secret at build step 10, so the claim set here is a contract
with `gateway/kong.yml` as much as with this service: `iss` is what Kong's JWT
plugin matches against its credential key, and `sub`, `role` and `exp` are what
the services and the mark schedule require.

Pure: settings in, string out. No database, no HTTP, no FastAPI, and the clock
is injectable so expiry is unit-testable without waiting an hour.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from pydantic import BaseModel, ConfigDict

from common.errors import AuthenticationError

# Kong's JWT plugin looks the signing credential up by the token's `iss`. This
# value is therefore also the `key` of the JWT credential in gateway/kong.yml.
TOKEN_ISSUER = "sentinel-ir-auth"


class TokenClaims(BaseModel):
    """
    Purpose: the decoded, validated contents of a Sentinel-IR access token.
    Inputs:  the claims below, as they appear in the token.
    Output:  an immutable claims object. `sub` is the username, not the row id,
             because it is what the event stream's `userId` carries and what a
             marker reading a log line can recognise.
    """

    model_config = ConfigDict(frozen=True)

    sub: str
    role: str
    iss: str
    iat: int
    exp: int


def issue_token(
    *,
    username: str,
    role: str,
    secret: str,
    algorithm: str,
    expiry_minutes: int,
    now: datetime | None = None,
) -> str:
    """
    Purpose: mint the access token a successful login returns.
    Inputs:  username - becomes `sub`.
             role - becomes `role`, and is what the admin-only routes check.
             secret / algorithm / expiry_minutes - from settings, never
                     hardcoded, so the gateway and the service cannot drift.
             now - injectable clock, supplied only by tests.
    Output:  the encoded JWT as a string.
    """
    issued_at = now or datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=expiry_minutes)
    claims = {
        "sub": username,
        "role": role,
        "iss": TOKEN_ISSUER,
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    return jwt.encode(claims, secret, algorithm=algorithm)


def decode_token(token: str, *, secret: str, algorithm: str) -> TokenClaims:
    """
    Purpose: verify a token's signature, issuer and expiry, and return its
             claims. The single place a token is trusted inside this service.
    Inputs:  token - the raw JWT.
             secret / algorithm - from settings; must match the issuer's.
    Output:  the validated `TokenClaims`.
    Raises:  `AuthenticationError` for an expired, tampered, wrongly-issued or
             structurally invalid token. The message distinguishes expiry from
             the rest because that is the one case a client can act on; it never
             reveals anything about the key.
    """
    if not token:
        raise AuthenticationError(
            "No token was supplied.", {"reason": "missing_token"}
        )
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[algorithm],
            issuer=TOKEN_ISSUER,
            options={"require_exp": True, "require_sub": True},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError(
            "The token has expired; log in again.", {"reason": "expired"}
        ) from exc
    except JWTError as exc:
        raise AuthenticationError(
            "The token is not valid.", {"reason": "invalid_token"}
        ) from exc

    try:
        return TokenClaims(**payload)
    except Exception as exc:
        # A correctly signed token whose claim set we do not recognise is still
        # a token we must refuse - it was issued by something that is not us.
        raise AuthenticationError(
            "The token is missing required claims.", {"reason": "invalid_claims"}
        ) from exc
