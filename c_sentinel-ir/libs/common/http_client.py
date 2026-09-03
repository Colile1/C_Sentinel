"""
http_client.py - the only sanctioned way one service calls another.

Implements the second marked pattern, Circuit Breaker with Retry
(`docs/patterns.md` section 2). Two layers, and the order of nesting is the
whole design:

    breaker( retry( one HTTP GET ) )

Retry sits INSIDE the breaker, so a request that is retried three times and
still fails counts as ONE failure against the breaker, not three. Nested the
other way, `circuit_fail_max=3` would trip on the retries of a single request
and the threshold would mean nothing.

Only transient faults - a connection error, a timeout, a 5xx - are retried and
counted. A 4xx is a correct answer from a healthy dependency: retrying it wastes
the caller's latency, and letting it trip the breaker would take the dependency
out of service because a client asked for an id that does not exist.

Author: Colile
"""

from __future__ import annotations

from typing import Any, Callable, TypeVar

import httpx
import pybreaker
import tenacity

from common.circuit_events import BreakerEventListener, emit_dependency_failure
from common.config import Settings
from common.correlation import CORRELATION_ID_HEADER
from common.errors import DependencyUnavailableError

T = TypeVar("T")

# Below this, a status is either success or the caller's own mistake; at or
# above it the dependency itself is faulting, which is what retry and the
# breaker exist for.
_SERVER_ERROR_FLOOR = 500


class _TransientDependencyError(Exception):
    """
    Purpose: the single exception type retry and the breaker count as a failure.
             Connection errors, timeouts and 5xx responses are all normalised to
             it, so both layers have exactly one thing to watch for and a 4xx
             cannot be miscounted by either.
    Inputs:  message - what failed, carried through onto the emitted event.
    Output:  an exception instance.
    """


