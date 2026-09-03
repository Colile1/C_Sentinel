# services/incident-service/

The core of the domain. Owns security incidents: what happened, how severe it is, who reported it,
which asset it affects, and where it sits in its lifecycle. It is the only service that calls
another, which makes it the home of the resilience pattern.

Direct port 8002. Its database is `incident_db`.

## Planned files

| File | Responsibility |
|------|----------------|
| `app/main.py` | Builds the app via `common.service.create_service_app("incident-service", check_database=database_reachable, on_startup=init_database)` and mounts the incident router onto it. No business logic. |
| `app/database.py` | The one SQLAlchemy engine for `incident_db`, its session factory, `init_database()` and `database_reachable()` — the shared shell used by every service. Holds this service's connection string and no other's. |
| `app/models.py` | `Incident` — id, title, description, severity (LOW/MEDIUM/HIGH/CRITICAL), status (OPEN/TRIAGED/RESOLVED), `reported_by`, `asset_id`, `asset_name_snapshot`, `created_at`, `updated_at` |
| `app/schemas.py` | `IncidentCreate`, `IncidentUpdate`, `IncidentRead`, `SeverityChange` |
| `app/repositories/incident_repository.py` | `get`, `list(status=None, severity=None)`, `create`, `update`, `delete` |
| `app/services/asset_gateway.py` | `fetch_asset(asset_id, correlation_id, settings) -> AssetSummary` — the **only** place `asset-service` is called. Its declared fallback returns an `AssetSummary` marked `available=False` so an incident can still be raised while the asset service is down. Calls through `ResilientClient` (retry plus circuit breaker), holding one long-lived client per asset-service URL in `_client_for` — the breaker's failure count is the pattern's state, so a client rebuilt per call would never open |
| `app/services/incident_service.py` | Business logic: creating an incident validates the asset through `asset_gateway`, snapshots the asset name, sets the initial status, and emits `INCIDENT_CREATED` — with `severity` carried onto the event, so Phase 2's "creation of a high-priority incident" signal comes free. Escalating to HIGH or CRITICAL emits `INCIDENT_ESCALATED` |
| `app/routers/incident_router.py` | `GET /api/v1/incidents`, `GET /api/v1/incidents/{id}`, `POST /api/v1/incidents`, `PUT /api/v1/incidents/{id}`, `PATCH /api/v1/incidents/{id}/severity`, `DELETE /api/v1/incidents/{id}` |
| `tests/test_skeleton.py` | The shared shell, built here for the first time: `/health`, `/health/live`, `/metrics`, correlation-id echo, the shared error shape |
| `tests/test_incident_service.py` | Creation with a valid asset succeeds; an invalid severity is rejected naming the field; escalation to HIGH/CRITICAL emits exactly one `INCIDENT_ESCALATED` event, a demotion or a move within LOW/MEDIUM emits none |
| `tests/test_asset_gateway.py` | Against a mock HTTP transport: a successful lookup, a genuine 404 propagated rather than masked, and a connection failure or 5xx returning the documented fallback |
| `tests/test_incident_repository.py` | CRUD and filtering round-trip against a test database |
| `tests/test_incident_router.py` | The six endpoints over the real ASGI stack, including the 422 on a bad severity |

## Integration

Called by the client through the gateway. Calls `asset-service` — and only through
`app/services/asset_gateway.py`, which from build step 8 onward is the sole importer of
`ResilientClient` in this service. A direct `httpx` call anywhere else in this folder is a defect: it
bypasses the circuit breaker and voids the pattern claim.

Depends on `libs/common` and `incident_db`. It never reads `asset_db`.

**The step 7 departure is closed.** `asset_gateway.fetch_asset` briefly called asset-service directly
with `httpx.get` because `libs/common/http_client.py` was step 8's deliverable and did not yet exist
(D-14). Step 8 built the client and replaced the call inside that one function; its public signature,
its fallback and its callers are unchanged, exactly as the decision anticipated.

Done when: the full CRUD passes; an incident can be created while `asset-service` is stopped, with
the fallback recorded on the incident, and that failure carries a `DEPENDENCY_FAILURE` event and the
breaker's open/close events in the log. **Met at step 8.**
