# RAG demonstration — Sentinel-IR

The Phase 2 specification (§11.6) requires at least three natural-language questions demonstrated,
each showing the user question, the retrieved graph evidence, the generated answer, and an
explanation of which retrieval method produced it. Six question types are supported and all six are
shown here, plus both refusal paths.

Every transcript below is real output, captured against Neo4j 5.22 with the graph loaded from the
committed attack capture. The full captures are
[docs/evidence/step19-rag-answers.txt](../evidence/step19-rag-answers.txt) and
[docs/evidence/step20-security-workflow.txt](../evidence/step20-security-workflow.txt); rerun any
of them with

```bash
python -m rag.generation.main "<question>"
python -m rag.generation.main --questions      # the six supported shapes
python -m rag.generation.main --demo           # the scenario question, live
```

## The retrieval method, in one paragraph

This is **Option A, Cypher-based GraphRAG**, with **Option C template generation** on top. It is
three named steps, each its own module, because the specification marks the ability to *explain*
retrieval rather than to call a model:

1. **`rag/retrieval/intent.py` — which question is this?** A keyword scoring table. Each intent owns
   a list of phrases; a question scores one point per phrase present; the highest score wins; ties
   break on declaration order. It is deterministic — a test asserts the same question classifies
   identically ten times — and it can be read aloud, which an embedding cannot.
2. **`rag/retrieval/cypher_builder.py` — which query answers it?** Each of the six intents maps onto
   one of the **five Cypher queries already demonstrated at build step 18**. No new Cypher exists in
   the RAG layer, so the queries the marker watches run there are the queries that run here. Two
   tests guard both directions of that mapping.
3. **`rag/retrieval/retriever.py` — run it and shape the rows.** The entity id extracted from the
   question is passed to the driver as a **bound parameter**, never interpolated into the query
   text; a test asserts the id never appears in the query string.

Generation is **template-based** (`DECISIONS.md` D-34). Every slot in every sentence is read out of
an `EvidenceNode`, so an answer is *structurally* incapable of stating something the graph does not
hold. `rag/tests/test_grounding.py` enforces this mechanically: it extracts every alert id, event
id, technique id and service name from the answer text and asserts each appears in the evidence's
nodes, properties or bound parameters. No LLM is called; `llm_generator.py` is deliberately not
built, though the seam (`generate(evidence) -> Answer`, and `Answer.method`) is kept.

Because retrieval is a single parameterised Cypher query per question, the retrieval method reported
on every answer is the same: **Cypher query over the Neo4j knowledge graph**, with the intent, the
query key and the bound parameters printed alongside it. That line *is* the confidence explanation
the specification asks for — it says exactly how the answer was reached.

## The intent-to-query map

| Intent | Question shape | Cypher query (step 18) |
|--------|----------------|------------------------|
| `ALERT_EXPLANATION` | "why was …" | `q4_controls_for_alert` |
| `RESPONSE_PROCEDURE` | "what should be done …" | `q4_controls_for_alert` |
| `SERVICE_ALERTS` | "which alerts …" | `q1_alerts_for_service` |
| `THREAT_MITIGATION` | "which threats …" | `q3_threats_for_service` |
| `USER_LINKAGE` | "which users …" | `q2_users_high_severity` |
| `DEPENDENCY_IMPACT` | "impact if …" | `q5_dependency_impact` |
| `UNSUPPORTED` | anything else | none — the question is refused |

---

## Question 1 — the demonstration scenario question

> **Why was alert `alt-186f128e294e` created and what should be done?**

**Generated answer**

> Alert alt-186f128e294e was created by the detection rule 'Multiple Failed Logins'. The alert
> indicates ATT&CK technique T1110 (Brute Force). The rule's recommended action is: Temporarily
> block the source IP at the gateway and verify whether the targeted account is compromised; force
> a password reset if it is. The controls that mitigate this threat are Forced password reset,
> Multi-factor authentication and Account lockout. The response procedure is documented in Runbook:
> suspected account compromise and Runbook: brute-force response.

**Retrieved evidence — 7 nodes, 6 relationships, 2 source documents**

```
Retrieved nodes: 7
  - (:Alert {alertId: 'alt-186f128e294e'}) ruleName='Multiple Failed Logins'
      recommendedAction='Temporarily block the source IP at the gateway and verify
      whether the targeted account is compromised; force a password reset if it is.'
  - (:Threat {techniqueId: 'T1110'}) name='Brute Force'
  - (:Control {name: 'Forced password reset'})
  - (:Control {name: 'Multi-factor authentication'})
  - (:Control {name: 'Account lockout'})
  - (:Document {title: 'Runbook: suspected account compromise'})
  - (:Document {title: 'Runbook: brute-force response'})
Retrieved relationships: 6
  - (alt-186f128e294e) -[:INDICATES]-> (T1110)
  - (Forced password reset) -[:MITIGATES]-> (T1110)
  - (Multi-factor authentication) -[:MITIGATES]-> (T1110)
  - (Account lockout) -[:MITIGATES]-> (T1110)
  - (Runbook: suspected account compromise) -[:SUPPORTS_RESPONSE_TO]-> (T1110)
  - (Runbook: brute-force response) -[:SUPPORTS_RESPONSE_TO]-> (T1110)
Source documents: 2
Retrieval method: Cypher query over the Neo4j knowledge graph
  Intent: ALERT_EXPLANATION   Query: controls_for_alert
  Parameters: {'alertId': 'alt-186f128e294e'}
```

