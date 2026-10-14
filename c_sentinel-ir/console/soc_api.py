"""
soc_api.py - the Phase 2 SOC layer for the UI: events, rules, detection.

Thin, like every entry point here: it calls the collector, the rule catalogue
and `soc.rules.main.persist_alerts` exactly as their CLIs do, and only shapes
the results as JSON. The alert listing and status changes themselves are the
alert service's own router, mounted in the same process by `console.main`, so
the alerts a detection run stores here are the ones `/api/v1/alerts` serves.

Two event sources, matching the CLIs' `--file` and default modes:
  capture   the committed attack capture, docs/evidence/step15-attack-events.jsonl
            - works with no Docker at all
  live      `docker compose logs` of the running stack

Author: Colile
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from common.errors import ValidationError

from soc.alert_service.dependencies import get_alert_store
from soc.collector.main import build_store, select_source
from soc.collector.store import EventStore
from soc.rules.catalogue import all_rules, evaluate_all
from soc.rules.main import latest_event_time, persist_alerts

from console.settings import CAPTURED_EVENTS

router = APIRouter(prefix="/console/api/soc", tags=["soc"])


class EventSource(str, Enum):
    """Where the collector reads events from."""

    CAPTURE = "capture"
    LIVE = "live"


class DetectionRequest(BaseModel):
    """Body of a detection run: the event source to evaluate."""

    source: EventSource = EventSource.CAPTURE


def collect(source: EventSource) -> EventStore:
    """
    Purpose: build a fresh event store from one source.
    Inputs:  source - capture or live.
    Output:  the populated `EventStore`.
    Raises:  `ValidationError` (422) naming the problem when the source cannot
             be read - most often Docker missing for `live`.
    """
    try:
        path = Path(CAPTURED_EVENTS) if source is EventSource.CAPTURE else None
        # The same resolution the CLIs use: a file when given, else docker logs.
        return build_store(select_source(argparse.Namespace(file=path, stdin=False)))
    except (RuntimeError, OSError, ValueError) as exc:
        raise ValidationError(
            f"could not collect events from the {source.value} source: {exc}",
            {"source": source.value},
        ) from exc


@router.get("/events", summary="Collected security events with facets")
def list_events(
    source: Annotated[EventSource, Query()] = EventSource.CAPTURE,
    event_type: Annotated[str | None, Query(alias="eventType")] = None,
    service: Annotated[str | None, Query()] = None,
    user: Annotated[str | None, Query()] = None,
    correlation_id: Annotated[str | None, Query(alias="correlationId")] = None,
) -> dict[str, Any]:
    """
    Purpose: the event explorer - every collected event, optionally narrowed,
             with counts per type and service for the summary chips.
    Inputs:  source and four optional exact-match filters.
    Output:  {total, shown, facets: {eventType, serviceName}, events: [...]}
             with events newest first, in the published camelCase schema.
    """
    events = collect(source).all_events()
    facets = {
        "eventType": Counter(event.event_type.value for event in events),
        "serviceName": Counter(event.service_name for event in events),
    }
    chosen = [
        event
        for event in events
        if (event_type is None or event.event_type.value == event_type)
        and (service is None or event.service_name == service)
        and (user is None or event.user_id == user)
        and (correlation_id is None or event.correlation_id == correlation_id)
    ]
    return {
        "source": source.value,
        "total": len(events),
        "shown": len(chosen),
        "facets": {name: dict(counts) for name, counts in facets.items()},
        "events": [event.to_json_dict() for event in reversed(chosen)],
    }


@router.get("/rules", summary="The detection rule catalogue")
def rule_catalogue() -> list[dict[str, Any]]:
    """
    Purpose: every rule's documented properties, read from the code itself as
             `soc.rules.main --catalogue` does.
    Inputs:  none.
    Output:  a JSON array, one object per rule.
    """
    return [
        {
            "name": rule.name,
            "purpose": rule.purpose,
            "inputEvents": [event_type.value for event_type in rule.input_event_types],
            "severity": rule.severity.value,
            "recommendedAction": rule.recommended_action,
        }
        for rule in all_rules()
    ]


@router.post("/detect", summary="Run every detection rule and store the alerts")
def run_detection(request: DetectionRequest) -> dict[str, Any]:
    """
    Purpose: the SOC workflow's detection stage - collect, evaluate, store.
             The store is cleared first, so a re-run replaces the previous
             evaluation instead of duplicating it under fresh alert ids.
    Inputs:  request - the event source.
    Output:  the run summary plus the alerts raised, newest first.
    """
    store = collect(request.source)
    if request.source is EventSource.CAPTURE:
        now = latest_event_time(store) or datetime.now(timezone.utc)
    else:
        now = datetime.now(timezone.utc)
    alerts = evaluate_all(store, now)
    get_alert_store().clear()
    stored = persist_alerts(alerts, store)
    return {
        "source": request.source.value,
        "eventsEvaluated": len(store),
        "evaluationMoment": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "alertsRaised": len(alerts),
        "alertsStored": stored,
        "alerts": [alert.to_json_dict() for alert in alerts],
    }


@router.get("/alerts/{alert_id}/events", summary="The events an alert cites")
def alert_events(
    alert_id: str,
    source: Annotated[EventSource, Query()] = EventSource.CAPTURE,
) -> list[dict[str, Any]]:
    """
    Purpose: resolve an alert's `relatedEvents` ids back to the full events,
             so the UI can show the evidence a rule fired on.
    Inputs:  alert_id - the alert; source - where its events were collected.
    Output:  the cited events in time order. 404 for an unknown alert.
    """
    cited = set(get_alert_store().get(alert_id).related_events)
    return [
        event.to_json_dict()
        for event in collect(source).all_events()
        if event.event_id in cited
    ]
