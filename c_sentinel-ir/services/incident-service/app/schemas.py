"""
schemas.py - the request and response bodies of incident-service's public API.

Pydantic v2 models, separate from the SQLAlchemy table on purpose: `IncidentRead`
exists so no route can accidentally serialise an ORM object directly.

Author: Colile
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class Severity(str, Enum):
    """The four severities an incident can carry."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class Status(str, Enum):
    """The three states of an incident's lifecycle, in order."""

    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    RESOLVED = "RESOLVED"


class IncidentCreate(BaseModel):
    """
    Purpose: the body of `POST /api/v1/incidents`.
    Inputs:  the new incident's details, as reported by an analyst.
    Output:  a validated request. `asset_id` is checked against asset-service
             by the business logic, not here.
    """

    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=2000)
    severity: Severity = Severity.LOW
    reported_by: str = Field(min_length=1, max_length=64)
    asset_id: int = Field(gt=0)


class IncidentUpdate(BaseModel):
    """
    Purpose: the body of `PUT /api/v1/incidents/{id}`.
    Inputs:  the fields that may change. All optional, so a client can send
             only what it is updating. Severity and status change through
             their own endpoint/rules, not a plain field overwrite here.
    Output:  a validated request; unset fields are left untouched.
    """

    title: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, min_length=1, max_length=2000)
    status: Status | None = None


class SeverityChange(BaseModel):
    """
    Purpose: the body of `PATCH /api/v1/incidents/{id}/severity`.
    Inputs:  the new severity.
    Output:  a validated request. An invalid value is rejected as 422 by
             FastAPI's enum parsing, naming the `severity` field.
    """

    severity: Severity


class IncidentRead(BaseModel):
    """
    Purpose: how an incident is returned to a client.
    Inputs:  an `Incident` row, read by attribute.
    Output:  the full public shape of an incident.
    """

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    severity: Severity
    status: Status
    reported_by: str
    asset_id: int
    asset_name_snapshot: str
    created_at: datetime
    updated_at: datetime
