"""
capture_attack_evidence.py - write the scripted attack the detection rules fire
on, as a newline-JSON event stream.

Runs offline, like `capture_breaker_evidence.py`: no Docker, no network. It
writes `docs/evidence/step15-attack-events.jsonl`, which is the input to

    python -m soc.rules.main --file docs/evidence/step15-attack-events.jsonl

so the rules can be demonstrated on camera without first staging a live attack
against the stack. The live equivalent is `client/failed_login_demo.py` plus the
gateway burst in `tests/integration`; this file is the reproducible twin.

The attack is one story told in order: an attacker brute-forces an analyst
account, gets in, probes endpoints its role does not cover including the admin
route, then floods the gateway until the rate limiter refuses it and
asset-service falls over behind the breaker.

Author: Colile
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from common.events import EventType, SecurityEvent, Severity, build_event

OUTPUT_PATH = Path("docs") / "evidence" / "step15-attack-events.jsonl"

# The attack is written around a fixed instant, so a rerun reproduces the same
# story at the same times and `--now` can pin the evaluation moment. The event
# ids still differ per run - `build_event` mints them, as it must - so a rerun
# does show a diff.
ATTACK_START = datetime(2026, 9, 4, 12, 0, 0, tzinfo=timezone.utc)

ATTACKER_IP = "203.0.113.9"
VICTIM_USER = "analyst-1"


def _at(offset_seconds: int, **fields) -> SecurityEvent:
    """
    Purpose: one event stamped at a fixed offset into the attack.
    Inputs:  offset_seconds - seconds after `ATTACK_START`; fields - the event's
             values, passed straight to `build_event`.
    Output:  a validated `SecurityEvent` with the offset timestamp.
    """
    moment = ATTACK_START + timedelta(seconds=offset_seconds)
    return build_event(**fields).model_copy(
        update={"timestamp": moment.strftime("%Y-%m-%dT%H:%M:%SZ")}
    )


def _brute_force() -> list[SecurityEvent]:
    """
    Purpose: phase one - six failed logins against one account from one address,
             then the success that means the attacker guessed it.
    Inputs:  none.
    Output:  a list of `SecurityEvent`.
    """
    events = [
        _at(
            index * 8,
            service_name="auth-service",
            event_type=EventType.AUTH_FAILED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            status_code=401,
            user_id=VICTIM_USER,
            source_ip=ATTACKER_IP,
            correlation_id=f"corr-bruteforce-{index}",
            message="Authentication failed: invalid credentials.",
            affected_entity="login-endpoint",
        )
        for index in range(6)
    ]
    events.append(
        _at(
            56,
            service_name="auth-service",
            event_type=EventType.AUTH_SUCCESS,
            severity=Severity.LOW,
            endpoint="/api/v1/auth/login",
            http_method="POST",
            status_code=200,
            user_id=VICTIM_USER,
            source_ip=ATTACKER_IP,
            correlation_id="corr-bruteforce-hit",
            message="Authentication succeeded.",
            affected_entity="login-endpoint",
        )
    )
    return events


def _endpoint_probing() -> list[SecurityEvent]:
    """
    Purpose: phase two - the stolen token probing endpoints outside its role,
             ending on the admin route, which is what raises Rule 2 to HIGH.
    Inputs:  none.
    Output:  a list of `SecurityEvent`.
    """
    probes = [
        ("/api/v1/incidents", "api-gateway", EventType.UNAUTHORISED_ACCESS, 403),
        ("/api/v1/assets", "api-gateway", EventType.UNAUTHORISED_ACCESS, 403),
        ("/api/v1/auth/users", "auth-service", EventType.REQUEST_COMPLETED, 403),
    ]
    return [
        _at(
            90 + index * 15,
            service_name=service,
            event_type=event_type,
            severity=Severity.MEDIUM,
            endpoint=path,
            http_method="GET",
            status_code=status,
            user_id=VICTIM_USER,
            source_ip=ATTACKER_IP,
            correlation_id=f"corr-probe-{index}",
            message=f"Request to {path} refused: caller is not authorised.",
            affected_entity=path,
        )
        for index, (path, service, event_type, status) in enumerate(probes)
    ]


def _request_flood() -> list[SecurityEvent]:
    """
    Purpose: phase three - a burst that the gateway's rate limiter refuses, which
             is what Rule 3 sees in practice.
    Inputs:  none.
    Output:  a list of `SecurityEvent`.
    """
    return [
        _at(
            200 + index,
            service_name="api-gateway",
            event_type=EventType.RATE_LIMIT_EXCEEDED,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/incidents",
            http_method="GET",
            status_code=429,
            user_id=VICTIM_USER,
            source_ip=ATTACKER_IP,
            correlation_id=f"corr-flood-{index}",
            message="Request refused: rate limit exceeded.",
            affected_entity="rate-limit",
        )
        for index in range(8)
    ]


def _dependency_collapse() -> list[SecurityEvent]:
    """
    Purpose: phase four - asset-service buckles under the load, incident-service
             exhausts its retries and the breaker opens. Rule 4's input, and the
             point where Phase 1's marked circuit-breaker pattern feeds the SOC
             layer directly.
    Inputs:  none.
    Output:  a list of `SecurityEvent`.
    """
    failures = [
        _at(
            215 + index * 4,
            service_name="incident-service",
            event_type=EventType.DEPENDENCY_FAILURE,
            severity=Severity.HIGH,
            endpoint="/api/v1/incidents",
            http_method="POST",
            status_code=503,
            correlation_id=f"corr-dependency-{index}",
            message="Call to asset-service failed after retries: timeout.",
            affected_entity="asset-service",
        )
        for index in range(3)
    ]
    failures.append(
        _at(
            228,
            service_name="incident-service",
            event_type=EventType.CIRCUIT_OPENED,
            severity=Severity.HIGH,
            endpoint="/api/v1/incidents",
            http_method="POST",
            status_code=503,
            correlation_id="corr-breaker-open",
            message="Circuit opened for asset-service after 3 consecutive failures.",
            affected_entity="asset-service",
        )
    )
    return failures


def build_attack() -> list[SecurityEvent]:
    """
    Purpose: the whole scripted attack, in the order it happens.
    Inputs:  none.
    Output:  a list of `SecurityEvent`.
    """
    return (
        _brute_force()
        + _endpoint_probing()
        + _request_flood()
        + _dependency_collapse()
    )


def main() -> int:
    """
    Purpose: write the attack stream to the evidence file.
    Inputs:  none; the destination is `OUTPUT_PATH`, relative to c_sentinel-ir/.
    Output:  a process exit code, 0 on success.
    """
    events = build_attack()
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(event.to_json_dict()) for event in events]
    OUTPUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"Attack events written: {len(events)}")
    print(f"Output file: {OUTPUT_PATH}")
    print(f"Attack window: {events[0].timestamp} to {events[-1].timestamp}")
    print(f"Attacker address: {ATTACKER_IP}")
    print(f"Targeted account: {VICTIM_USER}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
