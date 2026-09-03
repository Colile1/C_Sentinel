"""
schemas.py - the request and response bodies of auth-service's public API.

Pydantic v2 models, separate from the SQLAlchemy tables on purpose: `UserRead`
exists so that no route can accidentally serialise `password_hash` by returning
an ORM object directly.

Author: Colile
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator


# A deliberately loose check: something, an @, something, a dot, something.
# Full RFC 5322 validation needs a library, and this field is an identifier
# here rather than a delivery address - nothing in the system sends mail.
_EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


class Role(str, Enum):
    """
    The two roles the system recognises. `admin` may manage users and delete
    incidents; `analyst` is everything else. Copied verbatim into the JWT.
    """

    ADMIN = "admin"
    ANALYST = "analyst"


class LoginRequest(BaseModel):
    """
    Purpose: the body of `POST /api/v1/auth/login`.
    Inputs:  username and password as typed by the client.
    Output:  a validated request. Length bounds only - a wrong username must
             fail as a 401 from the business logic, identically to a wrong
             password, so nothing here rejects an unknown-looking name early.
    """

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class TokenResponse(BaseModel):
    """
    Purpose: the body of a successful login.
    Inputs:  the issued token and the seconds it remains valid.
    Output:  the standard bearer-token response shape.
    """

    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires.")
    role: Role


class UserCreate(BaseModel):
    """
    Purpose: the body of `POST /api/v1/auth/users`, admin only.
    Inputs:  the new account's username, email, password and role.
    Output:  a validated request. The password's own rules are enforced in
             `password_service`, the one place hashing happens.
    """

    username: str = Field(min_length=3, max_length=64)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=256)
    role: Role = Role.ANALYST

    @field_validator("email")
    @classmethod
    def _validate_email(cls, value: str) -> str:
        """
        Purpose: reject an address that is obviously not one, without adding
                 `email-validator` to the pinned dependencies for a field the
                 system never sends mail to.
        Inputs:  the supplied address.
        Output:  the address, trimmed and lower-cased.
        """
        address = value.strip().lower()
        if not _EMAIL_PATTERN.fullmatch(address):
            raise ValueError("must be an email address, e.g. analyst@example.com")
        return address


class UserRead(BaseModel):
    """
    Purpose: how a user is returned to a client.
    Inputs:  a `User` row, read by attribute.
    Output:  the safe subset of the row. There is deliberately no field for the
             password hash, so it cannot leak through this model.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    role: Role
    is_active: bool
    created_at: datetime


class VerifyResponse(BaseModel):
    """
    Purpose: the body of `GET /api/v1/auth/verify`.
    Inputs:  the claims decoded from the presented token.
    Output:  confirmation plus the claims, so a client can see who the gateway
             will treat it as and when the token dies.
    """

    valid: bool = True
    username: str
    role: Role
    issued_at: int
    expires_at: int
