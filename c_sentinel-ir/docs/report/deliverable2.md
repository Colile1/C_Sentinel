# Sentinel-IR — Phase 2: SOC, knowledge graph and GraphRAG

**Colile Sibanda — Student number 56543115 — ITRI623, North-West University, 2026**

## 1. What Phase 2 adds

Phase 1 delivered a working distributed system: three FastAPI microservices behind a Kong gateway,
each with its own database, registered in Consul, deployed by Docker Compose, and emitting a
structured security event for everything security-relevant it does.

Phase 2 treats that system as an operational environment under attack, and adds four layers on top
of it:

1. **`soc/collector`** reads the event stream the services already emit and holds it in a queryable
   store.
2. **`soc/rules`** runs four detection rules over that store and raises alerts.
3. **`soc/alert_service`** stores the alerts and serves them over an API.
4. **`kg/`** loads the application topology, the live events and alerts, and MITRE ATT&CK security
   knowledge into a Neo4j knowledge graph; **`rag/`** answers natural-language security questions
   from that graph, showing the evidence for every answer.

The single most consequential decision was made in Phase 1, not here: **the event schema was fixed
at build step 3 against the Phase 2 specification.** `docs/soc-events.md` names the same thirteen
fields §3.1 asks for, so the collector needed no translation layer, the alert model could reuse the
event model's conventions, and the graph loader could parse every id it was given. A contract test
(`tests/contract/test_event_schema.py`) parses that document and asserts the field names still match
the Pydantic model, so the two cannot drift.

## 2. Architecture

```
   Phase 1                             Phase 2
 ┌───────────────────┐
 │ Kong API Gateway  │──┐
 ├───────────────────┤  │  JSON security events on stdout
 │ auth-service      │──┤  (docs/soc-events.md schema)
 │ incident-service  │──┤
 │ asset-service     │──┘
 └───────────────────┘  │
                        ▼
              ┌──────────────────┐   ┌──────────────┐   ┌────────────────┐
              │ soc/collector    │──▶│ soc/rules    │──▶│ soc/           │
              │ EventStore       │   │ 4 rules      │   │ alert_service  │
              └────────┬─────────┘   └──────┬───────┘   └───────┬────────┘
                       │  events            │  alerts           │
                       └────────────┬───────┴───────────────────┘
                                    ▼
                      ┌───────────────────────────┐      ┌──────────────────────┐
                      │ kg/loader → Neo4j         │◀─────│ MITRE ATT&CK         │
                      │ 12 labels, 18 rel. types  │      │ T1110, T1078, …      │
                      └────────────┬──────────────┘      └──────────────────────┘
                                   │  6 Cypher queries (kg/cypher)
                                   ▼
                      ┌───────────────────────────┐
                      │ rag/retrieval             │  intent → query → rows
                      │ rag/generation            │  template → answer + evidence
                      └───────────────────────────┘
```

Three things about this shape are worth stating, because each was a decision rather than a default:

**The layers are one-directional and each is a pure function of the one before it.** A rule is a
pure function of the event store's contents and an injected clock; a loader is a pure function
returning a list of writes; a retriever shapes rows. Nothing reaches backwards. This is why 598 unit
tests run with no container, no network and no database — the only components that need a server are
the ones that genuinely talk to Neo4j, and those tests are marked `neo4j` and skip cleanly without
one.

**The Phase 2 services deliberately do not register with Consul or own a database** (D-30, D-33).
`soc/alert_service` and `kg/cypher/graph_service` are thin FastAPI applications reusing the shared
logging and error handlers. They are analysis tooling over the domain, not domain services, and
adding a fourth and fifth registered service would have muddled the Phase 1 architecture the marker
is also reading.

**The alert store is in-process** (D-25, D-30). Alerts live for the life of the process that raised
them and are re-derivable from the event stream at any time by re-running the rules. A durable alert
database was not built because nothing in the specification requires alerts to survive a restart,
and the graph is where alerts are persisted meaningfully.

## 3. SOC event collection

`soc/collector/reader.py` takes any iterable of raw log lines — an open file, `sys.stdin`, or the
output of `docker compose logs` — and yields validated `SecurityEvent` objects. Ordinary application
log lines carry no `eventType` and are skipped; a line that *does* carry one but fails the schema
raises `MalformedEventError` rather than being silently dropped. Silently dropping malformed
security events is how a SOC layer comes to under-report an attack.

`soc/collector/store.py` holds them with the queries the rules need: by user, by source IP, by
service, by correlation ID, each with a time window.

