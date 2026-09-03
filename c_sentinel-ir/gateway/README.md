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

The signing key is *not* in `kong.yml`; it is the placeholder `__JWT_SECRET__`, filled in at
container start by `deploy/kong-entrypoint.sh`. See D-20 — the two forms that look like they should
do this instead (`${{ env ... }}` and a `{vault://env/...}` reference) both fail silently on
Kong 3.7, leaving a gateway that starts healthy and rejects every valid token.

## What `kong.yml` must contain

**Services and routes** — three upstream services resolved by their Consul-registered Docker DNS
names, each with a route:

| Kong route | Path | Upstream | Protection |
|------------|------|----------|------------|
| `auth-login` | `/api/v1/auth/login`, `POST` only | auth-service:8001 | Public |
| `auth-protected` | `/api/v1/auth` prefix | auth-service:8001 | JWT required |
| `incidents` | `/api/v1/incidents` prefix | incident-service:8002 | JWT required |
| `assets` | `/api/v1/assets` prefix | asset-service:8003 | JWT required |

auth-service is one Kong *service* with two *routes* because a plugin attaches to a route, and login
is the one endpoint that cannot require a token (D-21). Kong's longest-prefix match picks
`auth-login` ahead of `auth-protected`. `strip_path: false` everywhere: the services already mount
their routers under `/api/v1/...`, so the path is passed through unchanged.

**Plugins**

| Plugin | Why it is here |
|--------|----------------|
| `jwt` | Validates the HS256 token issued by auth-service at the edge, so a request without a valid token never reaches a domain service. A 401 raised *at the gateway* is the demo evidence that the gateway is doing work |
| `rate-limiting` | Global, 60/minute, `policy: local`. Global rather than per-consumer so it also covers the unauthenticated login route, which is where a brute-force attempt lands and what Phase 2's Rule 3 must see (D-22). Exceeding it returns 429. The counter is per Kong node and resets when the container restarts, which is correct for a single-node demo stack |
| `correlation-id` | Stamps `X-Correlation-ID` on every request and echoes it on the response, which is what threads one workflow through three services' logs |
| `file-log` or `http-log` | *Not yet configured.* Gateway-level request logging into the shared event stream; the gateway is one of the four required event sources in Phase 2. Kong's proxy access log currently goes to stdout and is collected by Docker alongside the services' JSON logs, which satisfies Phase 1; the structured log plugin lands with the Phase 2 collector at step 14 |

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

## Verification (build step 10)

Run against `kong:3.7` with the three upstreams stubbed, using a token minted by
`token_service.issue_token` — the project's own issuer, not a hand-made JWT:

| Check | Result |
|-------|--------|
| `/incidents`, `/assets`, `/auth/verify`, `/auth/users` with no token | `401` from Kong |
| The same routes with a valid token | reach the upstream |
| A token with one character altered | `401` |
| `POST /auth/login` with no token | reaches the upstream, not `401` |
| Response header `X-Correlation-ID` | present on every response |
| A client-supplied `X-Correlation-ID` | echoed back unchanged |
| A 90-request authenticated burst | 61 pass, 29 return `429` |

The end-to-end repeat of this against the live services, with the upstream log shown silent for the
401, is `tests/integration/test_gateway_enforcement.py` at build step 12.
