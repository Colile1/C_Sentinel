"""
circuit_events.py - the security events the circuit breaker emits.

Split from `http_client.py` so that file holds the calling policy and this one
holds the Phase 2 contract. Every breaker state change and every exhausted call
becomes a `SecurityEvent`, because `docs/soc-events.md` promises Rule 4 a
`DEPENDENCY_FAILURE` per failed request and a `CIRCUIT_OPENED` / `CIRCUIT_CLOSED`
pair per state change. A breaker that opens silently still loses the pattern
mark, so the events are not optional decoration - they are the evidence.

Author: Colile
"""

from __future__ import annotations

import pybreaker

from common.correlation import get_correlation_id
from common.events import EventType, Severity, build_event
from common.logging import emit_event

# A dependency call is not an HTTP request of ours, so there is no status code
# from a client. 503 is recorded: it is what the caller would have received had
# it declared no fallback, which is what `DependencyUnavailableError` returns.
_DEPENDENCY_STATUS_CODE = 503


def emit_dependency_failure(
    *, service_name: str, endpoint: str, dependency: str, reason: str,
    correlation_id: str,
) -> None:
    """
    Purpose: record that a call to a dependency failed after every retry was
             spent. One event per exhausted request, never one per attempt -
             `docs/soc-events.md` defines it as "failed after retries", and
             Rule 4 counts requests, not attempts.
    Inputs:  service_name - the calling service. endpoint - the path called.
             dependency - the service that failed. reason - the exception text.
             correlation_id - joins this to the request that provoked it.
    Output:  None. One event is written to the stream.
    """
    emit_event(
        build_event(
            service_name=service_name,
            event_type=EventType.DEPENDENCY_FAILURE,
            severity=Severity.HIGH,
            endpoint=endpoint,
            http_method="GET",
            status_code=_DEPENDENCY_STATUS_CODE,
            message=f"Call to {dependency} failed after retries: {reason}",
            correlation_id=correlation_id,
            affected_entity=dependency,
        )
    )


class BreakerEventListener(pybreaker.CircuitBreakerListener):
    """
    Purpose: turn pybreaker's state changes into the two security events Phase 2
             reads. Attached to the breaker rather than checked at the call site,
             so a transition can never be missed by a code path that forgot to
             look for it - including the half-open trial call that closes it.
    Inputs:  service_name - the calling service, named as the event's emitter.
             dependency - the service the breaker guards, recorded as the
             affected entity. endpoint - the path this breaker fronts.
    Output:  a listener instance. pybreaker calls it; nothing else does.
    """

    def __init__(self, *, service_name: str, dependency: str, endpoint: str) -> None:
        self._service_name = service_name
        self._dependency = dependency
        self._endpoint = endpoint

    def state_change(self, breaker, old_state, new_state) -> None:
        """
        Purpose: emit `CIRCUIT_OPENED` when the breaker trips and
                 `CIRCUIT_CLOSED` when a trial call proves the dependency is
                 healthy again. The half-open state is a transient probe and is
                 deliberately not an event of its own - Phase 2's graph has no
                 node for it.
        Inputs:  breaker - the breaker changing state. old_state - the state
                 left, None on construction. new_state - the state entered.
        Output:  None. At most one event is written.
        """
        entered = getattr(new_state, "name", str(new_state))
        if entered == pybreaker.STATE_OPEN:
            event_type, severity, message = (
                EventType.CIRCUIT_OPENED,
                Severity.HIGH,
                f"Circuit breaker opened for {self._dependency} after "
                f"{breaker.fail_max} consecutive failures; calls now return the "
                f"fallback without touching the network",
            )
        elif entered == pybreaker.STATE_CLOSED and old_state is not None:
            event_type, severity, message = (
                EventType.CIRCUIT_CLOSED,
                Severity.LOW,
                f"Circuit breaker closed for {self._dependency}; live calls resumed",
            )
        else:
            # Construction (old_state is None) and the half-open probe.
            return

        emit_event(
            build_event(
                service_name=self._service_name,
                event_type=event_type,
                severity=severity,
                endpoint=self._endpoint,
                http_method="GET",
                status_code=_DEPENDENCY_STATUS_CODE,
                message=message,
                correlation_id=get_correlation_id(),
                affected_entity=self._dependency,
            )
        )
