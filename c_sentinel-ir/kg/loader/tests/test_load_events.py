"""
test_load_events.py - the events source wires events and alerts together.

The step-17 handover: every alert gets a `CREATED_ALERT` edge from a real
event's id, an event against a numbered resource still targets a real Endpoint
node via its stem, and an event with no user emits no `TRIGGERED` edge.

Runs without Neo4j.

Author: Colile
"""

from __future__ import annotations

from soc.alert_service.store import AlertStore
from soc.collector.store import EventStore
from kg.loader.load_events import (
    _endpoint_stem,
    events,
    stable_alert_id,
    with_stable_ids,
)


def test_every_alert_has_a_created_alert_edge_from_a_real_event(
    event_store: EventStore, alert_store: AlertStore
):
    """`CREATED_ALERT` joins each alert back to an event actually in the store -
    the link a RAG answer follows to cite evidence."""
    writes = events(event_store, alert_store)
    known_event_ids = {e.event_id for e in event_store.all_events()}

    created = [w for w in writes if "CREATED_ALERT" in w.cypher]
    assert created
    for write in created:
        assert write.parameters["eventId"] in known_event_ids

    linked_alerts = {w.parameters["alertId"] for w in created}
    assert linked_alerts == {a.alert_id for a in alert_store.list()}


def test_events_come_before_alerts_so_the_edges_can_match(
    event_store: EventStore, alert_store: AlertStore
):
    """The `CREATED_ALERT` MATCH needs the Event node to exist already."""
    writes = events(event_store, alert_store)
    first_alert = next(
        i for i, w in enumerate(writes) if w.cypher.startswith("MERGE (a:Alert")
    )
    last_event = max(
        i for i, w in enumerate(writes) if w.cypher.startswith("MERGE (e:Event")
    )
    assert last_event < first_alert


def test_every_statement_is_a_merge(
    event_store: EventStore, alert_store: AlertStore
):
    """Reloading the event stream must not duplicate it."""
    for write in events(event_store, alert_store):
        assert "MERGE" in write.cypher
        assert "CREATE " not in write.cypher


def test_endpoint_stem_maps_a_numbered_resource_to_its_route():
    """`/api/v1/incidents/1` targets the `/api/v1/incidents` Endpoint node."""
    assert _endpoint_stem("/api/v1/incidents/1") == "/api/v1/incidents"
    assert _endpoint_stem("/api/v1/assets/2") == "/api/v1/assets"
    assert _endpoint_stem("/api/v1/auth/login") == "/api/v1/auth/login"


def test_an_event_with_no_user_emits_no_triggered_edge():
    """A gateway rejection names no user, so nothing TRIGGERED it."""
    from datetime import datetime, timezone

    from common.events import EventType, Severity, build_event

    store = EventStore()
    store.append(
        build_event(
            service_name="api-gateway",
            event_type=EventType.UNAUTHORISED_ACCESS,
            severity=Severity.MEDIUM,
            endpoint="/api/v1/incidents",
            http_method="GET",
            status_code=401,
            message="No valid token.",
            correlation_id="corr-x",
            user_id=None,
        ).model_copy(update={"timestamp": "2026-09-04T12:00:00Z"})
    )
    writes = events(store, AlertStore())
    assert not any("TRIGGERED" in w.cypher for w in writes)


def test_stable_alert_id_is_deterministic_for_the_same_firing(
    event_store: EventStore, alert_store: AlertStore
):
    """A reload MERGEs the same Alert node, so the graph is idempotent - the
    schema's own random `alertId` would create a fresh node each run."""
    alerts = alert_store.list()
    assert alerts

    first = with_stable_ids(alerts)
    second = with_stable_ids(alerts)
    assert [a.alert_id for a in first] == [a.alert_id for a in second]
    for alert in first:
        assert alert.alert_id.startswith("alt-")
        assert len(alert.alert_id) == len("alt-") + 12
        assert alert.alert_id == stable_alert_id(alert)


def test_stable_alert_id_differs_when_the_evidence_differs(
    alert_store: AlertStore
):
    """Two alerts citing different events are different findings and must not
    collapse onto one node."""
    alert = alert_store.list()[0]
    other = alert.model_copy(update={"related_events": ("evt-ffffffffffff",)})
    assert stable_alert_id(alert) != stable_alert_id(other)
