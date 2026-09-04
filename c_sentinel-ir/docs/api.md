# API documentation

**Base URL:** `http://localhost:8000/api/v1` — the gateway. Every endpoint below is reached through
it. Direct service ports (8001-8003) exist for inspection and are not part of the public API.

Interactive OpenAPI documentation is generated per service by FastAPI at `/docs` on each service
port; this file is the consolidated catalogue the submission sheet asks for.

Fill in each section as its endpoint is built. Every row needs: method, path, auth requirement,
request body, response body, and status codes.

## Conventions

- Nouns in the path, plural: `/incidents`, `/assets`, `/auth/users`.
- `200` read, `201` created, `204` deleted, `400` malformed, `401` no or bad token, `403` wrong role,
  `404` unknown id, `409` conflict, `422` validation failure naming the field, `429` rate limited.
- All responses are JSON objects. Errors use one shape, produced by `install_error_handlers` and
  by nothing else: `{"error": "<CODE>", "message": "<one sentence>", "details": {...}}`. `details`
  is an object, empty when there is nothing structured to add, and carries the offending field on a
  validation failure.
- Every request may carry `X-Correlation-ID`; every response returns one. When the client does not
  send one, the gateway's `correlation-id` plugin mints it; when the client does, it is passed
  through unchanged and echoed back, so the client can quote the id it chose.
- Protected endpoints require `Authorization: Bearer <jwt>`.

## What the gateway enforces before a service is reached

Everything below `/api/v1` except `POST /api/v1/auth/login` requires a valid token, and the check
happens at Kong (`gateway/kong.yml`), not in the service. A missing, malformed, expired or tampered
token returns Kong's own body — note that it is *not* the services' error shape, because no service
was involved:

```json
{ "message": "Unauthorized" }
```

Exceeding 60 requests per minute returns `429` with the same style of body. Every response, including
these, carries `X-Correlation-ID` and the `RateLimit-*` headers, so a rejected request is still
traceable in the event stream.

## auth-service

Built at build step 5. Paths below are shown without the `/api/v1` prefix every route carries;
the full path to login is `/api/v1/auth/login`.

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | public | Exchange credentials for a JWT |
| GET | `/auth/verify` | bearer | Validate the current token and return its claims |
| POST | `/auth/users` | bearer, admin | Create a user |
| GET | `/auth/users` | bearer, admin | List users |

### POST /api/v1/auth/login

Request:

```json
{ "username": "admin", "password": "admin-password" }
```

`200` — the token is HS256 and carries `sub`, `role`, `iss`, `iat` and `exp`:

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "role": "admin"
}
```

`401` — an unknown username, a wrong password and a disabled account are deliberately
indistinguishable here; the reason is on the event stream, not in the response (D-11):

```json
{
  "error": "AUTHENTICATION_ERROR",
  "message": "The username or password is incorrect.",
  "details": { "reason": "invalid_credentials" }
}
```

Either outcome emits exactly one event — `AUTH_SUCCESS` or `AUTH_FAILED` — carrying the request's
correlation ID. `422` when the body is missing a field.

### GET /api/v1/auth/verify

`Authorization: Bearer <jwt>`. `200`:

```json
{
  "valid": true,
  "username": "admin",
  "role": "admin",
  "issued_at": 1788420985,
  "expires_at": 1788424585
}
```

`401` with `details.reason` of `expired`, `invalid_token`, `invalid_claims` or
`missing_bearer_token`.

### POST /api/v1/auth/users

Admin only. Request:

```json
{
  "username": "analyst1",
  "email": "analyst1@sentinel.local",
  "password": "analyst-password",
  "role": "analyst"
}
```

`201` returns the created user with no password field of any kind:

```json
{
  "id": 2,
  "username": "analyst1",
  "email": "analyst1@sentinel.local",
  "role": "analyst",
  "is_active": true,
  "created_at": "2026-09-03T07:36:28.083416"
}
```

`403` for a non-admin, `409` when the username or email is taken, `422` on a short password, a
malformed address or a role outside `admin` / `analyst`.

### GET /api/v1/auth/users

Admin only. `200` with the array above, oldest first. `403` for a non-admin.

## incident-service

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/incidents` | bearer | List incidents, filterable by status and severity |
| GET | `/incidents/{id}` | bearer | Read one incident |
| POST | `/incidents` | bearer | Raise an incident against an asset |
| PUT | `/incidents/{id}` | bearer | Update an incident |
| PATCH | `/incidents/{id}/severity` | bearer | Change severity — emits an escalation event |
| DELETE | `/incidents/{id}` | bearer, admin | Delete an incident |