class ResilientClient:
    """
    Purpose: call one downstream service with retry-with-backoff and a circuit
             breaker in front of it. One instance guards one dependency, and it
             must be long-lived: a breaker constructed per call counts to one
             and never opens, which still passes a happy-path demo and loses the
             pattern mark.
    Inputs:  service_name - the calling service, named as the emitter of the
             resilience events. base_url - the dependency's root URL.
             dependency - the dependency's name, for events and logs.
             settings - supplies the timeout and the retry and breaker
             thresholds, so the demo can tune them without a code change.
    Output:  a client whose `get` never raises a transport error: it returns the
             caller's declared fallback, or raises `DependencyUnavailableError`
             when the caller declared none.
    """

    def __init__(
        self,
        *,
        service_name: str,
        base_url: str,
        dependency: str,
        settings: Settings,
    ) -> None:
        self._service_name = service_name
        self._base_url = base_url.rstrip("/")
        self._dependency = dependency
        self._timeout = settings.dependency_timeout_seconds
        self._max_attempts = settings.retry_max_attempts
        self._backoff = settings.retry_backoff_seconds
        self._breaker = pybreaker.CircuitBreaker(
            fail_max=settings.circuit_fail_max,
            reset_timeout=settings.circuit_reset_seconds,
            name=f"{service_name}->{dependency}",
            # Anything that is not a transient dependency fault - a 404 above
            # all - passes through without being counted against the threshold.
            exclude=[lambda exc: not isinstance(exc, _TransientDependencyError)],
            listeners=[
                BreakerEventListener(
                    service_name=service_name,
                    dependency=dependency,
                    endpoint=f"/{dependency}",
                )
            ],
        )

    @property
    def breaker_state(self) -> str:
        """
        Purpose: expose the breaker's state for the tests and the demo, without
                 letting a caller reach in and change it.
        Inputs:  none beyond the instance.
        Output:  `closed`, `open` or `half-open`.
        """
        return self._breaker.current_state

    def get(
        self,
        path: str,
        *,
        correlation_id: str,
        fallback: Callable[[], T] | None = None,
    ) -> Any:
        """
        Purpose: GET one path on the dependency through both resilience layers.
        Inputs:  path - the path on the dependency, e.g. `/api/v1/assets/1`.
                 correlation_id - propagated on the request so the two services'
                 logs join, and carried onto any event this call emits.
                 fallback - a zero-argument callable producing the degraded
                 result. Declared by the caller, because only the caller knows
                 what a safe degraded answer for its own domain looks like.
        Output:  the decoded JSON body on success, or the fallback's result when
                 the dependency failed or the breaker is open.
        Raises:  `httpx.HTTPStatusError` for a 4xx - a real answer from a healthy
                 dependency, never masked as a fallback.
                 `DependencyUnavailableError` (503) when the dependency failed
                 and the caller declared no fallback.
        """
        # Read before the call, because the call itself may change it. A call
        # made while the breaker was already open never reached the network; a
        # call that *trips* the breaker did, and its failure must still be
        # recorded even though pybreaker reports the trip rather than the cause.
        was_open = self.breaker_state == pybreaker.STATE_OPEN
        try:
            return self._breaker.call(self._call_with_retry, path, correlation_id)
        except pybreaker.CircuitBreakerError as exc:
            if was_open:
                # Suppressed before it left the process. Deliberately silent on
                # the event stream: CIRCUIT_OPENED already recorded the outage,
                # and one DEPENDENCY_FAILURE per suppressed call would flood
                # Rule 4 with calls that never touched the network.
                return self._degrade(
                    "circuit breaker is open", path, fallback, emit=False
                )
            # This call is the one that tripped it, so it genuinely failed.
            # pybreaker reports the trip ("failures threshold reached"), which
            # says nothing about the cause; the original fault is chained onto
            # it, so record that instead and keep the trip text as a fallback.
            cause = exc.__cause__ or exc.__context__
            reason = str(cause) if isinstance(cause, _TransientDependencyError) else str(exc)
            return self._degrade(
                reason, path, fallback, correlation_id=correlation_id
            )
        except _TransientDependencyError as exc:
            return self._degrade(
                str(exc), path, fallback, correlation_id=correlation_id
            )

    def _call_with_retry(self, path: str, correlation_id: str) -> Any:
        """
        Purpose: perform the GET, retrying transient failures with exponential
                 backoff. Wrapped by the breaker, so all of its attempts together
                 count as one failure against the threshold.
        Inputs:  path - the dependency path. correlation_id - propagated header.
        Output:  the decoded JSON body.
        Raises:  `_TransientDependencyError` once every attempt is spent;
                 `httpx.HTTPStatusError` immediately for a 4xx, unretried.
        """
        retrying = tenacity.Retrying(
            stop=tenacity.stop_after_attempt(self._max_attempts),
            wait=tenacity.wait_exponential(multiplier=self._backoff),
            retry=tenacity.retry_if_exception_type(_TransientDependencyError),
            reraise=True,
        )
        return retrying(self._attempt, path, correlation_id)

    def _attempt(self, path: str, correlation_id: str) -> Any:
        """
        Purpose: one single HTTP GET, with every transient fault normalised to
                 `_TransientDependencyError` and every 4xx left to propagate.
        Inputs:  path - the dependency path. correlation_id - propagated header.
        Output:  the decoded JSON body.
        Raises:  `_TransientDependencyError` on a connection error, a timeout or
                 a 5xx; `httpx.HTTPStatusError` on a 4xx.
        """
        url = f"{self._base_url}{path}"
        headers = {CORRELATION_ID_HEADER: correlation_id}
        try:
            response = httpx.get(url, headers=headers, timeout=self._timeout)
        except httpx.HTTPError as exc:
            raise _TransientDependencyError(f"{type(exc).__name__}: {exc}") from exc
        if response.status_code >= _SERVER_ERROR_FLOOR:
            raise _TransientDependencyError(
                f"{self._dependency} returned {response.status_code}"
            )
        response.raise_for_status()
        return response.json()

    def _degrade(
        self,
        reason: str,
        path: str,
        fallback: Callable[[], T] | None,
        *,
        emit: bool = True,
        correlation_id: str = "",
    ) -> T:
        """
        Purpose: the one place a failed call becomes a degraded result, so the
                 returned fallback and the emitted event can never disagree
                 about what happened.
        Inputs:  reason - why the call failed. path - the path attempted.
                 fallback - the caller's degraded result, or None.
                 emit - whether to record a `DEPENDENCY_FAILURE`.
                 correlation_id - carried onto that event.
        Output:  the fallback's result.
        Raises:  `DependencyUnavailableError` when no fallback was declared.
        """
        if emit:
            emit_dependency_failure(
                service_name=self._service_name,
                endpoint=path,
                dependency=self._dependency,
                reason=reason,
                correlation_id=correlation_id,
            )
        if fallback is None:
            raise DependencyUnavailableError(
                f"{self._dependency} could not be reached: {reason}",
                {"dependency": self._dependency, "path": path, "reason": reason},
            )
        return fallback()
