"""
schemas.py - the request and response shapes the alert API speaks.

The alert *record* is `models.Alert`, fixed by the specification and rendered
with `to_json_dict()`. This module holds only what the HTTP layer adds on top:
the body of the status-change request. Responses are the schema dict itself, so
there is no `AlertRead` - inventing one would be a second place the eleven field
names live.

Author: Colile
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from soc.alert_service.models import AlertStatus


class StatusChange(BaseModel):
    """
    Purpose: the body of `PATCH /api/v1/alerts/{id}/status` - the one field a
             responder may change on a raised alert.
    Inputs:  status - the target `AlertStatus`.
    Output:  a validated request. An unknown status value is a 422 naming the
             field, from FastAPI's own validation.
    """

    model_config = ConfigDict(extra="forbid")

    status: AlertStatus
