# Architecture

Written up at build step 13.

## The diagram

`docs/diagrams/architecture.svg` (opens in any browser or a recent version of Word/PowerPoint).
It shows the client, Kong, Consul, the three domain services, their three databases, the
Prometheus/Grafana pair, and the JSON security-event pipeline, with the two claimed patterns called
out explicitly in the legend.

The request path the diagram makes obvious:

```
client  ->  Kong (8000)  ->  auth | incident | asset  ->  its own Postgres
              |                        |
              |                   incident -> asset, via retry + circuit breaker
              |
         Consul registry (health, instance addresses)
         Prometheus -> Grafana        Docker logs -> JSON security events
```

## 1. The domain and why microservices suit it

Incident reporting has three genuinely separate concerns with different rates of change and
different sensitivity. Identity (`auth-service`) changes rarely and must be hardened — a password
hash, a JWT secret and a login endpoint have no reason to share a deployment with anything else.
The asset register (`asset-service`) is reference data: assets are created occasionally and read
often, and other teams (Phase 2's knowledge graph) will eventually query it independently of
incidents. Incident handling (`incident-service`) is the highest-churn part of the system — new
severities, new workflow states, new fields — and coupling its schema to the asset register's would
mean every asset-register change forces an incident-service migration, and vice versa. Splitting
along these seams means each can be developed, tested, deployed and scaled on its own schedule,
which is the entire justification for paying the operational cost of a distributed system rather
than shipping one monolith.

## 2. The services and each one's role

- **auth-service** — the identity boundary. Holds the user table, hashes passwords, issues and
  verifies HS256 JWTs. It is the only service that ever sees a plaintext password, and the only one
  whose failures the mark schedule asks to be observable as security events (`AUTH_FAILED`).
- **incident-service** — the domain's core workflow. Owns the incident lifecycle (`OPEN` ->
  `TRIAGED` -> `RESOLVED`) and severity (`LOW`..`CRITICAL`), and is the one service that calls
  another service in the running system — asset-service, to snapshot the asset a new incident names.
  That single cross-service call is deliberately the one place the circuit-breaker pattern lives.
- **asset-service** — the asset register. A CRUD service over the organisation's assets
  (`asset_type`, `criticality`, `owner`, `location`), consulted by incident-service and, in Phase 2,
  by the knowledge-graph loader for topology.

Full endpoint-level detail for each is in `docs/api.md`; the design rationale for each service's own
folder is in that service's `README.md`.

## 3. Endpoint design

Conventions, fixed once at step 5 and held constant afterwards so the API reads as one system rather
than three: nouns in the path, plural (`/incidents`, `/assets`, `/auth/users`); status codes used
consistently (`200`/`201`/`204` for success, `400`/`401`/`403`/`404`/`409`/`422`/`429` for the
specific failure, never a bare `400` for something more specific applies); one error shape
(`{"error", "message", "details"}`) produced in exactly one place per service
(`install_error_handlers`) so a client never has to branch on which service answered. JSON in, JSON
out, everywhere — no service returns HTML or plain text on any path. The full catalogue, with
request and response bodies, is `docs/api.md`.

## 4. The API Gateway

Kong (`gateway/kong.yml`, DB-less/declarative) is the single public entry point on `localhost:8000`.
It routes every `/api/v1/...` path to the owning service, terminates JWT validation for every
protected route (a bad or missing token is rejected *at the gateway*, so an unauthenticated request
never reaches a service process), enforces a 60 requests/minute rate limit, and stamps every
request and response with `X-Correlation-ID` via the correlation plugin. A single entry point
matters more as services multiply because it is the one place authentication, rate limiting and
request tracing can be enforced consistently — without it, each of the three services would need to
reimplement all three, and a missed one becomes a silent hole. (The gateway is not claimed as one of
the two marked patterns — the mark schedule excludes it explicitly — but it is the mechanism that
makes both claimed patterns and the correlation invariant demonstrable from outside the system.)

## 5. Service registry and discovery

Consul is the service registry; the five-step explanation lived first in `registry/README.md` and
is restated here because the demo needs it stated plainly:

1. Each service reads its own name, host and port from its environment at startup and registers
   itself with Consul (`PUT /v1/agent/service/register`), including a health-check definition
   pointing at its own `/health`.
