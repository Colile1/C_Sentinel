"""
auth_service.py - the business logic of authentication.

A failed login here is not an error to swallow, it is a product: it is the
input to Phase 2's first detection rule (multiple failed logins), so
`AUTH_FAILED` carries the attempted username, the source IP and the correlation
id, and is emitted on every failing path - unknown user, wrong password and
disabled account alike.

The caller is told the same thing in all three cases. Distinguishing "no such
user" from "wrong password" in the response hands an attacker a free username
oracle, and the event stream records the real reason for the SOC either way.

Pure business logic: it takes a repository and settings, and imports no
FastAPI. That is what makes it testable against a fake repository with no
database, no container and no network.

Author: Colile
"""

from __future__ import annotations

from common.errors import AuthenticationError
from common.events import EventType, Severity, build_event
from common.logging import emit_event

from app.repositories.user_repository import UserRepository
from app.schemas import Role
from app.services.password_service import verify_password
from app.services.token_service import decode_token, issue_token

SERVICE_NAME = "auth-service"
LOGIN_ENDPOINT = "/api/v1/auth/login"

# The schema's `affectedEntity` for an authentication event: the thing acted
# upon is the login endpoint itself, not any incident or asset.
_LOGIN_ENTITY = "login-endpoint"

# The one message every failed login returns, whatever actually went wrong.
_FAILURE_MESSAGE = "The username or password is incorrect."


class AuthService:
    """
    Purpose: authenticate users and issue their tokens, emitting the
             authentication events Phase 2 consumes. Account administration is
             a separate concern; it lives in `user_admin_service.py`.
    Inputs:  users - the repository this service reads and writes through.
             settings - supplies the JWT secret, algorithm and expiry. Never
                        hardcoded, so the gateway's validation cannot drift
                        from the issuer's signing.
    Output:  an object whose methods raise typed errors from `common.errors`;
             the HTTP mapping is done once, in `install_error_handlers`.
    """

    def __init__(self, users: UserRepository, settings) -> None:
        self._users = users
        self._settings = settings

    def authenticate(
        self,
        *,
        username: str,
        password: str,
        source_ip: str | None,
        correlation_id: str,
    ) -> tuple[str, Role, int]:
        """
        Purpose: verify credentials and issue an access token, emitting exactly
                 one authentication event whichever way it goes.
        Inputs:  username and password as supplied by the client; source_ip and
                 correlation_id from the request, for the event stream.
        Output:  (token, role, expires_in_seconds).
        Raises:  `AuthenticationError` (401) for an unknown user, a wrong
                 password or a disabled account - all with the same message.
        """
        user = self._users.get_by_username(username)

        if user is None:
            self._emit_failure(username, source_ip, correlation_id, "unknown_user")
            raise AuthenticationError(_FAILURE_MESSAGE, {"reason": "invalid_credentials"})

        if not user.is_active:
            self._emit_failure(username, source_ip, correlation_id, "account_disabled")
            raise AuthenticationError(_FAILURE_MESSAGE, {"reason": "invalid_credentials"})

        if not verify_password(password, user.password_hash):
            self._emit_failure(username, source_ip, correlation_id, "bad_password")
            raise AuthenticationError(_FAILURE_MESSAGE, {"reason": "invalid_credentials"})

        token = issue_token(
            username=user.username,
            role=user.role,
            secret=self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
            expiry_minutes=self._settings.jwt_expiry_minutes,
        )

        emit_event(
            build_event(
                service_name=SERVICE_NAME,
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                user_id=user.username,
                source_ip=source_ip,
                endpoint=LOGIN_ENDPOINT,
                http_method="POST",
                status_code=200,
                message=f"User {user.username} authenticated successfully.",
                correlation_id=correlation_id,
                affected_entity=_LOGIN_ENTITY,
            )
        )

        return token, Role(user.role), self._settings.jwt_expiry_minutes * 60

    def verify(self, token: str):
        """
        Purpose: validate a presented token and return its claims, for
                 `GET /api/v1/auth/verify`.
        Inputs:  token - the raw JWT from the Authorization header.
        Output:  the `TokenClaims`.
        Raises:  `AuthenticationError` when the token is expired, tampered with
                 or otherwise not ours.
        """
        return decode_token(
            token,
            secret=self._settings.jwt_secret,
            algorithm=self._settings.jwt_algorithm,
        )

    def _emit_failure(
        self,
        username: str,
        source_ip: str | None,
        correlation_id: str,
        reason: str,
    ) -> None:
        """
        Purpose: emit the `AUTH_FAILED` event Phase 2's Rule 1 counts. Exactly
                 one per failed attempt, carrying the attempted username as
                 `userId` even when no such account exists - a brute-force run
                 against invented names is precisely what the rule must see.
        Inputs:  the attempted username, the client IP, the correlation id, and
                 the internal reason, which is recorded here but never returned
                 to the client.
        Output:  None. One JSON line on the event stream.
        """
        emit_event(
            build_event(
                service_name=SERVICE_NAME,
                event_type=EventType.AUTH_FAILED,
                severity=Severity.MEDIUM,
                user_id=username,
                source_ip=source_ip,
                endpoint=LOGIN_ENDPOINT,
                http_method="POST",
                status_code=401,
                message=f"Failed login attempt for {username!r} ({reason}).",
                correlation_id=correlation_id,
                affected_entity=_LOGIN_ENTITY,
            )
        )
