"""
models.py - the alert schema, fixed by the Phase 2 specification.

An `Alert` is what a detection rule produces when it fires. The field names are
a contract in exactly the way `common.events.SecurityEvent`'s are: the alert API
serves them, `kg/loader` projects them into the graph, and `rag/retrieval` cites
them as evidence. Renaming one is a breaking change needing a DECISIONS.md entry.

`related_events` holds real `eventId` values. That is the link that lets an
answer point at the events which caused an alert rather than assert a cause, so
it may not be empty - an alert nothing caused is not evidence of anything.

Author: Colile
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from common.events import Severity

# The schema's identifier format, mirroring `evt-` in the event schema.
_ALERT_ID_PREFIX = "alt-"
_ALERT_ID_HEX_LENGTH = 12

_HEX_CHARACTERS = frozenset("0123456789abcdef")


class AlertStatus(str, Enum):
    """The lifecycle of an alert once a rule has raised it."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    CLOSED = "CLOSED"


def new_alert_id() -> str:
    """
    Purpose: mint an alert identifier in the schema's exact format.
    Inputs:  none.
    Output:  a string `alt-` followed by 12 hexadecimal characters.
    """
    return f"{_ALERT_ID_PREFIX}{uuid.uuid4().hex[:_ALERT_ID_HEX_LENGTH]}"


class Alert(BaseModel):
    """
    Purpose: one detection-rule firing, in the exact shape the Phase 2
             specification names.
    Inputs:  the fields below; `alert_id` defaults to a fresh identifier.
    Output:  a validated, immutable alert. `to_json_dict()` renders it with the
             camelCase keys the API and the graph loader read.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    alert_id: str = Field(
        default_factory=new_alert_id, serialization_alias="alertId"
    )
    timestamp: str = Field(serialization_alias="timestamp")
    rule_name: str = Field(serialization_alias="ruleName")
    severity: Severity = Field(serialization_alias="severity")
    status: AlertStatus = Field(
        default=AlertStatus.OPEN, serialization_alias="status"
    )
    description: str = Field(serialization_alias="description")
    related_events: tuple[str, ...] = Field(serialization_alias="relatedEvents")
    affected_service: str | None = Field(
        default=None, serialization_alias="affectedService"
    )
    affected_user: str | None = Field(
        default=None, serialization_alias="affectedUser"
    )
    affected_entity: str | None = Field(
        default=None, serialization_alias="affectedEntity"
    )
    recommended_action: str = Field(serialization_alias="recommendedAction")

    @field_validator("alert_id")
    @classmethod
    def _validate_alert_id(cls, value: str) -> str:
        """
        Purpose: keep every identifier parseable by the graph loader.
        Inputs:  the candidate alert id.
        Output:  the id, unchanged.
        """
        if not value.startswith(_ALERT_ID_PREFIX):
            raise ValueError(
                f"must start with {_ALERT_ID_PREFIX!r}, received {value!r}"
            )
        suffix = value[len(_ALERT_ID_PREFIX):]
        if len(suffix) != _ALERT_ID_HEX_LENGTH:
            raise ValueError(
                f"must carry {_ALERT_ID_HEX_LENGTH} hex characters after the "
                f"prefix, received {value!r}"
            )
        if not set(suffix) <= _HEX_CHARACTERS:
            raise ValueError(f"must be lower-case hexadecimal, received {value!r}")
        return value

    @field_validator("related_events")
    @classmethod
    def _reject_empty_evidence(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        """
        Purpose: an alert with no related events cites nothing and cannot be
                 traced back to what caused it.
        Inputs:  the tuple of event ids.
        Output:  the tuple, unchanged.
        """
        if not value:
            raise ValueError("must name at least one event that caused the alert")
        return value

    @field_validator("rule_name", "description", "recommended_action", "timestamp")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """
        Purpose: a present-but-empty required field is a missing field with
                 extra steps, so it fails the same way.
        Inputs:  the field value.
        Output:  the value, unchanged.
        """
        if not value.strip():
            raise ValueError("is required and must not be blank")
        return value

    def to_json_dict(self) -> dict[str, Any]:
        """
        Purpose: render the alert with the camelCase keys of the published
                 schema, which is what the API and the graph loader read.
        Inputs:  none beyond the instance.
        Output:  a dict keyed exactly as the specification names.
        """
        return self.model_dump(by_alias=True, mode="json")
