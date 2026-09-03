# The two microservices patterns

The mark schedule awards 10% for at least two valid patterns, implemented *and* explained, and
states plainly that the API Gateway cannot be counted. The submission sheet goes further: the demo
must show the code or configuration **and** proof the pattern actually works in the application.

This project claims two. Both are chosen because they can be *proven on camera in under ninety
seconds*, which is a real selection criterion when the alternative is a pattern the marker has to
take on trust.

To be completed as each is built — the structure below is the specification for what each section
must contain.

## 1. Database per Service

**What it is.** Each service owns its data store exclusively. No service reads another's tables;
cross-service data moves over HTTP.

**How it is implemented here.** Three separate PostgreSQL containers — `auth-db`, `incident-db`,
`asset-db` — each with its own credentials, reachable only by its owning service. Each service
receives exactly one `DATABASE_URL` and has no knowledge of any other. `incident-service` stores an
`asset_id` and a snapshot of the asset name, never a foreign key into `asset_db`.

**Where the code is.** `deploy/docker-compose.yml` (the three database services and the single
credential each service receives); each service's `app/repositories/`.

**Why it improves loose coupling and independent deployment.** The specification asks for this
explanation directly. A schema change in `asset-db` cannot break `incident-service`, because
`incident-service` has never seen that schema — it sees a JSON contract. Either service can be
redeployed, or its database migrated, without coordinating with the other.

**How the demo proves it.** Two pieces of evidence, one negative and one positive. First,
`docker compose ps` shows three database containers; connect to `incident-db` and list its tables —
there is no asset table, and the absence is the proof that no cross-schema read is possible. Second,
`docker compose stop asset-db`: `asset-service` degrades, while `auth-service` and
`incident-service` keep serving normally. One service's data store failing does not take the system
down, which is the independent deployment and fault isolation the pattern buys.

**Filled in at build steps 6, 7 and 9.**

## 2. Circuit Breaker with Retry

**What it is.** A caller wraps a remote dependency. Transient failures are retried with backoff.
When failures pass a threshold, the breaker opens and subsequent calls return a fallback immediately
without touching the network, until a cooldown lets a trial call through.

**How it is implemented here.** `incident-service` needs `asset-service` when an incident names an
asset. That call goes through `libs/common/http_client.py` and nowhere else. Retry uses `tenacity`
with exponential backoff for connection errors and 5xx responses; the breaker uses `pybreaker` with
a failure threshold and a reset timeout, both from configuration. The declared fallback returns an
`AssetSummary` marked `available=False`, so the incident is still created — degraded, not failed —
and the incident record carries the fact that the asset could not be verified.

**Where the code is.** `libs/common/http_client.py`; the fallback and the only call site in
`services/incident-service/app/services/asset_gateway.py`.

**Why it matters.** Without it, `asset-service` going down turns every incident creation into a
hung request and then a 500, and the failure propagates to the client — one service's outage
becomes the system's outage. This is the fault isolation the non-functional requirements ask for.

**How the demo proves it.** `docker compose stop asset-service`, then create an incident from the
client. The first attempt retries visibly and returns the degraded response; the next few return
instantly, and `CIRCUIT_OPENED` appears in the log. Restart the service, wait out the reset timeout,
and `CIRCUIT_CLOSED` appears. Fast responses after a slow one is the observable signature of an open
breaker, and it is worth saying that out loud on camera.

**Filled in at build step 8.**

## Implemented but not claimed

Health checks, centralised structured logging, and application metrics are all built (see
`observability/`). They are supporting observability and are discussed in the report, but the two
patterns claimed for the 10% are the two above — a claim the marker can verify beats a longer list
they cannot.
