# The operator console

The console is one browser interface over the whole of Sentinel-IR. Every Phase 1 business
operation and every Phase 2 security stage can be driven from it: incidents, assets and users;
the security event stream; detection and alert triage; the Neo4j knowledge graph and its five
queries; GraphRAG answers with their evidence; the project's own demo and evidence scripts; and a
trace of every gateway call with its correlation ID.

It adds no new business logic. Each screen calls code the project already has (the gateway, the
SOC modules, the graph loader, the retriever) the same way that code's own CLI or client calls it.
So what the console shows is what the system does.

![Overview](evidence/console/01-overview.png)

## Running it

```bat
console.bat
```

or, from `c_sentinel-ir/` in any shell:

```bash
python -m console.main          # http://127.0.0.1:8010
```

The console needs only the `.venv` that `setup.bat` builds. How much works depends on what else
is running:

| Running | What works |
|---------|-----------|
| The console only | Security events, detection and alert triage, the rule catalogue and a dry-run graph load, all against the committed attack capture `docs/evidence/step15-attack-events.jsonl`; the offline Operations actions |
| Plus the stack (`start.bat`) | All of the above, plus Incidents, Assets, Users, the live event source, the knowledge graph, GraphRAG, and every Operations action |

Sign in with the bootstrap admin from `deploy/.env` (`BOOTSTRAP_ADMIN_USERNAME`, normally `admin`,
and `BOOTSTRAP_ADMIN_PASSWORD`). The token is kept in the tab's `sessionStorage` and is gone when
the tab closes.

## Architecture

```
 Browser  (console/static: index.html, app.css, app.js)
    │  same origin, http://127.0.0.1:8010
    ▼
 console.main  (FastAPI, bound to 127.0.0.1 only)
    ├── gateway_proxy  /gateway/api/v1/*  ──HTTP──▶  Kong :8000 ──▶ auth / incident / asset services
    ├── stack_status   /console/api/status ──HTTP──▶  each service /health, Consul, Prometheus,
    │                                                  Grafana, Neo4j
    ├── soc_api        /console/api/soc/*   ──in-process──▶ soc.collector, soc.rules, AlertStore
    ├── alert router   /api/v1/alerts       (soc.alert_service.router, mounted unchanged)
    ├── graph_api      /console/api/graph/* ──in-process──▶ kg.cypher, kg.loader, rag ──Bolt──▶ Neo4j
    └── actions        /console/api/actions/* ──subprocess──▶ scripts/*.py, client/*.py, pytest
```

| File | Responsibility |
|------|----------------|
| `console/main.py` | Entry point. Shared logging and error handlers, mounts every router and the static UI. No logic |
| `console/settings.py` | Every address the console talks to, read from the environment with the stack's host ports as defaults; loads `deploy/.env`; puts Docker Desktop's CLI on `PATH` the way `start.bat` does |
| `console/gateway_proxy.py` | Relays the browser's business calls to Kong unchanged, returning status, body, `X-Correlation-ID` and the rate-limit headers |
| `console/stack_status.py` | Parallel health probes for the Overview screen; the Neo4j Bolt check every graph call makes first; the tool links |
| `console/soc_api.py` | Event explorer with facets, rule catalogue, detection runs, and resolving an alert's `relatedEvents` back to full events |
| `console/graph_api.py` | The five queries with their Cypher, node counts per label, graph reload, the graph's alert ids, and GraphRAG questions |
| `console/actions.py` | The fixed catalogue of runnable scripts and the runner |
| `console/static/` | The single-page UI: plain HTML, CSS and JavaScript, no framework and no build step |
| `console/tests/test_console.py` | The console's HTTP contract, with no containers running |
| `console.bat` | Launcher: checks the venv, starts the server, opens the browser |

## Screens and the features they reach

