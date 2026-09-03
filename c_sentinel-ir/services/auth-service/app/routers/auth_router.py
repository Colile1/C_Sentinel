"""
auth_router.py - the four HTTP endpoints auth-service publishes.

HTTP only: parse the request, delegate to `AuthService`, shape the response.
No business logic and no error handling live here - a typed error raised below
becomes its status code in `install_error_handlers`, which is the one place
that mapping is written.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.routers.dependencies import (
    get_auth_service,
    get_bearer_token,
    get_request_correlation_id,
    get_source_ip,
    get_user_admin_service,
    require_admin,
)
from app.schemas import (
    LoginRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    VerifyResponse,
)
from app.services.auth_service import AuthService
from app.services.token_service import TokenClaims
from app.services.user_admin_service import UserAdminService

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for a JWT",
)
def login(
    payload: LoginRequest,
    service: Annotated[AuthService, Depends(get_auth_service)],
    source_ip: Annotated[str | None, Depends(get_source_ip)],
    correlation_id: Annotated[str, Depends(get_request_correlation_id)],
) -> TokenResponse:
    """
    Purpose: authenticate a user and return an access token.
    Inputs:  the login body; the client IP and correlation id for the event.
    Output:  200 with the bearer token, its lifetime and the caller's role.
             401 with the shared error shape when the credentials are wrong -
             and one `AUTH_FAILED` event on the stream either way.
    """
    token, role, expires_in = service.authenticate(
        username=payload.username,
        password=payload.password,
        source_ip=source_ip,
        correlation_id=correlation_id,
    )
    return TokenResponse(access_token=token, expires_in=expires_in, role=role)


@router.get(
    "/verify",
    response_model=VerifyResponse,
    summary="Validate the current token and return its claims",
)
def verify(
    token: Annotated[str, Depends(get_bearer_token)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> VerifyResponse:
    """
    Purpose: tell a client whether the token it holds is still good.
    Inputs:  the bearer token from the Authorization header.
    Output:  200 with the claims; 401 when the token is expired, tampered with
             or not issued by this service.
    """
    claims = service.verify(token)
    return VerifyResponse(
        username=claims.sub,
        role=claims.role,
        issued_at=claims.iat,
        expires_at=claims.exp,
    )


@router.post(
    "/users",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a user (admin only)",
)
def create_user(
    payload: UserCreate,
    service: Annotated[UserAdminService, Depends(get_user_admin_service)],
    _admin: Annotated[TokenClaims, Depends(require_admin)],
) -> UserRead:
    """
    Purpose: register a new account.
    Inputs:  the new user's details; the caller must hold an admin token.
    Output:  201 with the created user, hash excluded. 403 for a non-admin,
             409 when the username or email is taken, 422 on a weak password.
    """
    user = service.create_user(
        username=payload.username,
        email=payload.email,
        password=payload.password,
        role=payload.role,
    )
    return UserRead.model_validate(user)


@router.get(
    "/users",
    response_model=list[UserRead],
    summary="List users (admin only)",
)
def list_users(
    service: Annotated[UserAdminService, Depends(get_user_admin_service)],
    _admin: Annotated[TokenClaims, Depends(require_admin)],
) -> list[UserRead]:
    """
    Purpose: the admin view of every account.
    Inputs:  the caller must hold an admin token.
    Output:  200 with the users, oldest first. 403 for a non-admin.
    """
    return [UserRead.model_validate(user) for user in service.list_users()]
