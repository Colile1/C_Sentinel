"""
user_repository.py - every SQL statement auth-service runs, in one file.

SQLAlchemy lives here and nowhere else in this service: the business logic in
app/services/ takes a repository and never a Session, which is what keeps it
unit-testable against a fake with no database at all.

Author: Colile
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import ConflictError

from app.models import User


class UserRepository:
    """
    Purpose: read and write the `users` table.
    Inputs:  session - the request-scoped SQLAlchemy session.
    Output:  a repository whose methods return `User` rows or None. It raises
             only `ConflictError`; every other failure belongs to the caller.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_by_username(self, username: str) -> User | None:
        """
        Purpose: find the account a login attempt names.
        Inputs:  username - as supplied by the client.
        Output:  the `User`, or None when no such account exists.
        """
        statement = select(User).where(User.username == username)
        return self._session.scalars(statement).one_or_none()

    def list_users(self) -> list[User]:
        """
        Purpose: the admin listing.
        Inputs:  none.
        Output:  every user, oldest first, so the ordering is stable between
                 calls rather than whatever the database happens to return.
        """
        statement = select(User).order_by(User.id)
        return list(self._session.scalars(statement))

    def create(self, user: User) -> User:
        """
        Purpose: persist a new account.
        Inputs:  user - a `User` whose `password_hash` is already hashed.
        Output:  the persisted user, with its generated id populated.
        Raises:  `ConflictError` when the username or email is already taken -
                 the unique constraint is the authority, not a prior SELECT,
                 which two concurrent requests could both pass.
        """
        self._session.add(user)
        try:
            self._session.commit()
        except IntegrityError as exc:
            self._session.rollback()
            raise ConflictError(
                f"A user with username {user.username!r} or that email already exists.",
                {"field": "username", "value": user.username},
            ) from exc
        self._session.refresh(user)
        return user