**Verified live:** a run against the Phase 1 stack collected **1521 events from 3 services across 10
event types**, including `CIRCUIT_OPENED`, `CIRCUIT_CLOSED` and `DEPENDENCY_FAILURE`, and one
correlation ID's full journey is traceable across all three services
([docs/evidence/step14-collector.txt](../evidence/step14-collector.txt)).

**All four sources are live (D-36).** The specification names four emitters and the collector now
reads all four. The gateway was the last one wired: Kong's default access log is nginx combined
format, which carries no `eventType` and no correlation ID, so the reader correctly skipped it and
gateway events reached the rules only via `--file`. A `file-log` plugin in `gateway/kong.yml` now
renders each *refused* request (401, 403, 429) directly in the event schema onto the same stdout the
services use, so the existing docker source ingests it with **no reader or rule change** — the
source addition this was always scoped as.

**Verified live:** against the running stack, `soc.collector.main` reports **4 distinct services**
(was 3) and `RATE_LIMIT_EXCEEDED` / `UNAUTHORISED_ACCESS` now appear among the collected event
types. Driving three unauthorised probes and a 70-request burst through the gateway, the rules raise
*Unauthorised Endpoint Access* at **HIGH** (the probes include the privileged `/api/v1/auth/users`)
and *Abnormal Request Rate* on **both** of its signals at once — from genuine gateway events, not a
capture. Permitted traffic emits nothing at the gateway, because the upstream service already logs
it and a second copy would double-count Rule 3's volume signal.

**Service health is a fifth source.** A service that has stopped answering cannot log that it is
unhealthy, so its own stream goes quiet exactly when it matters. `soc/collector/health.py` asks
Consul — which already polls every service's `/health` — for critical checks, and turns each into a
`HEALTH_CHECK_FAILED` event on the same schema, named for the failing service. The live source adds
these automatically. **Verified live:** with `asset-service` stopped, the collector reports
`HEALTH_CHECK_FAILED` among its event types and Rule 4 raises *"asset-service is failing: its health
check is failing"*.

## 4. Detection rules

Four rules, documented in full in [detection-rules.md](detection-rules.md): Multiple Failed Logins,
Unauthorised Endpoint Access, Abnormal Request Rate, and Service Failure. The specification requires
three; the fourth was built because the Phase 1 circuit breaker already emits exactly the events it
needs, making it the point where a Phase 1 resilience pattern feeds the Phase 2 SOC layer.

The specification requires seven documented properties per rule. Five are class attributes on
`DetectionRule`, so a rule cannot be written without stating them, and
`python -m soc.rules.main --catalogue` prints the catalogue **from the code** — the documentation of
a rule cannot drift away from the rule.

Three design traps were closed here, each regression-tested, and they are the substance of the
detection work:

- **Rule 2 double-firing on brute force.** `AUTH_FAILED` carries a 401, so a naive "count the 401s"
  rule fires on every Rule 1 attack — two alerts for one attack, doubled responder work.
- **Rule 3 sleeping through its own demo.** Kong's rate limit refuses a burst *before* it reaches a
  service, so the surviving evidence is 429s, not request volume. A volume-only rule would stay
  silent through exactly the scenario it exists for; two independent signals were needed.
- **Rule 4 alarming on recovery.** `CIRCUIT_CLOSED` annotates the description but never fires the
  rule. An alarm on recovery trains a responder to ignore the alarms that matter.

**Verified both directions.** The scripted attack raises **5 alerts from all four rules**; the same
catalogue raises **0 alerts** on `docs/evidence/step12-correlated-logs.jsonl`, a real 16-event
capture taken off the running Phase 1 stack. Passing against data written for the test proves less
than passing against data the system actually produced.

## 5. Alert handling

`soc/alert_service` stores alerts and serves `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}` and
`PATCH /api/v1/alerts/{id}/status`. The `Alert` model mirrors `SecurityEvent` deliberately —
`extra="forbid"`, frozen, camelCase aliases, an `alt-` + 12-hex id — and carries every field §3.4
requires.

Two validators earn their place. `relatedEvents` may not be empty, because an alert citing nothing
is an assertion rather than evidence; and the id format is checked, so the graph loader can parse
every one. Beyond the model, `soc.rules.main` **refuses to store an alert whose `relatedEvents` do
not all resolve** to real events in the collector's store. That check is what makes the graph's
`(:Event)-[:CREATED_ALERT]->(:Alert)` edges trustworthy: an alert in the graph is reachable from the
events that caused it, always.

## 6. The knowledge graph

The model is documented in full at [kg/model/graph_model.md](../../kg/model/graph_model.md): **12
node labels and 18 relationship types**, covering every label §4.1 requires and every relationship
§4.2 lists, plus `SUBTECHNIQUE_OF`, `ACCESSED`, `CONCERNS` and `AFFECTS`. `schema.cypher` puts a uniqueness constraint on each label's natural key, and a test
cross-checks the document, the Python model and the loaders against each other so the diagram cannot
drift from the code.

