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

Three decisions in that implementation are worth stating, because each is a way the pattern is
commonly got wrong:

1. **Retry nests inside the breaker** — `breaker( retry( one GET ) )`. A request retried three times
   and still failing counts as *one* failure against the threshold, not three. Nested the other way,
   a threshold of three would trip on the retries of a single request and the configured value would
   mean nothing.
2. **Only transient faults are counted.** A connection error, a timeout and a 5xx are the dependency
   faulting. A 404 is a *correct answer from a healthy service*: it propagates unretried and never
   counts, because otherwise one client asking for an id that does not exist would take
   `asset-service` out of service for everyone.
3. **The client is long-lived**, cached per dependency URL in `asset_gateway._client_for`. The
   breaker's failure count *is* the pattern's state; a client rebuilt per call counts to one, never
   reaches its threshold, and never opens — which still passes a happy-path demo while quietly
   losing the mark.

**Where the code is.** `libs/common/http_client.py` (the calling policy) and
`libs/common/circuit_events.py` (the events); the fallback and the only call site in
`services/incident-service/app/services/asset_gateway.py`. Thresholds are the
`retry_*` and `circuit_*` settings in `libs/common/config.py`, read from the environment as
`RETRY_MAX_ATTEMPTS`, `RETRY_BACKOFF_SECONDS`, `CIRCUIT_FAIL_MAX` and `CIRCUIT_RESET_SECONDS`;
step 9 declares them in `deploy/.env.example`.

**Why it matters.** Without it, `asset-service` going down turns every incident creation into a
hung request and then a 500, and the failure propagates to the client — one service's outage
becomes the system's outage. This is the fault isolation the non-functional requirements ask for.

**How the demo proves it.** `docker compose stop asset-service`, then create an incident from the
client. The first attempt retries visibly and returns the degraded response; the next few return
instantly, and `CIRCUIT_OPENED` appears in the log. Restart the service, wait out the reset timeout,
and `CIRCUIT_CLOSED` appears. Fast responses after a slow one is the observable signature of an open
breaker, and it is worth saying that out loud on camera.

That contrast is already captured offline, reproducible without Docker by
`python scripts/capture_breaker_evidence.py`, and committed as
`docs/evidence/step8-circuit-breaker-timings.txt`:

```
Call 1: state=closed, elapsed_ms=53.6, result={'name': 'unknown', 'available': False}
Call 2: state=closed, elapsed_ms=41.6, result={'name': 'unknown', 'available': False}
Call 3: state=open,   elapsed_ms=42.8, result={'name': 'unknown', 'available': False}
Call 4: state=open,   elapsed_ms=0.1,  result={'name': 'unknown', 'available': False}
Call 5: state=open,   elapsed_ms=0.0,  result={'name': 'unknown', 'available': False}
Call 6: state=closed, elapsed_ms=4.1,  result={'id': 1, 'name': 'web-01'}
```

Calls 1–3 are slow because they retry a dependency that is down; call 3 crosses the threshold and
trips the breaker; calls 4 and 5 return in effectively zero milliseconds because no network is
touched; call 6, after the dependency recovers and the reset timeout elapses, is the half-open trial
that closes the breaker. The matching event stream is
`docs/evidence/step8-circuit-breaker-events.jsonl` — three `DEPENDENCY_FAILURE`, one
`CIRCUIT_OPENED`, one `CIRCUIT_CLOSED`. Note there is no `DEPENDENCY_FAILURE` for calls 4 and 5:
those never left the process, and recording them would inflate Phase 2's Rule 4 with calls that
never reached the network.

**Built at step 8.** Proven by `libs/common/tests/test_http_client.py` — 13 tests, including the two
the build order asks for by name (a transient failure retried and then succeeding; consecutive
failures opening the breaker, returning the fallback and logging the state change) and one that
fails if retry is ever nested outside the breaker.

## Implemented but not claimed

Health checks, centralised structured logging, and application metrics are all built (see
`observability/`). They are supporting observability and are discussed in the report, but the two
patterns claimed for the 10% are the two above — a claim the marker can verify beats a longer list
they cannot.