Built at build steps 7 and 8. Paths below are shown without the `/api/v1` prefix.

### POST /api/v1/incidents

Request:

```json
{
  "title": "Suspicious login pattern on core-auth-db",
  "description": "Five failed logins for the same account inside one minute.",
  "severity": "MEDIUM",
  "reported_by": "analyst1",
  "asset_id": 1
}
```

`201` — `asset_name_snapshot` is fetched from asset-service through
`libs/common/http_client.py` at creation time and stored, not looked up again on every read:

```json
{
  "id": 20,
  "title": "Suspicious login pattern on core-auth-db",
  "description": "Five failed logins for the same account inside one minute.",
  "severity": "MEDIUM",
  "status": "OPEN",
  "reported_by": "analyst1",
  "asset_id": 1,
  "asset_name_snapshot": "core-auth-db",
  "created_at": "2026-09-04T09:12:03.441Z",
  "updated_at": "2026-09-04T09:12:03.441Z"
}
```

`422` when a field is missing or out of range (`title`, `description`, `severity`, `reported_by`,
`asset_id` — see `services/incident-service/app/schemas.py`). One `INCIDENT_CREATED` event is
emitted, carrying the request's correlation ID. If `asset-service` cannot be reached, the circuit
breaker's fallback still lets the incident be created, degraded — see `docs/patterns.md` pattern 2.

### GET /api/v1/incidents and GET /api/v1/incidents/{id}

`200` with an `IncidentRead` array or object as shown above. The list endpoint accepts optional
`?status=` and `?severity=` query filters. `404` on an unknown id.

### PUT /api/v1/incidents/{id}

Request carries only the fields being changed — `title`, `description` and/or `status`; severity
changes go through its own endpoint below, not this one. `200` with the updated incident, `404` on
an unknown id.

### PATCH /api/v1/incidents/{id}/severity

Request:

```json
{ "severity": "HIGH" }
```

`200` with the updated incident. `404` on an unknown id, `422` when `severity` is not one of `LOW`,
`MEDIUM`, `HIGH`, `CRITICAL`. Escalating to `HIGH` or `CRITICAL` emits one `INCIDENT_ESCALATED`
event.

### DELETE /api/v1/incidents/{id}

Admin only. `204` on success, `403` for a non-admin, `404` on an unknown id.

## asset-service

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/assets` | bearer | List assets, filterable by type |
| GET | `/assets/{id}` | bearer | Read one asset |
| POST | `/assets` | bearer, admin | Register an asset |
| PUT | `/assets/{id}` | bearer, admin | Update an asset |
| DELETE | `/assets/{id}` | bearer, admin | Remove an asset |

Built at build step 6. Paths below are shown without the `/api/v1` prefix.

### POST /api/v1/assets

Admin only. Request:

```json
{
  "name": "core-auth-db",
  "asset_type": "database",
  "criticality": "CRITICAL",
  "owner": "platform-team",
  "location": "eu-west-1"
}
```

`201` with the created asset (id, timestamps added). `403` for a non-admin, `409` when `name` is
already registered, `422` on a missing or out-of-range field.

### GET /api/v1/assets and GET /api/v1/assets/{id}

`200` with an `AssetRead` array or object. The list endpoint accepts an optional `?asset_type=`
filter. `404` on an unknown id. Reading a `CRITICAL` asset emits one `ASSET_ACCESSED` event.

### PUT /api/v1/assets/{id} and DELETE /api/v1/assets/{id}

Admin only. `PUT` carries only the fields being changed and returns `200` with the updated asset;
`DELETE` returns `204`. Both return `403` for a non-admin and `404` on an unknown id.

## Operational endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` on each service port | Liveness plus database reachability. 200 when healthy, 503 when the database is unreachable. Polled by Consul |
| GET | `/health/live` on each service port | Bare liveness, never touches the database. Used by the container `HEALTHCHECK` so a database blip does not restart the process |
| GET | `/metrics` on each service port | Prometheus exposition |

## Example request and response

The submission sheet asks for example requests and responses as screenshots for **one**
microservice. Use `incident-service` — it is the one that shows the gateway, the token, the
correlation ID and the cross-service call in a single exchange. Screenshots go in `docs/evidence/`
and are embedded in `docs/report/deliverable1.md`.
