"""
test_logging.py - unit tests for JSON structured logging and the event stream.

Proves the second half of build step 3's verification: a log record parses as
JSON and carries `correlationId`, and an emitted security event reaches stdout
as one line in the published schema with no log-record wrapping around it.

Author: Colile
"""

from __future__ import annotations

import json
import logging

import pytest

from common.correlation import (
    get_correlation_id,
    new_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from common.events import EventType, Severity, build_event
from common.logging import EVENT_STREAM_LOGGER, configure_logging, emit_event


@pytest.fixture(autouse=True)
def _reset_logging() -> None:
    """Purpose: leave the logging module as found, so tests do not leak
    handlers into one another. Inputs: none. Output: None."""
    yield
    logging.getLogger().handlers.clear()
    logging.getLogger(EVENT_STREAM_LOGGER).handlers.clear()


def _captured_lines(capsys: pytest.CaptureFixture[str]) -> list[dict]:
    """Purpose: read stdout back as parsed JSON lines.
    Inputs: capsys. Output: one dict per emitted line."""
    output = capsys.readouterr().out.strip()
    return [json.loads(line) for line in output.splitlines() if line]


class TestApplicationLogging:
    """Ordinary log lines must be machine-readable and correlated."""

    def test_a_log_record_parses_as_json(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Docker collects stdout, so an unparseable line is a lost line."""
        configure_logging("asset-service")
        logging.getLogger("test").info("Asset register loaded")

        lines = _captured_lines(capsys)

        assert len(lines) == 1
        assert lines[0]["message"] == "Asset register loaded"

    def test_a_log_line_carries_the_correlation_id(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The central invariant: one id ties a workflow across three services."""
        configure_logging("asset-service")
        token = set_correlation_id("corr-abcdef123456")
        try:
            logging.getLogger("test").info("Handling a request")
        finally:
            reset_correlation_id(token)

        assert _captured_lines(capsys)[0]["correlationId"] == "corr-abcdef123456"

    def test_a_log_line_carries_the_service_name(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Three services share one stream, so each line must say who wrote it."""
        configure_logging("incident-service")
        logging.getLogger("test").info("Incident raised")

        assert _captured_lines(capsys)[0]["serviceName"] == "incident-service"

    def test_a_log_line_carries_its_level(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Filtering the demo log by level has to work."""
        configure_logging("auth-service")
        logging.getLogger("test").warning("Password check failed")

        assert _captured_lines(capsys)[0]["level"] == "WARNING"

    def test_extra_fields_are_merged_into_the_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Structured context must survive, not be dropped into the message."""
        configure_logging("asset-service")
        logging.getLogger("test").info("Asset read", extra={"assetId": 7})

        assert _captured_lines(capsys)[0]["assetId"] == 7

    def test_an_exception_is_rendered_into_the_line(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A traceback split across lines is unparseable, so it is embedded."""
        configure_logging("asset-service")
        try:
            raise ValueError("the database refused the connection")
        except ValueError:
            logging.getLogger("test").exception("Database unreachable")

        line = _captured_lines(capsys)[0]

        assert "the database refused the connection" in line["exception"]
        assert "\n" not in json.dumps(line)[1:-1].replace("\\n", "")

    def test_outside_a_request_the_correlation_id_is_a_placeholder(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Startup logging has no request, but the key must still be present."""
        configure_logging("asset-service")
        logging.getLogger("test").info("Service starting")

        assert _captured_lines(capsys)[0]["correlationId"] == "-"

    def test_the_log_level_threshold_is_applied(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A configured level of WARNING must silence INFO."""
        configure_logging("asset-service", log_level="WARNING")
        logging.getLogger("test").info("Chatty detail")
        logging.getLogger("test").warning("Worth knowing")

        lines = _captured_lines(capsys)

        assert len(lines) == 1
        assert lines[0]["message"] == "Worth knowing"

    def test_configuring_twice_does_not_duplicate_lines(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Re-entrant startup must not double every log line."""
        configure_logging("asset-service")
        configure_logging("asset-service")
        logging.getLogger("test").info("Only once")

        assert len(_captured_lines(capsys)) == 1


class TestEventStream:
    """Security events are the Phase 2 input and get their own bare format."""

    def test_an_emitted_event_is_one_json_line_in_the_schema(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The collector reads exactly docs/soc-events.md, with no wrapper."""
        configure_logging("auth-service")
        emit_event(
            build_event(
                service_name="auth-service",
                event_type=EventType.AUTH_FAILED,
                severity=Severity.MEDIUM,
                user_id="analyst",
                source_ip="10.0.0.9",
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=401,
                message="Login failed, the password did not match",
                correlation_id="corr-111111111111",
                affected_entity="login-endpoint",
            )
        )

        lines = _captured_lines(capsys)

        assert len(lines) == 1
        assert sorted(lines[0]) == sorted(
            [
                "eventId", "timestamp", "serviceName", "eventType", "severity",
                "userId", "sourceIp", "endpoint", "httpMethod", "statusCode",
                "message", "correlationId", "affectedEntity",
            ]
        )

    def test_an_event_line_carries_no_log_record_wrapping(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`level` and `logger` belong to application lines, not to events."""
        configure_logging("auth-service")
        emit_event(
            build_event(
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=200,
                message="Analyst signed in",
                correlation_id="corr-222222222222",
            )
        )

        line = _captured_lines(capsys)[0]

        assert "level" not in line
        assert "logger" not in line

    def test_an_event_is_emitted_exactly_once(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Propagation to the root logger would double-count every event and
        corrupt Phase 2's rate-based detection rules."""
        configure_logging("auth-service")
        emit_event(
            build_event(
                service_name="auth-service",
                event_type=EventType.AUTH_SUCCESS,
                severity=Severity.LOW,
                endpoint="/api/v1/auth/login",
                http_method="POST",
                status_code=200,
                message="Analyst signed in",
                correlation_id="corr-333333333333",
            )
        )

        assert len(_captured_lines(capsys)) == 1

    def test_the_event_correlation_id_is_the_events_own(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An event carries the id it was built with, not the ambient context."""
        configure_logging("auth-service")
        token = set_correlation_id("corr-ambient00000")
        try:
            emit_event(
                build_event(
                    service_name="auth-service",
                    event_type=EventType.AUTH_SUCCESS,
                    severity=Severity.LOW,
                    endpoint="/api/v1/auth/login",
                    http_method="POST",
                    status_code=200,
                    message="Analyst signed in",
                    correlation_id="corr-explicit0000",
                )
            )
        finally:
            reset_correlation_id(token)

        assert _captured_lines(capsys)[0]["correlationId"] == "corr-explicit0000"


class TestCorrelationContext:
    """The correlation id is per-request and must not leak between them."""

    def test_an_id_is_generated_in_the_documented_format(self) -> None:
        """The gateway may not supply one, so services mint their own."""
        assert new_correlation_id().startswith("corr-")
        assert len(new_correlation_id()) == len("corr-") + 12

    def test_generated_ids_are_unique(self) -> None:
        """Two concurrent workflows must not share a trace."""
        assert len({new_correlation_id() for _ in range(1000)}) == 1000

    def test_resetting_restores_the_previous_value(self) -> None:
        """Without this, one request's id leaks into the next."""
        outer = set_correlation_id("corr-outer0000000")
        inner = set_correlation_id("corr-inner0000000")

        assert get_correlation_id() == "corr-inner0000000"

        reset_correlation_id(inner)
        assert get_correlation_id() == "corr-outer0000000"

        reset_correlation_id(outer)
        assert get_correlation_id() == "-"
