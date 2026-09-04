"""
load_events.py - source 2 of 3: what *happened* in the application.

Every `SecurityEvent` the collector holds and every `Alert` the rules raised,
wired into the graph:

  (:User)-[:TRIGGERED]->(:Event)-[:GENERATED_BY]->(:Service)
  (:Event)-[:TARGETED]->(:Endpoint)
  (:Event)-[:CREATED_ALERT]->(:Alert)

`CREATED_ALERT` is built from each alert's `relatedEvents`. That list is
guaranteed non-empty by the alert schema, so every stored alert joins back to
at least one event here - which is what lets a RAG answer cite the events that
caused an alert rather than assert a cause.

`events(store, alert_store)` is pure; a test asserts the `Write` list and `main`
applies it against a live database.

Author: Colile
"""

from __future__ import annotations

import hashlib

from soc.alert_service.models import Alert
from soc.alert_service.store import AlertStore
from soc.collector.store import EventStore
from kg.loader.writes import Write

_LOADER = "events"


def stable_alert_id(alert: Alert) -> str:
    """
    Purpose: a deterministic `alt-` id derived from what the rule actually saw -
             its name, the subjects it attributed, and the exact events it
             cited - so re-running the loader over the same stream MERGEs the
             same Alert node rather than creating a new one each time. The
             alert schema's own `alertId` is a fresh uuid per construction,
             which is right for the live API but makes a reload non-idempotent.
    Inputs:  alert - the `Alert` a rule raised.
    Output:  `alt-` followed by 12 hex characters of a SHA-1 over the firing's
             identifying fields.
    """
    material = "|".join(
        [
            alert.rule_name,
            alert.affected_service or "",
            alert.affected_user or "",
            alert.affected_entity or "",
            ",".join(sorted(alert.related_events)),
        ]
    )
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()
    return f"alt-{digest[:12]}"


def with_stable_ids(alerts: list[Alert]) -> list[Alert]:
    """
    Purpose: re-key a list of alerts onto `stable_alert_id`, so the graph is
             idempotent under reload.
    Inputs:  alerts - the alerts a rule run produced.
    Output:  a new list of `Alert`, each a copy carrying its stable id.
    """
    return [
        alert.model_copy(update={"alert_id": stable_alert_id(alert)})
        for alert in alerts
    ]

# Endpoint paths the topology loader creates. An event against anything else
# (a numbered resource like /api/v1/incidents/1) is attached to its stem so the
# `TARGETED` edge still lands on a real Endpoint node.
_KNOWN_ENDPOINTS = (
    "/api/v1/auth/login",
    "/api/v1/auth/verify",
    "/api/v1/auth/users",
    "/api/v1/incidents",
    "/api/v1/assets",
)


def _endpoint_stem(path: str) -> str:
    """
    Purpose: map a concrete request path to the Endpoint node the topology
             loader created - `/api/v1/incidents/1` -> `/api/v1/incidents`.
    Inputs:  path - the event's `endpoint`.
    Output:  the longest known endpoint that prefixes it, or the path itself.
    """
    matches = [known for known in _KNOWN_ENDPOINTS if path.startswith(known)]
    return max(matches, key=len) if matches else path


def _merge_event(event) -> list[Write]:
    """
    Purpose: an Event node and its `GENERATED_BY`, `TARGETED` and (where the
             event names a user) `TRIGGERED` edges.
    Inputs:  event - a `SecurityEvent`.
    Output:  a list of `Write`.
    """
    row = event.to_json_dict()
    writes = [
        Write(
            "MERGE (e:Event {eventId: $eventId}) SET "
            "e.timestamp = $timestamp, e.serviceName = $serviceName, "
            "e.eventType = $eventType, e.severity = $severity, "
            "e.endpoint = $endpoint, e.httpMethod = $httpMethod, "
            "e.statusCode = $statusCode, e.message = $message, "
            "e.correlationId = $correlationId, e.userId = $userId, "
            "e.sourceIp = $sourceIp",
            {
                "eventId": row["eventId"],
                "timestamp": row["timestamp"],
                "serviceName": row["serviceName"],
                "eventType": row["eventType"],
                "severity": row["severity"],
                "endpoint": row["endpoint"],
                "httpMethod": row["httpMethod"],
                "statusCode": row["statusCode"],
                "message": row["message"],
                "correlationId": row["correlationId"],
                "userId": row["userId"],
                "sourceIp": row["sourceIp"],
            },
            _LOADER,
        ),
        Write(
            "MERGE (s:Service {name: $serviceName}) "
            "WITH s MATCH (e:Event {eventId: $eventId}) "
            "MERGE (e)-[:GENERATED_BY]->(s)",
            {"serviceName": row["serviceName"], "eventId": row["eventId"]},
            _LOADER,
        ),
        Write(
            "MERGE (n:Endpoint {path: $path}) "
            "WITH n MATCH (e:Event {eventId: $eventId}) "
            "MERGE (e)-[:TARGETED]->(n)",
            {"path": _endpoint_stem(row["endpoint"]), "eventId": row["eventId"]},
            _LOADER,
        ),
    ]
    if row["userId"]:
        writes.append(
            Write(
                "MERGE (u:User {username: $userId}) "
                "WITH u MATCH (e:Event {eventId: $eventId}) "
                "MERGE (u)-[:TRIGGERED]->(e)",
                {"userId": row["userId"], "eventId": row["eventId"]},
                _LOADER,
            )
        )
    return writes


def _merge_alert(alert) -> list[Write]:
    """
    Purpose: an Alert node and one `CREATED_ALERT` edge from every event it
             cites in `relatedEvents`.
    Inputs:  alert - an `Alert`.
    Output:  a list of `Write`.
    """
    row = alert.to_json_dict()
    writes = [
        Write(
            "MERGE (a:Alert {alertId: $alertId}) SET "
            "a.timestamp = $timestamp, a.ruleName = $ruleName, "
            "a.severity = $severity, a.status = $status, "
            "a.description = $description, a.affectedService = $affectedService, "
            "a.affectedUser = $affectedUser, a.affectedEntity = $affectedEntity, "
            "a.recommendedAction = $recommendedAction",
            {
                "alertId": row["alertId"],
                "timestamp": row["timestamp"],
                "ruleName": row["ruleName"],
                "severity": row["severity"],
                "status": row["status"],
                "description": row["description"],
                "affectedService": row["affectedService"],
                "affectedUser": row["affectedUser"],
                "affectedEntity": row["affectedEntity"],
                "recommendedAction": row["recommendedAction"],
            },
            _LOADER,
        )
    ]
    for event_id in alert.related_events:
        writes.append(
            Write(
                "MATCH (e:Event {eventId: $eventId}) "
                "MATCH (a:Alert {alertId: $alertId}) "
                "MERGE (e)-[:CREATED_ALERT]->(a)",
                {"eventId": event_id, "alertId": row["alertId"]},
                _LOADER,
            )
        )
    return writes


def events(store: EventStore, alert_store: AlertStore) -> list[Write]:
    """
    Purpose: the whole live-events-and-alerts source as idempotent writes -
             every event first (so the `CREATED_ALERT` edges have something to
             MATCH), then every alert with its edges back to those events.
    Inputs:  store - the collector's populated `EventStore`; alert_store - the
             `AlertStore` the rule runner filled.
    Output:  a list of `Write`, events before alerts.
    """
    writes: list[Write] = []
    for event in store.all_events():
        writes.extend(_merge_event(event))
    for alert in alert_store.list():
        writes.extend(_merge_alert(alert))
    return writes
