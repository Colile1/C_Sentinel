"""
user_admin_service.py - creating and listing accounts.

Split out of `auth_service.py`, which was doing two jobs: proving who someone
is, and administering who exists. Authentication runs on every login and is the
security-critical path; account management is a rare admin-only operation.
Keeping them apart means a change to one cannot disturb the other, and both
files stay inside the size limit in CLAUDE.md section 4.

Pure business logic: a repository in, domain objects out. No FastAPI.

Author: Colile
"""

from __future__ import annotations

from app.models import User
from app.repositories.user_repository import UserRepository
from app.schemas import Role
from app.services.password_service import hash_password


class UserAdminService:
    """
    Purpose: manage the accounts `AuthService` later authenticates against.
    Inputs:  users - the repository this service reads and writes through.
    Output:  an object raising only typed errors from `common.errors`; the HTTP
             mapping is done once, in `install_error_handlers`.
    """

    def __init__(self, users: UserRepository) -> None:
        self._users = users

    def create_user(
        self, *, username: str, email: str, password: str, role: Role
    ) -> User:
        """
        Purpose: register a new account, hashing the password before it is
                 stored. The only way a user enters the system.
        Inputs:  the new account's username, email, plaintext password and role.
        Output:  the persisted `User`.
        Raises:  `ValidationError` when the password breaks the rules in
                 `password_service`; `ConflictError` when the username or email
                 is taken.
        """
        user = User(
            username=username,
            email=email,
            password_hash=hash_password(password),
            role=role.value,
            is_active=True,
        )
        return self._users.create(user)

    def list_users(self) -> list[User]:
        """
        Purpose: the admin listing of accounts.
        Inputs:  none.
        Output:  every user, oldest first.
        """
        return self._users.list_users()