2. Consul polls that `/health` endpoint on an interval; an instance that stops answering is marked
   critical and, after a deregistration timeout, removed from the list.
3. `localhost:8500`'s UI lists every registered instance with its real address and port — this is
   the screen the demo shows for criterion 4.
4. In this deployment, Kong resolves the upstream hostname through Docker Compose's own DNS, not by
   querying Consul directly. Consul is the authoritative record of *which instances exist and
   whether they are healthy*, and the two are named separately here because conflating them would
   misdescribe what actually resolves a request at runtime.
5. On a clean shutdown a service deregisters, and it disappears from the Consul UI within the demo
   — shown immediately after `docker compose stop asset-service` in the pattern-2 demo step, so one
   action produces two pieces of evidence (registry deregistration and breaker opening) back to
   back.

## 6. The two patterns

Summarised from `docs/patterns.md`, which is the section a marker checking criterion 6 should read
in full:

1. **Database per Service** — three separate PostgreSQL containers, one per service, each service
   holding exactly one connection string and no visibility into the other two schemas.
   `incident-service` stores an `asset_id` and a name snapshot rather than a foreign key, so a
   schema change in `asset-db` cannot break it.
2. **Circuit Breaker with Retry** — the only cross-service call in the running system,
   `incident-service` -> `asset-service`, is wrapped by `libs/common/http_client.py`: retry with
   exponential backoff nested *inside* a circuit breaker, so a request retried three times counts as
   one failure against the breaker's threshold, not three. An open breaker returns a documented
   `AssetSummary(available=False)` fallback rather than hanging or raising, so an asset-service
   outage degrades incident creation instead of failing it.

Both were chosen because each can be proven on camera in under ninety seconds — `docker compose stop
asset-db` for the first, `scripts/break_asset_service.py` (or manually stopping `asset-service`) for
the second — rather than argued from source alone.

## 7. Deployment

The container inventory, health checks and startup ordering are specified in full in
`deploy/README.md`; the essentials: `docker compose -f deploy/docker-compose.yml up --build -d`
brings up Consul, Kong, three Postgres containers (`auth-db`, `incident-db`, `asset-db`), the three
FastAPI services, Prometheus and Grafana — ten containers, each independently built and lifecycled.
`depends_on: condition: service_healthy` sequences startup so a service never comes up racing its own
database. Each service's inspection port (8001-8003) is published only to `127.0.0.1`; the only
address a client is meant to use is the gateway's `8000`.

## 8. Observability

Structured JSON logs to stdout, collected by Docker (`libs/common/logging.py`), Prometheus metrics
at `/metrics` on every service (`libs/common/logging.py`'s counters plus FastAPI's own),
Grafana dashboards over that scrape (`observability/`), and the `/health` / `/health/live` split so a
database blip cannot restart a process via the container `HEALTHCHECK`. These are built and shown
in the demo, but the two patterns claimed for the pattern mark are the two in section 6 above — see
`docs/patterns.md`'s closing note for why a shorter, provable claim beats a longer one the marker
has to take on trust.

## 9. Preparation for the SOC and knowledge graph

`docs/soc-events.md` was designed backwards from the Phase 2 specification before any Phase 1
service was written, so Phase 1's output needs no translation to become Phase 2's input. Every
request that crosses the system carries `X-Correlation-ID`, generated by the gateway when a client
does not supply one and echoed unchanged when it does; every security-relevant thing that happens —
a login, a failed login, an incident being raised or escalated, a dependency failure, a circuit
opening or closing — is emitted as one JSON event in the fixed schema, carrying that correlation ID.
The entities that appear in those events (user, service, endpoint, asset, incident) are exactly the
node types the Phase 2 knowledge graph needs, so no event needs remodelling when the SOC collector
(step 14) starts reading this same stream.

## Dependency direction

Acyclic, stated explicitly because the coding rules require it:

```
client  ->  gateway  ->  services  ->  libs/common
                             |
                             +->  its own database
soc  ->  libs/common (event schema only)
kg   ->  soc
rag  ->  kg
```

Nothing points leftward. `libs/common` imports no service. Phase 2 packages read Phase 1 output and
are never imported by it.
