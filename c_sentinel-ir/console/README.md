# console/

The operator console: one browser interface over every Sentinel-IR feature, from Phase 1
incidents, assets and users to Phase 2 events, detection, the knowledge graph and GraphRAG.

```bat
console.bat                      &rem or: python -m console.main  ->  http://127.0.0.1:8010
```

It owns no business logic. Business calls go through the Kong gateway; the SOC, graph and RAG
screens call the existing packages in-process; the Platform screen reads Consul and drives
`docker compose` for six named containers only; the Operations screen runs the project's own
scripts from a fixed catalogue. The Demo guide walks both demo scripts from inside the console. It binds to `127.0.0.1` only, and like the alert and graph
services it is not on the request path and does not register with Consul (D-30).

| File | Responsibility |
|------|----------------|
| `main.py` | Entry point: shared logging and error handlers, every router, the static UI |
| `settings.py` | Addresses from the environment, `deploy/.env`, Docker Desktop on `PATH` |
| `gateway_proxy.py` | Relays `/gateway/api/v1/*` to Kong unchanged |
| `stack_status.py` | Health probes, the Neo4j Bolt check, tool links |
| `platform_api.py` | Consul registry, containers with stop/start for the services and their databases, per-database tables, gateway probes |
| `soc_api.py` | Events over three sources, rule catalogue, detection runs, an alert's cited events |
| `graph_api.py` | The five queries, graph counts and reload, an alert's neighbourhood, GraphRAG |
| `actions.py` | The runnable script catalogue |
| `static/` | The plain Material Design UI (HTML, CSS and JS, no build step) |
| `tests/` | The HTTP contract, with no containers running |

The design, the screen-to-feature map, how it was built and verified, and its known limits are in
[`docs/console.md`](../docs/console.md).

```bash
python -m pytest console
```