The three required sources are three loader modules:

1. **Application topology** — services and ports, the endpoints each exposes and whether the gateway
   protects them, the asset register, the seeded accounts and their roles, and the one real
   `incident-service -[:DEPENDS_ON]-> asset-service` edge.
2. **Live events and alerts** — every collected `SecurityEvent` and every raised `Alert`, wired with
   `TRIGGERED`, `GENERATED_BY`, `TARGETED` and `CREATED_ALERT`. Incident events become `Incident`
   nodes linked to the asset they were raised against (`AFFECTS`), and a read of a critical asset
   links the event to that asset (`ACCESSED`). An incident `CONTAINS` every HIGH or CRITICAL alert
   with evidence in the 30 minutes before it was raised — the time-window grouping a SOC uses when a
   responder opens an incident in reaction to what is firing.
3. **Security knowledge** — MITRE ATT&CK T1110 Brute Force with sub-techniques T1110.001–.004, plus
   T1078, T1498 and T1499, one per remaining rule (D-31); the vulnerabilities they exploit; the
   controls that mitigate them; and the response runbooks.

Loaders are pure functions returning `list[Write]`, plus one `apply(session, writes)`. The logic is
therefore testable with no database, and **reloading is idempotent**: `load_events.with_stable_ids`
re-keys alerts onto a content hash (D-32), so two consecutive loads produce 69 nodes and 147 edges,
not double.

**Verified live** against Neo4j 5.22: all 12 labels and all 18 relationship types populated, the
real dependency edge returned by a topology query, and a failed-login alert reaching a control in
three hops — `(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)`. The attack capture's
incident-response phase loads `incident-1`: CRITICAL after escalation, `AFFECTS` the asset
`core-auth-db` — the same asset the compromised `analyst-1` account `ACCESSED` — and `CONTAINS`
the alerts from all four rules.

**Six Cypher queries** (`kg/cypher/q1..q6`) are demonstrated, each opening with the plain-English
question it answers, each returning non-empty results on the seeded graph, and each served over the
graph API. They are listed in [rag-demonstration.md](rag-demonstration.md).

## 7. GraphRAG

Documented in full, with all seven question types and both refusal paths, in
[rag-demonstration.md](rag-demonstration.md). The pattern is **Option A (Cypher-based GraphRAG)**
with **Option C (template) generation** by default, plus an optional LLM generator that rephrases
the same evidence (below). Retrieval is three named steps because the specification marks
the ability to explain retrieval rather than to call a model: classify the intent → select the query
→ run it and shape the rows.

Two properties are worth defending as design choices:

**No new Cypher exists in the RAG layer.** All seven intents map onto the six demonstrated
queries, so the queries the marker watches run are the queries the RAG layer runs. Two tests
guard both directions of the map, so an added intent without a query, or a query without a shaper,
fails the build.

**Generation is template-based, and that is what makes grounding mechanical rather than aspirational
(D-34).** Every slot in every sentence is read out of an `EvidenceNode`, so an answer is
*structurally* incapable of stating something the graph does not hold. `test_grounding.py` enforces
this: it extracts every alert id, event id, technique id and service name from the answer text and
asserts each appears in the evidence's nodes, properties or bound parameters.

**An optional LLM generator rephrases the evidence; it never replaces retrieval.** With `--llm`,
`rag/generation/llm.py` sends Google Gemini (`gemini-3.5-flash-lite` by default) exactly two
things: the question and the rendered evidence block — the same block printed under every answer.
A system instruction tells it to answer only from that evidence, add no fact, technique, control or
recommendation it does not contain, and say the graph does not hold the answer when it does not.
Any failure — no `GEMINI_API_KEY`, an empty retrieval, a timeout, a rate limit, an overloaded model
or an empty reply — falls back to the template, so a question is always answered. Each answer's
`Generation method` line names which generator produced it (`template` or
`graph-grounded LLM (gemini-3.5-flash-lite)`), and the evidence block beneath is identical either
way. The trade is explicit: the LLM reads better, but its grounding is *instructed and checkable*
against the displayed evidence, whereas the template's is *guaranteed* by construction. That is why
the template stays the default and the one the grounding tests exercise.

**Parameters are bound, never interpolated.** An entity id comes from a user's question; a test
asserts it reaches the driver as a parameter and never appears in the query text.

