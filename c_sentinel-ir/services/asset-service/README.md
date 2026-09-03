# services/asset-service/

Owns the asset register: the servers, applications and systems an incident can be raised against.
Small on purpose — it exists to be a real second domain service and, in the demo, to be the
dependency that gets killed so the circuit breaker can be seen opening.

Direct port 8003. Its database is `asset_db`.

## Planned files

| File | Responsibility |
|------|----------------|
| `app/main.py` | Builds the app via `common.service.create_service_app("asset-service", check_database=database_reachable)` and, from step 6, mounts the asset routers onto it. No business logic. |
| `app/database.py` | The one SQLAlchemy engine for `asset_db`, created lazily with a short connect timeout, and `database_reachable()` — a `SELECT 1` the shared `/health` router calls. Holds this service's connection string and no other's. |
| `app/models.py` | `Asset` — id, name, `asset_type`, criticality (LOW/MEDIUM/HIGH/CRITICAL), owner, location, `created_at` |
| `app/schemas.py` | `AssetCreate`, `AssetUpdate`, `AssetRead` |
| `app/repositories/asset_repository.py` | `get(asset_id)`, `list(asset_type=None)`, `create(asset)`, `update(asset_id, changes)`, `delete(asset_id)` |
| `app/services/asset_service.py` | Business rules: a name must be unique, criticality must be one of the four values, deleting an asset is refused with a specific message when it is referenced. Raises `NotFoundError` and `ValidationError`; emits `ASSET_ACCESSED` for reads of CRITICAL assets, which Phase 2 uses as its "access to sensitive asset" signal |
| `app/routers/asset_router.py` | `GET /api/v1/assets`, `GET /api/v1/assets/{id}`, `POST /api/v1/assets`, `PUT /api/v1/assets/{id}`, `DELETE /api/v1/assets/{id}` |
| `tests/test_skeleton.py` | Build step 4: `/health` reports database reachability and returns 503 when the database is down, `/health/live` stays up regardless, `/metrics` returns Prometheus text, the correlation-id header round-trips, unknown routes use the shared error shape |
| `tests/test_asset_service.py` | Duplicate name rejected with a named field; unknown id raises `NotFoundError`; reading a CRITICAL asset emits exactly one `ASSET_ACCESSED` event |
| `tests/test_asset_repository.py` | CRUD round-trips against a test database |

## Integration

Called by the client through the gateway, and by `incident-service` through `ResilientClient` when
an incident names an asset. Calls nothing. Depends on `libs/common` and `asset_db`.

This service is deliberately the one stopped during the demo (`scripts/break_asset_service.py`), so
its unavailability must degrade `incident-service` gracefully rather than break it — that behaviour
belongs to `libs/common/http_client.py`, not here.

Done when: all five endpoints pass their tests, and reading a CRITICAL asset produces one event.
