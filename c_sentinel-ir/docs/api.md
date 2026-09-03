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
- All responses are JSON objects. Errors use one shape: `{"error": {"code": ..., "message": ...,
  "field": ...}}`.
- Every request may carry `X-Correlation-ID`; every response returns one.
- Protected endpoints require `Authorization: Bearer <jwt>`.

## auth-service

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | public | Exchange credentials for a JWT |
| GET | `/auth/verify` | bearer | Validate the current token and return its claims |
| POST | `/auth/users` | bearer, admin | Create a user |
| GET | `/auth/users` | bearer, admin | List users |

## incident-service

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/incidents` | bearer | List incidents, filterable by status and severity |
| GET | `/incidents/{id}` | bearer | Read one incident |
| POST | `/incidents` | bearer | Raise an incident against an asset |
| PUT | `/incidents/{id}` | bearer | Update an incident |
| PATCH | `/incidents/{id}/severity` | bearer | Change severity — emits an escalation event |
| DELETE | `/incidents/{id}` | bearer, admin | Delete an incident |

## asset-service

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/assets` | bearer | List assets, filterable by type |
| GET | `/assets/{id}` | bearer | Read one asset |
| POST | `/assets` | bearer, admin | Register an asset |
| PUT | `/assets/{id}` | bearer, admin | Update an asset |
| DELETE | `/assets/{id}` | bearer, admin | Remove an asset |

## Operational endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` on each service port | Liveness plus database reachability. Polled by Consul |
| GET | `/metrics` on each service port | Prometheus exposition |

## Example request and response

The submission sheet asks for example requests and responses as screenshots for **one**
microservice. Use `incident-service` — it is the one that shows the gateway, the token, the
correlation ID and the cross-service call in a single exchange. Screenshots go in `docs/evidence/`
and are embedded in `docs/report/deliverable1.md`.
