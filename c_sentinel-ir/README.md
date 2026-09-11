# C_Sentinel-IR — Cybersecurity Incident Reporting Platform

**Project:** ITRI623 Project 2026 — Microservices Application (Phase 1) and Knowledge Graph + RAG (Phase 2)
**Author:** Colile Sibanda (56543115) · North-West University, 2026

Sentinel-IR is a containerised microservices system for reporting and triaging cybersecurity
incidents. Analysts authenticate through an auth service, raise incidents against organisational
assets, and every request that crosses the system emits a structured security event carrying a
correlation ID. Phase 2 consumes that event stream: detection rules raise alerts, the alerts and the
application topology are loaded into a Neo4j knowledge graph alongside MITRE ATT&CK threat
knowledge, and a GraphRAG interface answers natural-language security questions with the graph
evidence attached.

The domain was chosen deliberately. In an incident-reporting system the business events *are*
security events, so the Phase 1 data model already produces what the Phase 2 SOC layer needs — no
retrofit, no restructuring.

## What it does

- Routes every client request through a Kong API Gateway that terminates JWT auth, applies rate
  limiting, and stamps a correlation ID onto the request.
- Runs three independently deployable domain services (auth, incident, asset), each owning its own
  PostgreSQL database, discoverable through Consul.
- Emits a canonical structured security event on every request, auth decision, and inter-service
  call, in the exact schema the Phase 2 specification requires.
- Protects the incident to asset dependency with a retry plus circuit breaker so a failing asset
  service degrades the response instead of cascading.
- Exposes Prometheus metrics and health endpoints from every service, scraped and graphed centrally.
- (Phase 2) Detects threats from the event stream, raises alerts, projects everything into Neo4j,
  and answers questions over the graph with cited evidence.

## Layout

| Path | Purpose |
|------|---------|
| `client/` | Minimal demo client that drives the full business workflow |
| `gateway/` | Kong declarative configuration — routes, JWT, rate limiting, correlation ID |
| `registry/` | Consul service registry configuration and per-service registration |
| `libs/common/` | Shared library: config, structured logging, event schema, JWT, resilient HTTP client |
| `services/auth-service/` | Users, login, JWT issue and verify, failed-login events |
| `services/incident-service/` | Incident CRUD, severity workflow, calls asset service |
| `services/asset-service/` | Asset register, criticality, ownership |
| `observability/` | Prometheus, Grafana, and the centralised logging configuration |
| `soc/` | **Phase 2** — event collector, detection rules, alert service |
| `kg/` | **Phase 2** — Neo4j graph model, Cypher, loaders |
| `rag/` | **Phase 2** — graph retrieval and grounded answer generation |
| `deploy/` | `docker-compose.yml`, Dockerfiles, environment configuration |
| `docs/` | Build order, API documentation, architecture, patterns, report, demo evidence |
| `tests/` | Cross-service contract and integration tests |
| `scripts/` | Seeding, demo-workflow, and evidence-capture scripts |
| `data/seed/` | Seed data that makes the demo workflow meaningful |

## Quick start (once built)

```bash
cp deploy/.env.example deploy/.env
docker compose -f deploy/docker-compose.yml up --build -d
docker compose -f deploy/docker-compose.yml ps        # every service healthy
export $(grep -E '^BOOTSTRAP_ADMIN' deploy/.env | xargs)   # seed_data.py and demo_workflow.py
python scripts/seed_data.py                            #   read these from the environment
python client/demo_workflow.py                         # login -> raise incident -> link asset
open http://localhost:8500                             # Consul: registered instances
open http://localhost:3901                             # Grafana: request and auth metrics
```

On Windows, `setup.bat` / `start.bat --seed` / `stop.bat` (repository root) are a quick alternative
that runs the same steps end to end and prints the generated admin, Grafana and Neo4j login at the
end of their output — a faster path to the same result, not a replacement for the commands above.

Run the tests:

```bash
python -m pytest                                       # unit tests, no containers needed
python -m pytest tests/integration -m integration      # requires the stack to be up
```

## Reproducibility contract

Every demonstrated result is reproducible from three things: the committed
`deploy/docker-compose.yml`, the pinned `requirements.txt`, and the commit hash. Service
configuration comes only from environment variables declared in `deploy/.env.example` — no hidden
local state, no manually created database rows. `scripts/seed_data.py` is the single source of demo
data, and `client/demo_workflow.py` reproduces the marked workflow end to end in one command.

## License

All rights reserved. This repository is public for viewing and assessment purposes only —
see [LICENSE](../LICENSE) at the repository root. No permission is granted to reuse, copy, or
redistribute this code without the author's written permission.
