# Demo script — Phase 2

The Phase 2 specification §7 asks for **one complete security workflow demonstrated end to end**:
failed logins → collected events → detection rule → alert → Neo4j → linked to user, service,
endpoint and threat → threat linked to controls → a natural-language question → a grounded answer
with its evidence.

That whole chain runs from **one command**, `python scripts/run_security_workflow.py`, so the
workflow can be shown in one pass without switching between four terminals and losing the thread.
The segments below add the explanation around it.

Target: **10–12 minutes**. Rehearse once against a loaded graph before recording.

## Before recording

```bash
cd c_sentinel-ir
docker compose -f deploy/docker-compose.yml up -d neo4j
docker compose -f deploy/docker-compose.yml ps neo4j          # healthy
python scripts/run_security_workflow.py --dry-run             # the four stages
```

Have open and ready to switch to: a terminal in `c_sentinel-ir/`, a browser tab on
`http://localhost:7474` (Neo4j Browser, signed in), and an editor with
`kg/model/graph_model.md`, `soc/rules/rule_failed_logins.py` and `kg/cypher/q4_controls_for_alert.cypher`.

If the full Phase 1 stack is also up, `python -m soc.collector.main` reads live container logs
instead of a file — worth showing for thirty seconds, but the workflow itself runs off the committed
capture so the demo does not depend on staging a live attack on camera.

## 0:00–0:30 — Identification

Camera on. "Colile Sibanda, student number 56543115, ITRI623, Sentinel-IR, Phase 2." Camera off for
the rest of the recording.

## 0:30–2:00 — SOC event collection (criterion 1, 15%)

State that Phase 1 was built so this layer needs no translation: every service emits the schema
fixed in `docs/soc-events.md`, and the collector reads it straight off `docker compose logs`.

```bash
python -m soc.collector.main --file docs/evidence/step14-collector.txt   # or live, see above
```

Point out the four sources the specification names — the gateway, auth-service, the two domain
services — and that a live run collected **1521 events across 3 services and 10 event types**. Then
show one workflow traced by correlation ID across all three services, which is what makes an alert's
`relatedEvents` resolvable later.

## 2:00–4:00 — Detection rules and alerts (criteria 2 and 3, 25%)

```bash
python -m soc.rules.main --catalogue
```

Say out loud that **this catalogue is printed from the rule classes themselves**, so the
documentation of a rule cannot drift from the rule. Open `soc/rules/rule_failed_logins.py` and
explain the one design point worth the time: the subject is keyed **both** by user and by source IP,
because an attacker controls one of the two, and a burst that trips both raises two alerts
deliberately — "this account is under attack" and "this address is attacking" are different findings.

Then the silent direction, which is the half that is easy to skip and expensive to lose:

```bash
python -m soc.rules.main --file docs/evidence/step12-correlated-logs.jsonl    # 0 alerts
```

Say that this file is a **real capture off the running stack at Phase 1**, not a fixture — a rule
that fires on everything is not a detection rule.

## 4:00–8:00 — The complete workflow, one pass (criteria 4, 5 and 6)

This is the segment the specification's §7 asks for. Start it and narrate as each stage prints.

```bash
python scripts/run_security_workflow.py
```

**Stage 1 — the attack, as events.** 22 events written: six failed logins against `analyst-1` from
`203.0.113.9`, the success that means the attacker guessed the password, three probes at endpoints
the role does not cover including the admin route, a gateway-throttled flood, and `asset-service`
falling over behind the circuit breaker.

**Stage 2 — detection.** **5 alerts from all four rules**, each printed with its rule, severity,
affected service, affected user and its `relatedEvents` count. Point out the two *Multiple Failed
Logins* alerts and name why there are two. Say that `soc.rules.main` refuses to store an alert whose
related events do not all resolve to real collected events — an alert citing evidence that does not
exist is an assertion, not a finding.

**Stage 3 — the graph.** ~195 writes across the three required sources: topology, events and alerts,
and MITRE ATT&CK security knowledge. Say the loaders are idempotent — re-running produces the same
graph, not a doubled one.

