"""
events.py - the security event schema, fixed by docs/soc-events.md.

This module is the ONLY sanctioned way to construct a security event. Every
field name here is a contract with Phase 2's collector, detection rules and
knowledge-graph loaders: renaming one is a breaking change to the whole system
and needs a DECISIONS.md entry.

Extra fields are rejected and missing required fields raise, because a silently
malformed event stream is discovered weeks later in Phase 2 rather than now.

Author: Colile
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# The schema calls for `evt-` followed by 12 hex characters of a uuid4.
_EVENT_ID_PREFIX = "evt-"
_EVENT_ID_HEX_LENGTH = 12

_HEX_CHARACTERS = frozenset("0123456789abcdef")
_PERMITTED_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
)


class Severity(str, Enum):
    """The four severities in docs/soc-events.md, ordered least to most severe."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class EventType(str, Enum):
    """
    Every event type the system emits, grouped by the service that emits it.
    Adding a member is additive and safe; renaming one breaks Phase 2.
    """

    # Authentication - auth-service
    AUTH_SUCCESS = "AUTH_SUCCESS"
    AUTH_FAILED = "AUTH_FAILED"

    # Gateway enforcement - api-gateway
    UNAUTHORISED_ACCESS = "UNAUTHORISED_ACCESS"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

    # Request baseline - all services
    REQUEST_RECEIVED = "REQUEST_RECEIVED"
    REQUEST_COMPLETED = "REQUEST_COMPLETED"

    # Incident domain - incident-service
    INCIDENT_CREATED = "INCIDENT_CREATED"
    INCIDENT_ESCALATED = "INCIDENT_ESCALATED"

    # Asset domain - asset-service
    ASSET_ACCESSED = "ASSET_ACCESSED"

    # Resilience - incident-service
    DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
    CIRCUIT_OPENED = "CIRCUIT_OPENED"
    CIRCUIT_CLOSED = "CIRCUIT_CLOSED"

    # Faults - all services
    SERVICE_ERROR = "SERVICE_ERROR"


class ServiceName(str, Enum):
    """The four emitters named in the schema. Nothing else may emit."""

    AUTH = "auth-service"
    INCIDENT = "incident-service"
    ASSET = "asset-service"
    GATEWAY = "api-gateway"


def new_event_id() -> str:
    """
    Purpose: mint an event identifier in the schema's exact format.
    Inputs:  none.
    Output:  a string `evt-` followed by 12 hexadecimal characters.
    """
    return f"{_EVENT_ID_PREFIX}{uuid.uuid4().hex[:_EVENT_ID_HEX_LENGTH]}"


