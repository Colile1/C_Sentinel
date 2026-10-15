# docs/report/

The written reports for both phases.

## Phase 1 — the microservices platform

| File | Contents |
|------|----------|
| `deliverable1.md` | The Phase 1 report: system functionality, API documentation with example requests and responses, the architecture diagram, the two patterns and how each is implemented, and how security events are collected |

## Phase 2 — SOC monitoring, the knowledge graph and GraphRAG

| File | Contents |
|------|----------|
| `deliverable2.md` | The Phase 2 report: architecture, design choices, limitations and an evidence index. Points to the three documents below rather than restating them |
| `detection-rules.md` | The rule catalogue — name, purpose, input events, detection condition, severity, generated alert and recommended response for each of the four rules, plus the design trap each rule avoids. Five of the seven properties print from the code with `python -m soc.rules.main --catalogue` |
| `rag-demonstration.md` | Seven question types and both refusal paths, each with the question, the retrieved evidence, the generated answer and the retrieval method. Real captured output |

The graph model is not in this folder: it lives with the code it describes, at
`kg/model/graph_model.md`, so a test can cross-check it against `graph_model.py` and the loaders.

## Why the Phase 2 workflow is one command

The security workflow runs failed logins → collected events → detection rule → alert → Neo4j →
linked to user, service, endpoint and threat → threat to controls → a natural-language question →
a grounded answer with its evidence. `scripts/run_security_workflow.py` runs every stage in order
and stops at the first one that fails, naming it, so the whole chain can be checked at once instead
of by running four commands by hand.

Every answer the RAG layer gives shows its evidence: retrieved nodes, retrieved relationships,
source documents and the retrieval method. That evidence block is the point of the answer, not an
appendix to it.
