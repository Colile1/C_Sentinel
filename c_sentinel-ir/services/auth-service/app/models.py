"""
models.py - the SQLAlchemy tables auth-service owns.

One table: the users whose credentials the rest of the system authenticates
against. It lives in `auth_db` and no other service may read it - cross-service
identity travels as a JWT claim, never as a query.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The declarative base for every table in auth_db."""


def _utc_now() -> datetime:
    """Purpose: a timezone-aware creation stamp. Inputs: none. Output: UTC now."""
    return datetime.now(timezone.utc)


class User(Base):
    """
    Purpose: one account that can log in. `role` is copied into the JWT and is
             what the admin-only endpoints and, later, the gateway check.
    Inputs:  the columns below.
    Output:  a persisted row. The plaintext password is never a column - only
             the bcrypt hash produced by `password_service` is stored.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="analyst")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    def __repr__(self) -> str:
        """Purpose: a safe debug rendering. Inputs: none. Output: a string that
        never contains the password hash."""
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"