**Stage 4 — the question and the answer.** The RAG interface is asked the specification's own
question, *"Why was alert alt-… created and what should be done?"*, and answers with the rule, ATT&CK
technique **T1110 Brute Force**, three mitigating controls and two runbooks — **7 nodes and 6
relationships displayed as evidence beneath it**.

Read one sentence of the answer aloud, then point at the evidence block and say the sentence's claim
maps to a node in it. Then state the property that matters: generation is template-based, every slot
is read out of a retrieved node, so the answer is *structurally* incapable of stating something the
graph does not hold — and a test enforces that by extracting every id and name from the answer text
and asserting each appears in the evidence.

## 8:00–9:30 — The graph model and the five queries (criteria 4 and 5, 25%)

Switch to the Neo4j Browser on `localhost:7474`.

```cypher
MATCH (a:Alert {ruleName: 'Multiple Failed Logins'})-[:INDICATES]->(t:Threat)<-[:MITIGATES]-(c:Control)
RETURN a, t, c
```

Show the visualisation: the alert, T1110, and the three controls. Then run the reverse direction to
show the alert reaching its evidence:

```cypher
MATCH (u:User)-[:TRIGGERED]->(e:Event)-[:CREATED_ALERT]->(a:Alert) RETURN u, e, a LIMIT 25
```

Open `kg/model/graph_model.md` for fifteen seconds — twelve node labels, fourteen relationship
types, the three sources — and say that this document and `graph_model.py` are cross-checked by a
test, so the diagram cannot drift from the loaders.

Then open `kg/cypher/q4_controls_for_alert.cypher` and say the sentence that ties the two halves
together: **the RAG layer runs these five queries and no others**, so the queries demonstrated here
are exactly the retrieval the answer at minute 7 came from.

## 9:30–11:00 — Three more questions (criterion 6, 25%)

Back to the terminal. Three questions, different intents, one command each:

```bash
python -m rag.generation.main "Which alerts affect auth-service?"
python -m rag.generation.main "What is the likely impact if asset-service fails?"
python -m rag.generation.main "What is the weather in Potchefstroom?"
```

The first two show different queries selected by intent, each with its evidence. **The third is the
one to spend time on:** it is refused, and the refusal names what the system *can* answer. Follow it
with the harder refusal:

```bash
python -m rag.generation.main "Why was alert alt-ffffffffffff created?"
```

Say why this one matters: the question classified correctly and the query ran — it simply returned
nothing, and the system reports that rather than describing a plausible generic alert. An honest
"I don't know" is worth more than a confident wrong answer.

## 11:00–11:30 — Close

State the traceability chain in one sentence, since the specification asks for it explicitly:
**event → alert → graph node → retrieved evidence → answer**, every link shown in the run at minute
4, and every claim in the final answer mapped to a node displayed beside it. Stop recording.

## Timing budget

| Segment | Minutes |
|---|---|
| Identification | 0.5 |
| SOC event collection | 1.5 |
| Detection rules and alerts | 2.0 |
| The complete workflow, one pass | 4.0 |
| Graph model and the five queries | 1.5 |
| Three more questions | 1.5 |
| Close | 0.5 |
| **Total** | **11.5** |

Trim the SOC collection segment first if a rehearsal runs long — it is the lightest-weighted
criterion at 15% and the best-evidenced elsewhere. **Never cut the one-pass workflow or the RAG
questions:** together they carry 60% of the Phase 2 mark, and §7 asks for the workflow explicitly.

## If something fails on camera

`run_security_workflow.py` stops at the first failing stage and names it rather than carrying on
with a broken graph. The two likely failures both concern Neo4j:

- **Stage 3 exits 1** — Neo4j is not up, or `NEO4J_PASSWORD` is unset in `deploy/.env`. The script
  prints both checks. `deploy/.env` is git-ignored and predates the graph work, so on a fresh
  machine the `NEO4J_*` block must be copied across from `deploy/.env.example`.
- **Stage 4 says the graph holds no alert** — stage 3 did not run, or ran against a different
  database. Re-run the workflow from the start.