**Method** — Cypher, single query, graph traversal three hops deep:
`(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)`. No vector retrieval, no LLM. Every
noun in the answer appears in the evidence above: the rule name, the technique id and name, all
three control names and both runbook titles.

## Question 2 — which alerts affect a service?

> **Which alerts affect auth-service?**

**Generated answer**

> 2 alert(s) affect auth-service:
>   - alt-186f128e294e: Multiple Failed Logins (HIGH, OPEN) — 6 failed logins from 203.0.113.9
>     within 5 minutes, against 1 username.
>   - alt-de2e25686f78: Unauthorised Endpoint Access (HIGH, OPEN) — 3 unauthorised requests from
>     analyst-1 within 10 minutes across 3 endpoints including the privileged route
>     /api/v1/auth/users.

**Retrieved evidence** — 2 `Alert` nodes, each carrying its `ruleName`, `severity`, `status`,
`timestamp`, `description` and `recommendedAction`. 0 relationships: the query returns the alerts
attached to the named service, and the answer makes no claim about anything beyond them.

**Method** — Cypher, `alerts_for_service` (`q1`), parameter `{'service': 'auth-service'}`.
Intent `SERVICE_ALERTS`.

## Question 3 — what threats target a service, and what mitigates them?

> **What is auth-service exposed to and which controls mitigate them?**

**Generated answer**

> auth-service is targeted by T1078 (Valid Accounts) and T1110 (Brute Force). The controls that
> mitigate these techniques are Forced password reset, Multi-factor authentication and Account
> lockout.

**Retrieved evidence** — 7 nodes (2 `Threat`, 2 `Vulnerability`, 3 `Control`) and 8 relationships,
including `(T1110)-[:EXPLOITS]->(No account lockout)` and the three `MITIGATES` edges.

**Method** — Cypher, `threats_for_service` (`q3`), parameter `{'service': 'auth-service'}`.
Intent `THREAT_MITIGATION`.

## Question 4 — which users are linked to repeated failed logins?

> **Which users are linked to repeated failed logins?**

**Generated answer**

> 1 user account(s) are linked to HIGH or CRITICAL alerts:
>   - analyst-1 on Unauthorised Endpoint Access [HIGH], 17 event(s) of evidence

**Retrieved evidence** — 18 nodes (the `User` plus the 17 `Event` nodes it triggered) and 17
`(analyst-1)-[:TRIGGERED]->(evt-…)` relationships. The count in the answer is the number of
relationships displayed beneath it.

**Method** — Cypher, `users_high_severity` (`q2`), no parameters. Intent `USER_LINKAGE`.

## Question 5 — what is the impact if a service fails?

> **What is the likely impact if asset-service fails?**

**Generated answer**

> If asset-service fails, 1 service(s) are affected: incident-service (1 hop(s)).

**Retrieved evidence** — 1 node, `(:Service {name: 'incident-service'})` with `hops=1`.

**Method** — Cypher, `dependency_impact` (`q5`), parameter `{'service': 'asset-service'}`. Intent
`DEPENDENCY_IMPACT`. This is a variable-length traversal over `DEPENDS_ON`, and it returns the one
real dependency in the system — `incident-service` calling `asset-service` through the circuit
breaker — rather than a hand-authored edge.

---

## The two refusal paths

An honest RAG system must be able to say it does not know. Both paths are demonstrated, and both
are regression-tested against a live graph.

**An off-topic question** — "What is the weather in Potchefstroom?"

> The knowledge graph does not hold an answer to this question: no supported question type matched;
> ask about an alert, a service's alerts or threats, users linked to failed logins, or the impact of
> a service failing.

Intent `UNSUPPORTED`, no query run, 0 nodes retrieved. The refusal names what the system *can*
answer rather than only what it cannot.

**A well-formed alert id the graph does not hold** — "Why was alert `alt-ffffffffffff` created?"

> The knowledge graph does not hold an answer to this question: the graph holds no
> controls_for_alert result for {'alertId': 'alt-ffffffffffff'}.

This is the more important of the two. The question classified correctly, the query ran, and it
returned nothing — so the system reports the empty retrieval instead of describing a generic
brute-force alert that would have read as plausible. Because generation reads every slot out of an
`EvidenceNode`, there is nothing for it to say when there are no nodes: the refusal is structural,
not a guard clause someone remembered to write.

## Limitations

- **Six question shapes, not open-ended language.** The classifier is a keyword table. A question
  phrased outside those shapes is refused rather than mis-answered, which is the correct failure
  direction, but it is a genuine limit compared with an LLM front end.
- **One query per question.** Multi-hop questions that would need two queries joined are not
  supported; the intent map is deliberately one-to-one with the five demonstrated queries.
- **No conversational memory.** Each question is answered independently; "and what about that one?"
  will not resolve.
- **Template phrasing.** Answers read as generated, because they are. That is the trade accepted in
  D-34 for the guarantee that no sentence can contain a fact the graph does not hold.
