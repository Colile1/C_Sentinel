"""
models.py - the SQLAlchemy table incident-service owns.

One table: security incidents. It lives in `incident_db` and no other service
may read it - cross-service data travels as HTTP responses only.

`asset_name_snapshot` exists so a listing never has to call asset-service:
the name is copied in at creation time and is allowed to go stale, exactly
like an order line item recording a product's name at purchase time.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """The declarative base for every table in incident_db."""


def _utc_now() -> datetime:
    """Purpose: a timezone-aware stamp. Inputs: none. Output: UTC now."""
    return datetime.now(timezone.utc)


class Incident(Base):
    """
    Purpose: one reported security incident and its lifecycle state.
    Inputs:  the columns below.
    Output:  a persisted row.
    """

    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(String(2000), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="LOW")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")
    reported_by: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_id: Mapped[int] = mapped_column(Integer, nullable=False)
    asset_name_snapshot: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utc_now, onupdate=_utc_now
    )

    def __repr__(self) -> str:
        """Purpose: a safe debug rendering. Inputs: none. Output: a string."""
        return (
            f"<Incident id={self.id} severity={self.severity!r} "
            f"status={self.status!r}>"
        )
