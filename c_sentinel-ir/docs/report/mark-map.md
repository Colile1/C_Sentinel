# Mark map — Deliverable 1

Every criterion on the submission sheet's mark schedule, mapped to the artefact that earns it, the
build step that produces it, and the demo moment that shows it. Filled in at build step 13 and used
as the last check before uploading. **A row with an empty column is a mark not yet earned.**

| # | Criterion | Weight | Artefact | Build step | Shown in the demo at |
|---|-----------|--------|----------|-----------|----------------------|
| 1 | Documentation — APIs simple, consistent, useful and well documented; architecture diagram correct | 15% | `docs/api.md`, `docs/architecture.md`, `docs/diagrams/`, `docs/report/deliverable1.md` (cover: Colile Sibanda, 56543115) | 13 | Opened by the marker alongside the demo; referred to throughout |
| 2 | Functional application — executes the required business functionality from a very basic client | 25% | `client/demo_workflow.py`, the three services | 5, 6, 7, 12 | Step 2 of the demo order — one complete workflow, start to finish |
| 3 | API Gateway — correctly routes traffic, relevant configuration | 20% | `gateway/kong.yml` | 10 | Step 3 — the config on screen, then live routing read off endpoint addresses |
| 4 | Service registry / discovery — services registered or discoverable, approach explained | 10% | `registry/consul-config.json`, `libs/common/registry.py`, `registry/README.md` | 4 | Step 4 — the Consul UI showing instances and addresses; stop a service and watch it leave |
| 5 | Deployment — services independently containerised | 15% | `deploy/docker-compose.yml`, `deploy/Dockerfile.service` | 9 | Step 5 — `docker compose ps`, then `docker images` |
| 6 | Microservices patterns — at least two valid patterns implemented and explained (not the gateway) | 10% | `docs/patterns.md`; `libs/common/http_client.py`; three database containers | 6, 7, 8, 9 | Step 6 — `incident-db` has no asset table; `scripts/break_asset_service.py` opens the breaker live |
| 7 | Preparation for SOC / knowledge graph — design produces useful data | 5% | `docs/soc-events.md`, `libs/common/events.py` | 3 | Step 7 — the event schema, then a real correlated event trail from the workflow just run |

## Submission items

| Item | Where it comes from | Done |
|------|--------------------|------|
| Code zip — hand-written source and deployment files only | `services/`, `libs/`, `gateway/kong.yml`, `deploy/`, `client/`, `scripts/` | ☑ (`docs/evidence/sentinel-ir-deliverable1-code.zip`, `scripts/build_submission_zip.py`) |
| Document (PDF) | `docs/report/deliverable1.md` | ☑ draft written; export to PDF before upload |
| Demo video, 8-10 minutes | Recorded against `docs/report/demo-script.md` | ☐ not yet recorded |
| All three uploaded to Dropbox | | ☐ |

## The two things most likely to cost marks

1. **Criterion 3.** Showing the gateway configuration is not showing the gateway being *used*. The
   sheet asks for evidence from the endpoint addresses as requests execute. Every demo request must
   visibly go to `localhost:8000`.
2. **Criterion 6.** The sheet asks for proof the patterns *work*, not that they exist. Reading the
   circuit-breaker code earns less than the breaker opening on screen.