**Verified live:** the specification's own question — *"Why was alert alt-… created and what should
be done?"* — answers with the rule, T1110 Brute Force, three controls and two runbooks, **7 nodes
and 6 relationships displayed**, and every claim mapped to a displayed node. All seven question
types return grounded evidence — including the specification's *"Which incidents are linked to
repeated failed logins?"* — and both refusal paths answer honestly.

## 8. The demonstration workflow

The specification's §7 scenario runs from one command:

```bash
python scripts/run_security_workflow.py
```

Four stages, stopping at the first failure: the attack as collected events → the rules raise 5
alerts → the events and alerts are loaded into Neo4j and linked → the RAG interface is asked why the
alert was created and answers with its evidence. The captured run is at
[docs/evidence/step20-security-workflow.txt](../evidence/step20-security-workflow.txt).

This is the traceability the specification asks for, and each link is visible in that one run:

> **event** (evt-…, `AUTH_FAILED`, from auth-service) → **alert** (alt-…, Multiple Failed Logins,
> citing those event ids) → **graph node** (`(:Alert)`, linked to the user, service, endpoint and
> T1110) → **retrieved evidence** (7 nodes, 6 relationships) → **answer** (every claim mapped to one
> of them).

## 9. Limitations and what was deliberately not built

Stated plainly, because the specification marks the explanation of limitations:

- **The alert store is in-process.** Alerts do not survive a restart; they are re-derivable by
  re-running the rules over the event stream, and are persisted meaningfully only in the graph.
- **LLM answers are instructed to stay grounded, not guaranteed to.** The default template
  generator cannot state anything the graph does not hold; the optional Gemini generator is told not
  to, and its answer can be checked against the evidence printed beneath it, but no test can
  enforce that for free text. It also depends on an external free-tier service: answers take about
  8–20 seconds, the larger Gemini models were often overloaded during testing, and any failure falls
  back to the template answer.
- **The LLM is only as informed as the evidence block.** Where a query's evidence answers a
  neighbouring question rather than the one asked, the LLM says the graph does not hold the answer —
  for example, "which users are linked to repeated failed logins?" retrieves users linked to
  high-severity alerts, and the one user found is linked to a high-severity alert that is not a
  failed-login one.
- **Seven question shapes, not open-ended language.** A question outside them is refused rather
  than mis-answered — the correct failure direction, but a real limit.
- **The demonstration runs off a committed attack capture, not a live attack.** The capture is
  reproducible from `scripts/capture_attack_evidence.py`, and its live twin exists
  (`client/failed_login_demo.py` plus the gateway burst in `tests/integration`), but staging a real
  attack on camera makes a recording depend on timing that cannot be rehearsed.
- **Incidents are grouped by time, not by investigation.** An incident contains every HIGH or
  CRITICAL alert with evidence in the 30 minutes before it was raised. That is the grouping a
  responder makes when opening an incident against what is firing, but it can include an unrelated
  alert that happened to fire in the same window; a responder linking alerts explicitly would need
  an API for it, which incident-service does not have.
- **Asset links rest on event messages.** The schema's thirteen fields have no asset field, so the
  loader reads the asset name from the `INCIDENT_CREATED` and `ASSET_ACCESSED` messages, both
  written by this codebase. Incidents created before that message named the asset carry no
  `AFFECTS` edge.
- **Health is polled, not streamed.** Consul's critical checks are read whenever the collector runs
  against the live stack, so a check that failed and recovered between two runs is not seen. Docker
  container health and Prometheus's `up` metric are visible in their own tools but are not collected.

## 10. Evidence index

| Artefact | File |
|----------|------|
| Collector, live against the stack | [step14-collector.txt](../evidence/step14-collector.txt) |
| The scripted attack, as events | [step15-attack-events.jsonl](../evidence/step15-attack-events.jsonl) |
| Detection run — 5 alerts, and 0 on the clean capture | [step15-detection-run.txt](../evidence/step15-detection-run.txt) |
| Graph load — labels, dependency edge, idempotency | [step17-graph-load.txt](../evidence/step17-graph-load.txt) |
| The Cypher queries, live | [step18-cypher-queries.txt](../evidence/step18-cypher-queries.txt) |
| RAG answers — the question types, both refusals | [step19-rag-answers.txt](../evidence/step19-rag-answers.txt) |
| The complete workflow, one pass | [step20-security-workflow.txt](../evidence/step20-security-workflow.txt) |

**Tests:** 598 unit tests, 0 failures, none requiring a container, a network or a database — of
which 16 are `neo4j`-marked, passing against a live server and skipping cleanly without one. Run
per suite: libs + contract 205, soc 100, kg 49, rag 89, console 13, auth 67, incident 39,
asset 36. The 12 integration tests also pass against the running stack.
