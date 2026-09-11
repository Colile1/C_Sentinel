# Mark map — Phase 2

Every criterion in the Phase 2 specification's assessment table (§12), mapped to the artefact that
earns it, the build step that produced it, and the demo moment that shows it. **A row with an empty
column is a mark not yet earned.**

| Criterion | Weight | Artefact | Build step | Shown in the demo at |
|-----------|--------|----------|-----------|----------------------|
| **SOC event collection** — events collected from relevant services | 15% | `soc/collector/`, `docs/soc-events.md`, [step14-collector.txt](../evidence/step14-collector.txt) | 3, 14 | 0:30–2:00 — 1521 live events, four sources, one workflow by correlation ID |
| **Detection rules** — at least three meaningful rules implemented and demonstrated | 15% | `soc/rules/` (four rules), [detection-rules.md](detection-rules.md), [step15-detection-run.txt](../evidence/step15-detection-run.txt) | 15 | 2:00–4:00 — `--catalogue` printed from the code, then both directions (5 alerts / 0 alerts) |
| **Alert handling** — alerts created, stored, displayed, linked to events | 10% | `soc/alert_service/` (`models.py`, `store.py`, `router.py`) | 15, 16 | 4:00–8:00 stage 2 — 5 alerts with resolvable `relatedEvents` |
| **Knowledge graph model** — relevant security, application and operational entities | 15% | [kg/model/graph_model.md](../../kg/model/graph_model.md), `schema.cypher`, `graph_model.py` | 17 | 8:00–9:30 — the model document and the Neo4j Browser visualisation |
| **Graph integration** — events and alerts inserted and linked meaningfully | 10% | `kg/loader/` (three loaders), `kg/cypher/q1..q5` | 17, 18 | 4:00–8:00 stage 3, then the three-hop alert→control query at 8:00 |
| **RAG capability** — natural-language questions retrieve graph evidence and produce grounded answers | 25% | `rag/retrieval/`, `rag/generation/`, [rag-demonstration.md](rag-demonstration.md) | 19 | 4:00–8:00 stage 4, then three more questions and both refusals at 9:30–11:00 |
| **Technical explanation** — architecture, design choices, limitations, evidence | 15% | [deliverable2.md](deliverable2.md), the folder READMEs | 20 | Read alongside the demo; §9 states the limitations plainly |

## Specification deliverables (§10)

| Item | Where it comes from | Done |
|------|--------------------|------|
| §11.1 Updated source code — collection, alert logic, monitoring config | `soc/`, `kg/`, `rag/`, `observability/` | ☑ |
| §11.3 Knowledge graph model — labels, relationships, properties, connections | [kg/model/graph_model.md](../../kg/model/graph_model.md) | ☑ 12 labels, 14 relationship types, table + diagram |
| §11.4 Detection rule documentation — seven properties per rule | [detection-rules.md](detection-rules.md) | ☑ four rules, all seven each |
| §11.6 RAG demonstration — 3+ questions with evidence, answer, method | [rag-demonstration.md](rag-demonstration.md) | ☑ six question types + two refusals |
| §7 Minimum demonstration scenario — one complete workflow | `scripts/run_security_workflow.py`, [step20-security-workflow.txt](../evidence/step20-security-workflow.txt) | ☑ four stages, one pass, exit 0 |
| Phase 2 report (PDF) | [deliverable2.md](deliverable2.md) | ☐ draft written; export to PDF before upload |
| Demo video | Recorded against [phase2-demo-script.md](phase2-demo-script.md) | ☐ not yet recorded |
| Uploaded to Dropbox | | ☐ |

## The two things most likely to cost marks

1. **RAG capability, 25% — the evidence, not the answer.** §5.3 requires every answer to *display*
   its evidence: retrieved nodes, retrieved relationships, source documents, and an explanation of
   the retrieval method. A fluent answer with no evidence block earns less than a stilted one with
   it. Every answer this system prints carries all four, and the demo must pause on that block
   rather than reading only the prose.

2. **Technical explanation, 15% — limitations are marked.** The criterion names limitations
   explicitly. §9 of the report states the remaining ones plainly — the in-process alert store, no
   LLM, six question shapes, the committed capture, unexercised `Incident` nodes. The Kong
   log-stream source, previously the one genuinely open code item, is now closed and live-verified
   (D-36). Claiming completeness that the code does not have is worth less than naming a gap and
   showing it is understood — and closing one is worth more than either.
