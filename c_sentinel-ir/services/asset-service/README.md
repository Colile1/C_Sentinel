# services/asset-service/

Owns the asset register: the servers, applications and systems an incident can be raised against.
Small on purpose — it exists to be a real second domain service and, in the demo, to be the
dependency that gets killed so the circuit breaker can be seen opening.

Direct port 8003. Its database is `asset_db`.

## Planned files

| File | Responsibility |
|------|----------------|
| `app/main.py` | Builds the app via `common.service.create_service_app("asset-service", check_database=database_reachable, on_startup=init_database)` and mounts the asset router onto it. No business logic. |
| `app/database.py` | The one SQLAlchemy engine for `asset_db`, its session factory, `init_database()` and `database_reachable()` — a `SELECT 1` the shared `/health` router calls. Holds this service's connection string and no other's. |
| `app/models.py` | `Asset` — id, name, `asset_type`, criticality (LOW/MEDIUM/HIGH/CRITICAL), owner, location, `created_at` |
| `app/schemas.py` | `AssetCreate`, `AssetUpdate`, `AssetRead` |
| `app/repositories/asset_repository.py` | `get(asset_id)`, `list(asset_type=None)`, `create(asset)`, `update(asset_id, changes)`, `delete(asset_id)` |
| `app/services/asset_service.py` | Business rules: a name must be unique, criticality must be one of the four values. Raises `NotFoundError` and `ConflictError`; emits `ASSET_ACCESSED` for reads of CRITICAL assets, which Phase 2 uses as its "access to sensitive asset" signal |
| `app/routers/asset_router.py` | `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `POST /api/v1/assets`, `PUT /api/v1/assets/{id}`, `DELETE /api/v1/assets/{id}` |
| `tests/test_skeleton.py` | Build step 4: `/health` reports database reachability and returns 503 when the database is down, `/health/live` stays up regardless, `/metrics` returns Prometheus text, the correlation-id header round-trips, unknown routes use the shared error shape |
| `tests/test_asset_service.py` | Duplicate name rejected with a named field; unknown id raises `NotFoundError`; reading a CRITICAL asset emits exactly one `ASSET_ACCESSED` event, a non-CRITICAL read emits none |
| `tests/test_asset_repository.py` | CRUD, filtering and the conflict round-trip against a test database |
| `tests/test_asset_router.py` | The five endpoints over the real ASGI stack: 404, 409 and 422 in their documented shapes |

## Integration

Called by the client through the gateway, and by `incident-service` through `ResilientClient` when
an incident names an asset. Calls nothing. Depends on `libs/common` and `asset_db`.

**Departure from the original plan:** the README's original delete rule — refuse deletion of an
asset that is referenced by an incident — is not implemented here. Checking that would mean this
service reading `incident_db`, which violates Database-per-Service; the refusal, if wanted, belongs
in `incident-service` or is a cross-service check added later. Not needed for step 6's own
verification. See `DECISIONS.md`.

This service is deliberately the one stopped during the demo (`scripts/break_asset_service.py`), so
its unavailability must degrade `incident-service` gracefully rather than break it — that behaviour
belongs to `libs/common/http_client.py`, not here.

Done when: all five endpoints pass their tests, and reading a CRITICAL asset produces one event.
