# Sentinel-IR — Deliverable 1

**Colile Sibanda — Student number 56543115 — ITRI623, North-West University, 2026**

## 1. System functionality

Sentinel-IR is a cybersecurity incident reporting platform built as three containerised
microservices behind a single API gateway. An analyst authenticates against `auth-service` to
receive a JWT, uses it to raise an incident in `incident-service` against a registered asset held
in `asset-service`, and can then track that incident through its severity workflow
(`LOW`→`MEDIUM`→`HIGH`→`CRITICAL`) and lifecycle (`OPEN`→`TRIAGED`→`RESOLVED`). Every request that
enters the system passes through the Kong API Gateway on `localhost:8000`, which authenticates the
token, rate-limits the caller, and stamps a correlation ID onto the request; every service emits a
structured JSON security event for everything security-relevant it does, so the full path of one
analyst's workflow can be reconstructed from the logs by that one correlation ID. The system is
deliberately data-light and behaviour-heavy: its value for this deliverable is in demonstrating a
correctly gated, observable, independently deployable distributed system, not a large domain model.

## 2. API documentation

**Base URL:** `http://localhost:8000/api/v1` — the gateway. Direct service ports (8001-8003) exist
for inspection only. The full endpoint catalogue, conventions, and every request/response shape are
in [`docs/api.md`](../api.md); it is not duplicated here so that one file stays the source of truth.

### Example request and response — incident-service

Chosen because a single exchange here shows the gateway, the bearer token, the correlation ID and
the cross-service call together.

**Request** — `POST http://localhost:8000/api/v1/incidents`, `Authorization: Bearer <jwt>`,
`X-Correlation-ID: corr-332de1db16a547a4`:

```json
{
  "title": "Suspicious login pattern on core-auth-db",
  "description": "Five failed logins for the same account inside one minute.",
  "severity": "MEDIUM",
  "reported_by": "analyst1",
  "asset_id": 1
}
```

**Response** — `201 Created`, `X-Correlation-ID: corr-332de1db16a547a4` echoed back:

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

`asset_name_snapshot` was fetched from `asset-service` at creation time through
`libs/common/http_client.py` — this single field is the evidence, in a live response, of both
marked patterns at once: it exists because the databases are separate (pattern 1) and it was
fetched through the retry/circuit-breaker wrapper (pattern 2). Screenshots of this exchange
executed live (gateway, terminal and Consul side by side) are in `docs/evidence/` and referenced in
the demo script.

## 3. Architecture

See [`docs/architecture.md`](../architecture.md) for the full write-up and
[`docs/diagrams/architecture.svg`](../diagrams/architecture.svg) for the diagram. In summary: a
client reaches the system only through the Kong gateway, which routes to three FastAPI domain
services (`auth-service`, `incident-service`, `asset-service`), each with its own PostgreSQL
database and no visibility into the other two. Services self-register with Consul at startup;
`incident-service` is the one service that calls another service, doing so exclusively through a
retry-plus-circuit-breaker wrapper. Prometheus scrapes all three services' `/metrics`, Grafana
renders that as dashboards, and every service emits JSON security events to stdout, collected by
Docker, in the schema fixed in `docs/soc-events.md`.

## 4. The two patterns

Full detail, including why each design choice was made and how the demo proves each fires, is in
[`docs/patterns.md`](../patterns.md). Summary:

1. **Database per Service.** Three independent PostgreSQL containers (`auth-db`, `incident-db`,
   `asset-db`); each service holds exactly one connection string and never reads another service's
   tables. `incident-service` records `asset_id` and a name snapshot rather than a foreign key, so
   the two services can evolve their schemas independently. Proven by inspecting `incident-db` for
   an absent asset table, and by `asset-db` failing without taking `auth-service` or
   `incident-service` down.
2. **Circuit Breaker with Retry.** `incident-service`'s only call to `asset-service` goes through
   `libs/common/http_client.py`, which nests `tenacity` retry-with-backoff *inside* a `pybreaker`
   circuit breaker, so a single logical request that retries three times counts once against the
   breaker's threshold. An open breaker returns an immediate, documented fallback
   (`AssetSummary(available=False)`) instead of hanging, so a downed dependency degrades incident
   creation rather than failing it. Proven by stopping `asset-service` and watching the breaker
   open (`CIRCUIT_OPENED` in the event log, response times dropping to sub-millisecond) and later
   close again once the dependency returns.

## 5. How security events are collected

Every service imports one shared module, `libs/common/events.py`, and emits every
security-relevant occurrence — successful and failed logins, incident creation and escalation,
asset access, dependency failures, circuit-breaker state changes, unauthorised access and rate
limiting at the gateway — as a single-line JSON object in the schema fixed in
[`docs/soc-events.md`](../soc-events.md): `eventId`, `timestamp`, `serviceName`, `eventType`,
`severity`, `userId`, `sourceIp`, `endpoint`, `httpMethod`, `statusCode`, `message`,
`correlationId`, `affectedEntity`. The schema is enforced, not advisory — an off-schema event is
rejected rather than logged partially. Every request carries `X-Correlation-ID` end to end (minted
by the gateway when absent, echoed when supplied), so the events from one analyst workflow across
all three services can be pulled together by that one ID — demonstrated live in
`docs/evidence/step12-correlated-logs.jsonl`, 17 correlated events across all three services from
one run of `client/demo_workflow.py`. This schema and correlation mechanism were designed against
the Phase 2 specification from the start, specifically so the SOC event collector due in step 14
can consume this exact stream with no translation layer.