def utc_now_iso() -> str:
    """
    Purpose: produce the event timestamp. Generated here and never by a caller,
             so every service reads its clock the same way and the format never
             varies across the stream Phase 2 parses.
    Inputs:  none.
    Output:  an ISO-8601 UTC string ending in `Z`, e.g. `2026-09-07T10:45:00Z`.
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class SecurityEvent(BaseModel):
    """
    Purpose: one security-relevant occurrence, in the exact shape Phase 2 reads.
    Inputs:  the fields below. Construct through `build_event`, not directly.
    Output:  a validated, immutable event. `to_json_dict()` renders the line
             written to the log stream.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(serialization_alias="eventId")
    timestamp: str = Field(serialization_alias="timestamp")
    service_name: str = Field(serialization_alias="serviceName")
    event_type: EventType = Field(serialization_alias="eventType")
    severity: Severity = Field(serialization_alias="severity")
    user_id: str | None = Field(default=None, serialization_alias="userId")
    source_ip: str | None = Field(default=None, serialization_alias="sourceIp")
    endpoint: str = Field(serialization_alias="endpoint")
    http_method: str = Field(serialization_alias="httpMethod")
    status_code: int = Field(serialization_alias="statusCode")
    message: str = Field(serialization_alias="message")
    correlation_id: str = Field(serialization_alias="correlationId")
    affected_entity: str | None = Field(
        default=None, serialization_alias="affectedEntity"
    )

    @field_validator("event_id")
    @classmethod
    def _validate_event_id(cls, value: str) -> str:
        """
        Purpose: keep every identifier parseable by Phase 2.
        Inputs:  the candidate event id.
        Output:  the id, unchanged.
        """
        if not value.startswith(_EVENT_ID_PREFIX):
            raise ValueError(
                f"must start with {_EVENT_ID_PREFIX!r}, received {value!r}"
            )
        suffix = value[len(_EVENT_ID_PREFIX):]
        if len(suffix) != _EVENT_ID_HEX_LENGTH:
            raise ValueError(
                f"must carry {_EVENT_ID_HEX_LENGTH} hex characters after the "
                f"prefix, received {value!r}"
            )
        if not set(suffix) <= _HEX_CHARACTERS:
            raise ValueError(f"must be lower-case hexadecimal, received {value!r}")
        return value

    @field_validator("service_name")
    @classmethod
    def _validate_service_name(cls, value: str) -> str:
        """
        Purpose: reject an emitter Phase 2's graph has no node for.
        Inputs:  the service name.
        Output:  the name, unchanged.
        """
        permitted = {member.value for member in ServiceName}
        if value not in permitted:
            raise ValueError(f"must be one of {sorted(permitted)}, received {value!r}")
        return value

    @field_validator("http_method")
    @classmethod
    def _validate_http_method(cls, value: str) -> str:
        """
        Purpose: normalise the method so detection rules match it exactly.
        Inputs:  the HTTP method.
        Output:  the method, upper-cased.
        """
        method = value.upper()
        if method not in _PERMITTED_METHODS:
            raise ValueError(
                f"must be one of {sorted(_PERMITTED_METHODS)}, received {value!r}"
            )
        return method

    @field_validator("status_code")
    @classmethod
    def _validate_status_code(cls, value: int) -> int:
        """
        Purpose: reject a status no HTTP client would ever produce.
        Inputs:  the status code.
        Output:  the code, unchanged.
        """
        if not 100 <= value <= 599:
            raise ValueError(f"must be a valid HTTP status, received {value}")
        return value

    @field_validator("endpoint", "message", "correlation_id")
    @classmethod
    def _reject_blank(cls, value: str) -> str:
        """
        Purpose: a required field that is present but empty is a missing field
                 with extra steps, so it fails the same way.
        Inputs:  the field value.
        Output:  the value, unchanged.
        """
        if not value.strip():
            raise ValueError("is required and must not be blank")
        return value

    def to_json_dict(self) -> dict[str, Any]:
        """
        Purpose: render the event with the camelCase keys of the published
                 schema, which is what Phase 2 parses.
        Inputs:  none beyond the instance.
        Output:  a dict keyed exactly as docs/soc-events.md specifies.
        """
        return self.model_dump(by_alias=True, mode="json")


def build_event(
    *,
    service_name: str,
    event_type: EventType,
    severity: Severity,
    endpoint: str,
    http_method: str,
    status_code: int,
    message: str,
    correlation_id: str,
    user_id: str | None = None,
    source_ip: str | None = None,
    affected_entity: str | None = None,
) -> SecurityEvent:
    """
    Purpose: the only sanctioned way to construct a security event. Generates
             the event id and timestamp itself so no caller can supply a wrong
             format, and validates every remaining field against the schema.
    Inputs:  keyword-only, mirroring docs/soc-events.md. The optional fields are
             exactly those the schema marks "where known".
    Output:  a validated `SecurityEvent`.
    Raises:  `pydantic.ValidationError` when a field violates the schema. It is
             deliberately not caught here: a malformed event must fail loudly at
             its source rather than be emitted partially.
    """
    return SecurityEvent(
        event_id=new_event_id(),
        timestamp=utc_now_iso(),
        service_name=service_name,
        event_type=event_type,
        severity=severity,
        user_id=user_id,
        source_ip=source_ip,
        endpoint=endpoint,
        http_method=http_method,
        status_code=status_code,
        message=message,
        correlation_id=correlation_id,
        affected_entity=affected_entity,
    )