| Screen | What you can do | Project code it reaches |
|--------|-----------------|-------------------------|
| **Overview** | Health of all eight components; open incidents, assets, open alerts and captured events; the security workflow; links to Grafana, Prometheus, Consul, Neo4j Browser and each service's OpenAPI page | Each component's health endpoint; the gateway |
| **Incidents** | List, filter by status and severity, and search. Raise an incident against an asset, edit it, move its status, change its severity, and delete it (admin) | `incident-service` through Kong, which calls `asset-service` through `ResilientClient` |
| **Assets** | List, filter by type, and search. Open an asset to see the incidents raised against it. Register, edit and remove assets (admin) | `asset-service` through Kong. Opening a CRITICAL asset emits `ASSET_ACCESSED` |
| **Users** | List accounts and create users (admin) | `auth-service` through Kong |
| **Security events** | Browse the event stream from the captured attack or the live stack logs. Filter by type, service, user and correlation ID. Click a correlation ID to see every event in that request | `soc.collector` (`build_store`, `select_source`) |
| **Detection & alerts** | Run all rules; read the rule catalogue; move each alert from OPEN to ACKNOWLEDGED to CLOSED; see the events behind an alert; jump to GraphRAG about it | `soc.rules.catalogue`, `soc.rules.main.persist_alerts`, `soc.alert_service.router` |
| **Knowledge graph** | Node and relationship counts; reload the graph (dry run optional); run q1 to q5 with parameter pickers and see each query's Cypher | `kg.loader.main`, `kg.cypher.queries`, `kg.loader.connection.run_query` |
| **Ask GraphRAG** | Ask a question, or pick a suggestion built from real graph ids; optional LLM phrasing; see the answer with all four evidence parts, the Cypher and the CLI rendering | `rag.generation.main.answer_question` |
| **Operations** | Run the project's scripts and read their output: verify, seed, business workflow, failed-login burst, circuit-breaker drill, evidence captures, the Phase 2 workflow, and the unit tests suite by suite | `scripts/`, `client/`, `pytest` |
| **Request trace** | Every gateway call this session made, with status, latency, remaining rate limit and correlation ID. Copy the ID, or look it up in the live events | The headers `gw()` records |

![Incident detail](evidence/console/02-incident-sheet.png)
![Detection and alerts](evidence/console/04-detection-alerts.png)
![Ask GraphRAG](evidence/console/06-ask-graphrag.png)

## Design decisions

**Business calls go through Kong, never to a service port.** The browser cannot call `:8000`
from `:8010` without CORS, so the console relays the calls instead of bypassing the gateway. As a
result JWT validation, rate limiting and correlation-ID stamping all still apply, and every click
lands on the security event stream exactly as a `client/api_client.py` call would.

**The UI chooses the correlation ID.** `gw()` sends a fresh UUID as `X-Correlation-ID` on every
call. Kong passes a client-chosen ID through unchanged, so the ID in the Request trace is the one
all three services logged. That is what makes the trace-to-events lookup work.

**The alert service's router is mounted unchanged.** The console and `/api/v1/alerts` share one
in-process `AlertStore`. The alerts a detection run stores are therefore served and updated by
the alert service's own, already-tested endpoints, not by a second copy of them.

**A detection re-run replaces the alerts.** `new_alert_id()` mints a random ID per firing, so
evaluating the same events twice would hold every alert twice. `AlertStore` gained `clear()` for
this, with its own test; the console clears the store before persisting a new evaluation.

**Two event sources, chosen per screen.** "Captured attack" is the committed capture and needs no
Docker. "Live stack logs" is `docker compose logs`. Both resolve through
`soc.collector.main.select_source`, the function the CLIs use, so the console cannot read events
differently from them.

**A missing graph fails fast.** Every graph call first checks that Neo4j's Bolt port accepts a
connection and returns a plain 503 within a second if not, instead of waiting out the driver's
connection timeout.

**The Operations screen can only run what is written down.** The browser picks an action by ID
and can pass no arguments. Anything outside `ACTIONS` is a 404, and the server binds to
`127.0.0.1` only. The unit-test action runs each suite separately, per decision D-13.

**Plain Material Design, no framework.** Material 3 colour roles are CSS custom properties on
`:root`, redefined for dark mode, and components follow Material's own names: navigation drawer,
top app bar, cards, chips, segmented buttons, data tables, dialogs, side sheets, snackbars. There
is nothing to install or build, and the UI matches the project's no-hidden-state reproducibility
contract.

