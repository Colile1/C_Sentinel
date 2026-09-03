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
| `app/services/asset_gateway.py` | `fetch_asset(asset_id, correlation_id, settings) -> AssetSummary` — the **only** place `asset-service` is called. Its declared fallback returns an `AssetSummary` marked `available=False` so an incident can still be raised while the asset service is down. **Step 7 only calls it with a plain, timed-out `httpx.get`** — see the departure note below; step 8 wraps this exact call in `ResilientClient` for retry-with-backoff and the circuit breaker, without changing this module's public signature |
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

**Departure from the original plan (build step 7):** `libs/common/http_client.py` does not exist
until step 8, so `asset_gateway.fetch_asset` currently calls asset-service directly with `httpx.get`
and a 3-second timeout, degrading to the same documented fallback a `ResilientClient` will use. This
already satisfies step 7's own verification (CRUD plus a working severity workflow); step 8 replaces
the call inside this one function with `ResilientClient` for retry-with-backoff and the breaker,
without touching its callers. See `DECISIONS.md`.

Done when: the full CRUD passes; an incident can be created while `asset-service` is stopped, with
the fallback recorded on the incident. From step 8, that failure also carries a `DEPENDENCY_FAILURE`
event and the breaker's open/close events in the log.
