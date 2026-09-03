"""
dependencies.py - the FastAPI wiring auth-service's routes depend on.

Routers stay HTTP-only by taking their collaborators from here: a session, an
`AuthService` built on it, the bearer token pulled off the header, and the
admin guard. Nothing in this file makes a decision of its own beyond refusing a
request that carries no usable credential.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from common.config import Settings, get_settings
from common.correlation import get_correlation_id
from common.errors import AuthenticationError, AuthorisationError

from app.database import SERVICE_NAME, get_session
from app.repositories.user_repository import UserRepository
from app.schemas import Role
from app.services.auth_service import AuthService
from app.services.token_service import TokenClaims
from app.services.user_admin_service import UserAdminService

_BEARER_PREFIX = "bearer "


def get_service_settings() -> Settings:
    """
    Purpose: this service's settings, as a dependency so tests can override it
             without touching the environment.
    Inputs:  none.
    Output:  the cached `Settings` for auth-service.
    """
    return get_settings(SERVICE_NAME)


def get_auth_service(
    session: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_service_settings)],
) -> AuthService:
    """
    Purpose: build the business-logic object for one request.
    Inputs:  the request-scoped session and the service settings.
    Output:  an `AuthService` over a repository bound to that session.
    """
    return AuthService(UserRepository(session), settings)


def get_user_admin_service(
    session: Annotated[Session, Depends(get_session)],
) -> UserAdminService:
    """
    Purpose: build the account-management object for one request. It needs no
             settings: creating a user signs nothing.
    Inputs:  the request-scoped session.
    Output:  a `UserAdminService` over a repository bound to that session.
    """
    return UserAdminService(UserRepository(session))


def get_bearer_token(request: Request) -> str:
    """
    Purpose: pull the raw JWT out of the Authorization header.
    Inputs:  request - the incoming request.
    Output:  the token, without its scheme.
    Raises:  `AuthenticationError` (401) when the header is absent or is not a
             bearer credential.
    """
    header = request.headers.get("Authorization", "")
    if not header.lower().startswith(_BEARER_PREFIX):
        raise AuthenticationError(
            "An `Authorization: Bearer <token>` header is required.",
            {"reason": "missing_bearer_token"},
        )
    token = header[len(_BEARER_PREFIX):].strip()
    if not token:
        raise AuthenticationError(
            "The Authorization header carries no token.",
            {"reason": "missing_bearer_token"},
        )
    return token


def get_current_claims(
    token: Annotated[str, Depends(get_bearer_token)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> TokenClaims:
    """
    Purpose: the authenticated caller's identity, for any protected route.
    Inputs:  the bearer token and the auth service that validates it.
    Output:  the decoded `TokenClaims`.
    Raises:  `AuthenticationError` (401) for an expired or invalid token.
    """
    return service.verify(token)


def require_admin(
    claims: Annotated[TokenClaims, Depends(get_current_claims)],
) -> TokenClaims:
    """
    Purpose: guard the user-management routes. Authentication says who you are;
             this says whether you may.
    Inputs:  the caller's validated claims.
    Output:  the same claims, when the caller is an admin.
    Raises:  `AuthorisationError` (403) for any other role - deliberately not a
             401, because the caller's identity was never in doubt.
    """
    if claims.role != Role.ADMIN.value:
        raise AuthorisationError(
            "This endpoint is restricted to the admin role.",
            {"required_role": Role.ADMIN.value, "role": claims.role},
        )
    return claims


def get_source_ip(request: Request) -> str | None:
    """
    Purpose: the client address recorded on every authentication event. Behind
             Kong the socket peer is the gateway, so the forwarded header wins
             when it is present.
    Inputs:  request - the incoming request.
    Output:  the client IP, or None when it cannot be determined.
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def get_request_correlation_id() -> str:
    """
    Purpose: the correlation id bound to this request by the middleware, so the
             authentication events join the rest of the workflow.
    Inputs:  none.
    Output:  the current correlation id.
    """
    return get_correlation_id()