**Errors keep one shape.** The console installs the shared `install_error_handlers`, so its own
failures use the same `{error, message, details}` body as the services, and the UI shows the
message.

## How it was built

1. **Survey.** Read the README, `docs/api.md`, `gateway/kong.yml`, `deploy/docker-compose.yml`,
   and each Phase 2 entry point (`soc.collector.main`, `soc.rules.main`, the alert service,
   `kg.cypher.graph_service`, `kg.loader.main`, `rag.generation.main`) to list every feature and
   the function that owns it. The schemas fixed the form values: severities, incident statuses
   `OPEN`/`TRIAGED`/`RESOLVED`, alert statuses, and roles.
2. **Design.** Decided on a backend that only delegates, and on the four integration routes:
   proxy to Kong, in-process modules, the mounted alert router, and a subprocess for scripts.
3. **Backend.** Wrote the modules above, then tested every endpoint in-process with FastAPI's
   `TestClient`: rules, events, detection, alert status changes, cited events, dry-run load, query
   catalogue, status, the action 404, and the gateway proxy.
4. **Live check.** The stack was running, so the same calls were repeated against it: 8 of 8
   components up, the graph at 65 nodes and 130 relationships, and the step-19 question answered
   and grounded.
5. **Frontend.** Wrote `index.html` (the frame), `app.css` (tokens and components) and `app.js`
   (helpers, HTTP, overlays, session, one render function per screen, routing).
6. **Browser verification.** A small script drove headless Chrome over the DevTools protocol. It
   signed in, visited every screen, took screenshots, flagged horizontal overflow and collected JS
   errors. It also exercised the incident flow end to end (create through the dialog, escalate in
   the side sheet, delete, confirm gone, so no test data was left behind), ran q4, asked the demo
   question, and repeated the tour at phone width in dark mode.
7. **Fixes found by step 6.**
   - The menu button showed on desktop (a later `.icon-btn` rule overrode `.menu-btn`).
   - A query result could be written after you had left the screen (now guarded with
     `isConnected`).
   - Alert IDs wrapped, and incidents listed oldest first.
   - The scripts could not find `docker` because Docker Desktop was not on `PATH`.
   - The unit-test action ran one root `pytest` against D-13.
8. **Tests and documentation.** Added `console/tests/test_console.py`, the `AlertStore.clear`
   test, `console` in `pytest.ini`, `console.bat`, and this document.

## Verification

```bash
python -m pytest console       # 10 passed, no containers needed
python -m pytest soc           # 95 passed, including AlertStore.clear
```

On the running stack, the Operations screen's *Verify the stack* returned "Preflight: all green",
and the live event source read the stack's events, including the `INCIDENT_CREATED` and
`INCIDENT_ESCALATED` emitted by the console's own test incident. The screenshots in
`evidence/console/` were taken from the console against the live stack.

## Known limits

- Alerts live in memory, like the alert service's. Restarting the console empties them; run
  detection again.
- The graph loader raises its own alerts with their own IDs, so a console detection run and the
  graph hold different alert IDs for the same firings. The GraphRAG suggestions and the q4 picker
  therefore read IDs from the graph, and "Ask GraphRAG about this kind of alert" looks up the
  graph's alert from the same rule.
- Roboto and the Material Symbols icons load from Google Fonts. Offline, the text falls back to
  the system font and icons show as their names.
- An Operations action runs to completion before its output appears, up to 300 seconds. The
  circuit-breaker drill asks for confirmation because it stops `asset-service`.
- *Phrase with LLM* needs `GEMINI_API_KEY`. Without it the template generator answers, as it does
  on the CLI.

## Extending it

- **A new screen:** write `renderX(el)` in `app.js`, register it in `ROUTES`, and add a
  `nav-item` in `index.html`. Business calls go through `gw()`; console calls through `api()`.
- **A new backend capability:** add a router module under `console/` that delegates to the
  owning package, and include it in `console/main.py` before the static mount.
- **A new script:** add an `Action` to `ACTIONS` in `console/actions.py`. Nothing else needs to
  change.
