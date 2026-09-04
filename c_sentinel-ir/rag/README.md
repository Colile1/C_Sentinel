# rag/ — **Phase 2**

Retrieval-augmented generation over the knowledge graph. A user asks a security question in plain
English; the system retrieves the relevant subgraph and produces an answer whose every claim is
backed by a node or relationship it shows alongside.

The specification is emphatic on two points: the answer must be grounded in evidence retrieved from
the graph, and the student must be able to explain the retrieval process rather than merely call a
model. The design here follows Option A, Cypher-based GraphRAG, because its retrieval step is a
query the student can read out loud.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `retrieval/` | Question to Cypher to subgraph |
| `generation/` | Subgraph to answer, with the evidence attached |

Generation is **template-based** (D-34): every slot in every sentence is read out of a retrieved
node, so an answer is structurally incapable of stating something the graph does not hold.

## The questions it answers

Each maps to one of the five queries demonstrated at step 18 — no new Cypher is written here.

| Question | Intent | Query |
|----------|--------|-------|
| Why was this alert created, and what should be done? | `ALERT_EXPLANATION` | `controls_for_alert` |
| What response procedure should be followed? | `RESPONSE_PROCEDURE` | `controls_for_alert` |
| Which alerts affect this service? | `SERVICE_ALERTS` | `alerts_for_service` |
| What threats target this service, and what mitigates them? | `THREAT_MITIGATION` | `threats_for_service` |
| Which users are linked to repeated failed logins? | `USER_LINKAGE` | `users_high_severity` |
| What is the likely impact if this service fails? | `DEPENDENCY_IMPACT` | `dependency_impact` |

Anything else is answered "the knowledge graph does not hold an answer to this question", with the
reason — never a guess.

## Running it

```bash
python -m rag.generation.main --demo
```

Worked answers for all six question types, plus both refusal cases, are captured at
`docs/evidence/step19-rag-answers.txt`.

## Integration

Reads `kg/` and nothing else. Never queries a Phase 1 database directly — if the graph does not know
something, the honest answer is that the graph does not know it.

Done when: "Why was this alert created and what should be done?" returns an answer in which every
claim maps to a displayed retrieved node or relationship. **Done** — verified against a live Neo4j
by `rag/tests/test_live_answers.py`, which asserts the property mechanically rather than by reading.
