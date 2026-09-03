"""
logging.py - JSON structured logging to stdout, and the security event stream.

Two things leave a Sentinel-IR service on stdout: ordinary application log
lines, and security events. Both are single-line JSON so Docker collects them
and Phase 2's SOC collector parses them without a translation layer. Every line
carries the correlation id of the request that produced it.

No service may log in an ad-hoc format, and no service may build a security
event line by hand: `emit_event` is the only writer.

Author: Colile
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

from common.correlation import get_correlation_id
from common.events import SecurityEvent

# Marks the lines Phase 2's collector must pick out of the combined stream.
EVENT_STREAM_LOGGER = "sentinel.events"

# Attributes the stdlib puts on every record, which we render explicitly or
# deliberately drop. Anything outside this set is a caller's `extra` and is
# merged into the line.
_STANDARD_RECORD_ATTRIBUTES = frozenset(
    {
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "levelname", "levelno", "lineno", "module", "msecs",
        "message", "msg", "name", "pathname", "process", "processName",
        "relativeCreated", "stack_info", "thread", "threadName", "taskName",
    }
)


class JsonFormatter(logging.Formatter):
    """
    Purpose: render a log record as one line of JSON carrying the service name
             and the current correlation id, so a workflow can be followed
             across three services by grepping one value.
    Inputs:  service_name - the emitting service, stamped onto every line.
    Output:  a formatter installable on any handler.
    """

    def __init__(self, service_name: str) -> None:
        super().__init__()
        self._service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        """
        Purpose: turn one record into the JSON line written to stdout.
        Inputs:  record - the record the logging module produced.
        Output:  a JSON string with no embedded newline.
        """
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "serviceName": self._service_name,
            "logger": record.name,
            "message": record.getMessage(),
            "correlationId": get_correlation_id(),
        }

        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRIBUTES and not key.startswith("_"):
                payload[key] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str)


class EventFormatter(logging.Formatter):
    """
    Purpose: write a security event as the bare schema JSON, with none of the
             log-record wrapping, so the SOC collector reads exactly the shape
             docs/soc-events.md publishes.
    Inputs:  none.
    Output:  a formatter for the event-stream logger only.
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        Purpose: render the event carried on the record.
        Inputs:  record - carries the rendered event dict on `securityEvent`.
        Output:  a single JSON line in the published schema.
        """
        event = getattr(record, "securityEvent", None)
        if event is None:
            return json.dumps({"message": record.getMessage()}, default=str)
        return json.dumps(event, default=str)


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """
    Purpose: install JSON logging on stdout for this process. Called once, from
             `app/main.py`, before anything else logs.
    Inputs:  service_name - stamped onto every application log line.
             log_level - the threshold, already validated by `config.Settings`.
    Output:  None. The root logger and the event logger are reconfigured.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)

    application_handler = logging.StreamHandler(sys.stdout)
    application_handler.setFormatter(JsonFormatter(service_name))
    root.addHandler(application_handler)
    root.setLevel(log_level)

    event_logger = logging.getLogger(EVENT_STREAM_LOGGER)
    for handler in list(event_logger.handlers):
        event_logger.removeHandler(handler)

    event_handler = logging.StreamHandler(sys.stdout)
    event_handler.setFormatter(EventFormatter())
    event_logger.addHandler(event_handler)
    event_logger.setLevel(logging.INFO)

    # Security events are their own stream. Letting them propagate would emit
    # every event twice, once wrapped as an application line.
    event_logger.propagate = False

    # Uvicorn installs its own plain-text handlers; strip them so the container
    # emits one format only.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def emit_event(event: SecurityEvent) -> None:
    """
    Purpose: write one security event to the stream Phase 2 consumes. The only
             sanctioned writer — no service formats an event line itself.
    Inputs:  event - a validated `SecurityEvent` from `build_event`.
    Output:  None. One JSON line is written to stdout.
    """
    logging.getLogger(EVENT_STREAM_LOGGER).info(
        event.message, extra={"securityEvent": event.to_json_dict()}
    )
