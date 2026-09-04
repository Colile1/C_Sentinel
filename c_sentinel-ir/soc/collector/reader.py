"""
reader.py - parse the mixed Phase 1 log stream into SecurityEvents.

A Sentinel-IR container writes two kinds of JSON line to stdout: ordinary
application log lines (they carry `level` and `logger`, never `eventType`), and
security events in the exact schema of `docs/soc-events.md`. This module reads
the combined stream, yields one `SecurityEvent` per event line, and silently
skips everything else.

A line that *claims* to be an event - it has an `eventType` key - but fails
schema validation is not skipped: it raises `MalformedEventError`. A silently
dropped malformed event is a detection rule that never fires for a reason no
one can see.

Author: Colile
"""

from __future__ import annotations

import json
import sys
from typing import Iterable, Iterator

from common.events import SecurityEvent

# The log stream is written with the schema's camelCase keys (serialization
# aliases). `model_validate` wants the snake_case field names, so map back.
_ALIAS_TO_FIELD = {
    (field.serialization_alias or name): name
    for name, field in SecurityEvent.model_fields.items()
}

# The one key that distinguishes an event line from an application log line.
_EVENT_MARKER_KEY = "eventType"


class MalformedEventError(ValueError):
    """
    Purpose: signal a line that identifies itself as a security event but does
             not conform to the schema. Raised rather than swallowed so the
             fault surfaces at ingestion, not weeks later in a rule.
    Inputs:  the raw line and the underlying validation failure.
    Output:  an exception carrying both for the caller's log.
    """

    def __init__(self, raw_line: str, cause: Exception) -> None:
        super().__init__(f"line claims to be an event but fails the schema: {cause}")
        self.raw_line = raw_line
        self.__cause__ = cause


def _looks_like_event(obj: object) -> bool:
    """
    Purpose: decide whether a parsed line is a security event or an ordinary
             application log line.
    Inputs:  obj - the result of `json.loads` on one line.
    Output:  True when it is a dict carrying the event marker key.
    """
    return isinstance(obj, dict) and _EVENT_MARKER_KEY in obj


def parse_event_line(raw_line: str) -> SecurityEvent | None:
    """
    Purpose: turn one raw log line into a `SecurityEvent`, or nothing.
    Inputs:  raw_line - a single line from the log stream, with or without a
             trailing newline.
    Output:  a validated `SecurityEvent` if the line is an event; None if the
             line is blank, is not JSON, or is an application log line.
    Raises:  `MalformedEventError` if the line carries `eventType` but does not
             validate against the schema.
    """
    stripped = raw_line.strip()
    if not stripped:
        return None
    try:
        obj = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not _looks_like_event(obj):
        return None

    unknown = set(obj) - set(_ALIAS_TO_FIELD)
    if unknown:
        raise MalformedEventError(
            stripped, ValueError(f"non-schema keys {sorted(unknown)}")
        )
    by_field = {_ALIAS_TO_FIELD[key]: value for key, value in obj.items()}
    try:
        return SecurityEvent.model_validate(by_field)
    except Exception as exc:  # pydantic.ValidationError and nothing wider
        raise MalformedEventError(stripped, exc) from exc


def stream_events(lines: Iterable[str]) -> Iterator[SecurityEvent]:
    """
    Purpose: the reader's public entry point - filter a stream of raw log lines
             down to the security events in it.
    Inputs:  lines - any iterable of strings: an open file, `sys.stdin`, the
             output of `docker compose logs`, or a list in a test.
    Output:  an iterator of `SecurityEvent`, in the order the lines arrived.
    Raises:  `MalformedEventError` on the first line that claims to be an event
             and fails validation.
    """
    for raw_line in lines:
        event = parse_event_line(raw_line)
        if event is not None:
            yield event


def stream_stdin() -> Iterator[SecurityEvent]:
    """
    Purpose: convenience wrapper for the common case of piping a log stream in.
    Inputs:  none; reads `sys.stdin`.
    Output:  an iterator of `SecurityEvent`.
    """
    return stream_events(sys.stdin)
