# Demo script — Deliverable 1

Target: **8-10 minutes**, camera on at the start and end, following the submission sheet's mandated
order exactly (`docs/report/README.md`). Rehearse once against a freshly built stack before
recording — do not fix problems live.

## Before recording

```bash
cd c_sentinel-ir
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps        # everything healthy
python scripts/verify_stack.py                        # preflight, all green
python scripts/seed_data.py                            # 2 analysts, 6 assets
```

Have open and ready to switch to: a terminal in `c_sentinel-ir/`, a browser tab on
`http://localhost:8500` (Consul), a browser tab on `http://localhost:3000` (Grafana), and
`gateway/kong.yml` in an editor.

## 0:00–0:30 — Identification

Camera on. State name and student number out loud: "Colile Sibanda, student number 56543115,
ITRI623, Sentinel-IR, Deliverable 1." Camera off for the rest of the recording (screen only).

## 0:30–3:00 — One complete business workflow (criterion 2, 25%)

```bash
python client/demo_workflow.py
```

Narrate each of the five steps as it prints: login through the gateway, list assets, create an
incident against `core-auth-db` with a snapshotted asset name, read it back, escalate its severity
to HIGH. Point out the correlation ID printed at the top and that it reappears in every step's
output — this is the same ID that will be found in all three services' logs at minute 8.

## 3:00–4:30 — API Gateway: configuration and live routing (criterion 3, 20%)

Open `gateway/kong.yml`; scroll to the `auth-public` / `auth-protected` route split and explain it
in one sentence (login must be reachable without a token, everything else must not). Then, live:

```bash
curl -i http://localhost:8000/api/v1/incidents                 # no token -> 401, from Kong
curl -i http://localhost:8000/api/v1/auth/login -d '{"username":"admin","password":"WRONG"}' -H "Content-Type: application/json"
# /api/v1/health has no Kong route, and a sequential loop is too slow to land
# 65 requests inside one 60s rate-limit window - fire them concurrently
# against a route that exists instead, so the tail actually turns 429:
for i in $(seq 1 65); do curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8000/api/v1/auth/login -d '{"username":"admin","password":"WRONG"}' -H "Content-Type: application/json" & done; wait
```

Call out that every response carries `X-Correlation-ID` and the `RateLimit-*` headers — read one off
the terminal — as the "evidence from the endpoint addresses" the sheet asks for.

## 4:30–5:30 — Service registry (criterion 4, 10%)

Switch to the Consul UI tab, `localhost:8500`. Show all three services registered with their real
addresses and passing health checks. Then:

```bash
docker compose -f deploy/docker-compose.yml stop asset-service
```

Refresh Consul — the instance leaves the healthy list within the health-check interval. Restart it
before continuing:

```bash
docker compose -f deploy/docker-compose.yml start asset-service
```

## 5:30–6:15 — Docker hosts the services (criterion 5, 15%)

```bash
docker compose -f deploy/docker-compose.yml ps
docker images | grep sentinel
```

Point out ten separate containers and three separately built service images, each with its own
lifecycle — say out loud that this is what "independently containerised" means, not just
"containerised."

## 6:15–8:15 — The two patterns, proven live (criterion 6, 10%)

**Database per Service.** Open `docs/patterns.md` section 1 on screen for ten seconds, then:

```bash
docker exec -it $(docker compose -f deploy/docker-compose.yml ps -q incident-db) psql -U incident_user -d incident_db -c '\dt'
```

Point out there is no `assets` table — the absence is the proof. Then show `asset-db` failing
without taking the other two services down:

```bash
docker compose -f deploy/docker-compose.yml stop asset-db
curl -s http://localhost:8000/api/v1/health   # incident-service and auth-service still fine
docker compose -f deploy/docker-compose.yml start asset-db
```

**Circuit Breaker with Retry.** Open `docs/patterns.md` section 2's three numbered points on screen
for a few seconds (retry nested inside the breaker; only transient faults count; the client is
long-lived), then run the on-camera proof:

```bash
python scripts/break_asset_service.py
```

Narrate as it runs: the first attempts are slow (retrying a dead dependency), the incident still
succeeds with a degraded asset summary rather than a 500, then responses go near-instant once the
breaker opens, then `CIRCUIT_CLOSED` appears once `asset-service` is restarted and the reset timeout
elapses.

## 8:15–9:15 — Security event collection (criterion 7 / criterion 1, 5% + part of 15%)

```bash
cat docs/evidence/step12-correlated-logs.jsonl | grep <the workflow's correlation ID>
```

Show the same correlation ID appearing in `auth-service`, `incident-service` and `asset-service`
events for the one workflow run at minute 1. Open `docs/soc-events.md` briefly and name the fields
out loud (`eventId`, `eventType`, `severity`, `correlationId`, `affectedEntity`) and state in one
sentence that this schema was designed against the Phase 2 specification so the SOC collector due
next needs no translation layer.

## 9:15–9:45 — Close

Switch to the Grafana tab (`localhost:3000`) for five seconds to show the request/auth-failure
dashboard rendering real data from the run just performed, then stop recording.

## Timing budget

| Segment | Minutes |
|---|---|
| Identification | 0.5 |
| Business workflow | 2.5 |
| Gateway | 1.5 |
| Registry | 1.0 |
| Docker | 0.75 |
| Patterns | 2.0 |
| Security events | 1.0 |
| Close | 0.5 |
| **Total** | **9.75** |

Trim the gateway or registry segment first if a rehearsal runs long — the workflow and patterns
segments are the two the mark schedule weights heaviest and should never be cut.
