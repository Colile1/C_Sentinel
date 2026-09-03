"""
schemas.py - the request and response bodies of asset-service's public API.

Pydantic v2 models, separate from the SQLAlchemy table on purpose: `AssetRead`
exists so no route can accidentally serialise an ORM object directly.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Criticality(str, Enum):
    """The four criticality levels the register recognises."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AssetCreate(BaseModel):
    """
    Purpose: the body of `POST /api/v1/assets`.
    Inputs:  the new asset's details.
    Output:  a validated request. Uniqueness of `name` is enforced by the
             service layer against the repository, not here.
    """

    name: str = Field(min_length=1, max_length=128)
    asset_type: str = Field(min_length=1, max_length=64)
    criticality: Criticality = Criticality.LOW
    owner: str = Field(min_length=1, max_length=128)
    location: str = Field(min_length=1, max_length=128)


class AssetUpdate(BaseModel):
    """
    Purpose: the body of `PUT /api/v1/assets/{id}`.
    Inputs:  the fields that may change. All optional, so a client can send
             only what it is updating.
    Output:  a validated request; unset fields are left untouched.
    """

    name: str | None = Field(default=None, min_length=1, max_length=128)
    asset_type: str | None = Field(default=None, min_length=1, max_length=64)
    criticality: Criticality | None = None
    owner: str | None = Field(default=None, min_length=1, max_length=128)
    location: str | None = Field(default=None, min_length=1, max_length=128)


class AssetRead(BaseModel):
    """
    Purpose: how an asset is returned to a client.
    Inputs:  an `Asset` row, read by attribute.
    Output:  the full public shape of an asset.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    asset_type: str
    criticality: Criticality
    owner: str
    location: str
    created_at: datetime
