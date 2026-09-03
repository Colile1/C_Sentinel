"""
models.py - the SQLAlchemy table asset-service owns.

One table: the asset register. It lives in `asset_db` and no other service may
read it - cross-service data travels as HTTP responses only.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The declarative base for every table in asset_db."""


def _utc_now() -> datetime:
    """Purpose: a timezone-aware creation stamp. Inputs: none. Output: UTC now."""
    return datetime.now(timezone.utc)


class Asset(Base):
    """
    Purpose: one server, application or system an incident can be raised
             against. `criticality` is what makes `ASSET_ACCESSED` selective -
             only a read of a CRITICAL asset is Phase 2's signal, not every
             read.
    Inputs:  the columns below.
    Output:  a persisted row.
    """

    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    asset_type: Mapped[str] = mapped_column(String(64), nullable=False)
    criticality: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    owner: Mapped[str] = mapped_column(String(128), nullable=False)
    location: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )

    def __repr__(self) -> str:
        """Purpose: a safe debug rendering. Inputs: none. Output: a string."""
        return f"<Asset id={self.id} name={self.name!r} criticality={self.criticality!r}>"
