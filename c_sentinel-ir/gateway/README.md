# gateway/

The Kong API Gateway configuration — the single entry point for every client request, on
`localhost:8000`. Twenty percent of the Deliverable 1 mark rests on this folder, and the submission
sheet is specific: the marker wants evidence the gateway is *being used*, read off the endpoint
addresses as requests execute, not merely that it was configured.

Kong runs DB-less: the whole configuration is this declarative file, versioned in git, which is
exactly what makes it demonstrable.

## Planned files

| File | Responsibility |
|------|----------------|
| `kong.yml` | The declarative configuration: services, routes, plugins, consumers. The single source of gateway truth |
| `README.md` | This specification |

## What `kong.yml` must contain

**Services and routes** — three upstream services resolved by their Consul-registered Docker DNS
names, each with a route:

| Route | Upstream | Protection |
|-------|----------|------------|
| `/api/v1/auth/login` | auth-service | Public |
| `/api/v1/auth/*` | auth-service | JWT required |
| `/api/v1/incidents*` | incident-service | JWT required |
| `/api/v1/assets*` | asset-service | JWT required |

**Plugins**

| Plugin | Why it is here |
|--------|----------------|
| `jwt` | Validates the HS256 token issued by auth-service at the edge, so a request without a valid token never reaches a domain service. A 401 raised *at the gateway* is the demo evidence that the gateway is doing work |
| `rate-limiting` | A per-consumer limit. Exceeding it returns 429 — and produces the abnormal-request-rate signal Phase 2's Rule 3 detects |
| `correlation-id` | Stamps `X-Correlation-ID` on every request and echoes it on the response, which is what threads one workflow through three services' logs |
| `file-log` or `http-log` | Gateway-level request logging into the shared event stream. The gateway is one of the four required event sources in Phase 2 |

## Integration

Sits between `client/` and `services/`. Reads nothing from the services; the services do not know it
exists beyond honouring the correlation-ID header. The JWT secret is shared with `auth-service`
through `deploy/.env` — the gateway validates tokens it did not issue.

Configured in `deploy/docker-compose.yml` as a container mounting this file read-only, so a change
here needs only a container restart, never a rebuild.

Done when: every endpoint in `docs/api.md` answers on `localhost:8000`; an unauthenticated request
to a protected route returns 401 without the upstream service being touched (its log stays silent);
exceeding the rate limit returns 429; and the correlation ID on the response matches the one in all
three services' logs.
