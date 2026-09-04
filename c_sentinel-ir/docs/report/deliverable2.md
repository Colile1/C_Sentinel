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
                      │ 12 labels, 14 rel. types  │      │ T1110, T1078, …      │
                      └────────────┬──────────────┘      └──────────────────────┘
                                   │  5 Cypher queries (kg/cypher)
                                   ▼
                      ┌───────────────────────────┐
                      │ rag/retrieval             │  intent → query → rows
                      │ rag/generation            │  template → answer + evidence
                      └───────────────────────────┘
```

Three things about this shape are worth stating, because each was a decision rather than a default:

**The layers are one-directional and each is a pure function of the one before it.** A rule is a
pure function of the event store's contents and an injected clock; a loader is a pure function
returning a list of writes; a retriever shapes rows. Nothing reaches backwards. This is why 545 unit
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

**Known limitation.** The specification names four sources and three are read live. The gateway's
own events (`UNAUTHORISED_ACCESS`, `RATE_LIMIT_EXCEEDED`) come from Kong's log stream rather than
the service container logs, and reach the collector today only via `--file`. The reader validates
gateway-shaped lines identically — they are exercised throughout the attack capture and covered by
the contract tests — so wiring Kong's stream in is a **source** addition, not a reader or rule
change. It is recorded as open in `TODO.md` rather than papered over.

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
node labels and 14 relationship types**, covering every label §4.1 requires and every relationship
§4.2 lists. `schema.cypher` puts a uniqueness constraint on each label's natural key, and a test
cross-checks the document, the Python model and the loaders against each other so the diagram cannot
drift from the code.

The three required sources are three loader modules:

1. **Application topology** — services and ports, the endpoints each exposes and whether the gateway
   protects them, the asset register, the seeded accounts and their roles, and the one real
   `incident-service -[:DEPENDS_ON]-> asset-service` edge.
2. **Live events and alerts** — every collected `SecurityEvent` and every raised `Alert`, wired with
   `TRIGGERED`, `GENERATED_BY`, `TARGETED` and `CREATED_ALERT`.
3. **Security knowledge** — MITRE ATT&CK T1110 Brute Force with sub-techniques T1110.001–.004, plus
   T1078, T1498 and T1499, one per remaining rule (D-31); the vulnerabilities they exploit; the
   controls that mitigate them; and the response runbooks.

Loaders are pure functions returning `list[Write]`, plus one `apply(session, writes)`. The logic is
therefore testable with no database, and **reloading is idempotent**: `load_events.with_stable_ids`
re-keys alerts onto a content hash (D-32), so two consecutive loads produce 65 nodes and 130 edges,
not double.

**Verified live** against Neo4j 5.22: 12 labels present, the real dependency edge returned by a
topology query, and a failed-login alert reaching a control in three hops —
`(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)`.

**Five Cypher queries** (`kg/cypher/q1..q5`) are demonstrated, each opening with the plain-English
question it answers, each returning non-empty results on the seeded graph, and each served over the
graph API. They are listed in [rag-demonstration.md](rag-demonstration.md).

## 7. GraphRAG

Documented in full, with all six question types and both refusal paths, in
[rag-demonstration.md](rag-demonstration.md). The pattern is **Option A (Cypher-based GraphRAG)**
with **Option C (template) generation**, and it is three named steps because the specification marks
the ability to explain retrieval rather than to call a model: classify the intent → select the query
→ run it and shape the rows.

Two properties are worth defending as design choices:

**No new Cypher exists in the RAG layer.** All six intents map onto the five queries demonstrated at
build step 18, so the queries the marker watches run are the queries the RAG layer runs. Two tests
guard both directions of the map, so an added intent without a query, or a query without a shaper,
fails the build.

**Generation is template-based, and that is what makes grounding mechanical rather than aspirational
(D-34).** Every slot in every sentence is read out of an `EvidenceNode`, so an answer is
*structurally* incapable of stating something the graph does not hold. `test_grounding.py` enforces
this: it extracts every alert id, event id, technique id and service name from the answer text and
asserts each appears in the evidence's nodes, properties or bound parameters. An LLM answer would
have read better and could only ever have been *checked* for grounding, not *guaranteed* it. The
seam for an LLM generator is kept (`generate(evidence) -> Answer`, and `Answer.method`) but
deliberately not built.

**Parameters are bound, never interpolated.** An entity id comes from a user's question; a test
asserts it reaches the driver as a parameter and never appears in the query text.

**Verified live:** the specification's own question — *"Why was alert alt-… created and what should
be done?"* — answers with the rule, T1110 Brute Force, three controls and two runbooks, **7 nodes
and 6 relationships displayed**, and every claim mapped to a displayed node. All six question types
return grounded evidence; both refusal paths answer honestly.

## 8. The demonstration workflow

The specification's §7 scenario runs from one command:

```bash
python scripts/run_security_workflow.py
```

Four stages, stopping at the first failure: the attack as collected events → the rules raise 5
alerts → the events and alerts are loaded into Neo4j and linked → the RAG interface is asked why the
alert was created and answers with its evidence. The captured run is at
[docs/evidence/step20-security-workflow.txt](../evidence/step20-security-workflow.txt); the narrated
version is [phase2-demo-script.md](phase2-demo-script.md).

This is the traceability the specification asks for, and each link is visible in that one run:

> **event** (evt-…, `AUTH_FAILED`, from auth-service) → **alert** (alt-…, Multiple Failed Logins,
> citing those event ids) → **graph node** (`(:Alert)`, linked to the user, service, endpoint and
> T1110) → **retrieved evidence** (7 nodes, 6 relationships) → **answer** (every claim mapped to one
> of them).

## 9. Limitations and what was deliberately not built

Stated plainly, because the specification marks the explanation of limitations:

- **Kong's log stream is not yet a live collector source.** Gateway events reach the collector via
  `--file` today. See §3.
- **The alert store is in-process.** Alerts do not survive a restart; they are re-derivable by
  re-running the rules over the event stream, and are persisted meaningfully only in the graph.
- **No LLM.** Answers read as generated. This was chosen (D-34) for the structural grounding
  guarantee; the trade is fluency for verifiability.
- **Six question shapes, not open-ended language.** A question outside them is refused rather than
  mis-answered — the correct failure direction, but a real limit.
- **The demonstration runs off a committed attack capture, not a live attack.** The capture is
  reproducible from `scripts/capture_attack_evidence.py`, and its live twin exists
  (`client/failed_login_demo.py` plus the gateway burst in `tests/integration`), but staging a real
  attack on camera makes a recording depend on timing that cannot be rehearsed.
- **`Incident` nodes are loaded only when incident events are present.** The attack capture is an
  authentication and availability story, so `(:Incident)-[:CONTAINS]->(:Alert)` is modelled and
  loadable but not exercised by the demonstrated scenario.

## 10. Evidence index

| Artefact | File |
|----------|------|
| Collector, live against the stack | [step14-collector.txt](../evidence/step14-collector.txt) |
| The scripted attack, as events | [step15-attack-events.jsonl](../evidence/step15-attack-events.jsonl) |
| Detection run — 5 alerts, and 0 on the clean capture | [step15-detection-run.txt](../evidence/step15-detection-run.txt) |
| Graph load — labels, dependency edge, idempotency | [step17-graph-load.txt](../evidence/step17-graph-load.txt) |
| The five Cypher queries, live | [step18-cypher-queries.txt](../evidence/step18-cypher-queries.txt) |
| RAG answers — six question types, both refusals | [step19-rag-answers.txt](../evidence/step19-rag-answers.txt) |
| The complete workflow, one pass | [step20-security-workflow.txt](../evidence/step20-security-workflow.txt) |

**Tests:** 546 unit tests, 0 failures, none requiring a container, a network or a database — of
which 16 are `neo4j`-marked, passing against a live server and skipping cleanly without one. Run
per suite (`DECISIONS.md` D-13): libs + contract 196, soc 89, kg 42, rag 77, auth 67, incident 39,
asset 36.
