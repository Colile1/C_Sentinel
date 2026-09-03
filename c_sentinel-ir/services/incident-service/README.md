# services/incident-service/

The core of the domain. Owns security incidents: what happened, how severe it is, who reported it,
which asset it affects, and where it sits in its lifecycle. It is the only service that calls
another, which makes it the home of the resilience pattern.

Direct port 8002. Its database is `incident_db`.

## Planned files

| File | Responsibility |
|------|----------------|
| `app/main.py` | `create_app() -> FastAPI` — wiring only |
| `app/models.py` | `Incident` — id, title, description, severity (LOW/MEDIUM/HIGH/CRITICAL), status (OPEN/TRIAGED/RESOLVED), `reported_by`, `asset_id`, `asset_name_snapshot`, `created_at`, `updated_at` |
| `app/schemas.py` | `IncidentCreate`, `IncidentUpdate`, `IncidentRead`, `SeverityChange` |
| `app/repositories/incident_repository.py` | `get`, `list(status=None, severity=None)`, `create`, `update`, `delete` |
| `app/services/asset_gateway.py` | `fetch_asset(asset_id, correlation_id) -> AssetSummary` — the **only** place `asset-service` is called, through `ResilientClient`. Its declared fallback returns an `AssetSummary` marked `available=False` so an incident can still be raised while the asset service is down |
| `app/services/incident_service.py` | Business logic: creating an incident validates the asset through `asset_gateway`, snapshots the asset name, sets the initial status, and emits `INCIDENT_CREATED` — with `severity` carried onto the event, so Phase 2's "creation of a high-priority incident" signal comes free. Escalation to CRITICAL emits `INCIDENT_ESCALATED` |
| `app/routers/incident_router.py` | `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`, `POST /api/v1/incidents`, `PUT /api/v1/incidents/{id}`, `PATCH /api/v1/incidents/{id}/severity`, `DELETE /api/v1/incidents/{id}` |
| `tests/test_incident_service.py` | Creation with a valid asset succeeds; an invalid severity is rejected naming the field; escalation emits exactly one `INCIDENT_ESCALATED` event |
| `tests/test_asset_gateway.py` | With the dependency failing, the fallback `AssetSummary` is returned, an incident is still created, and a `DEPENDENCY_FAILURE` event is emitted — the test that proves the pattern rather than assuming it |

## Integration

Called by the client through the gateway. Calls `asset-service` — and only through
`app/services/asset_gateway.py`, which is the sole importer of `ResilientClient` in this service. A
direct `httpx` call anywhere else in this folder is a defect: it bypasses the circuit breaker and
voids the pattern claim.

Depends on `libs/common` and `incident_db`. It never reads `asset_db`.

Done when: the full CRUD passes; an incident can be created while `asset-service` is stopped, with
the fallback recorded on the incident and a `DEPENDENCY_FAILURE` event in the log.
