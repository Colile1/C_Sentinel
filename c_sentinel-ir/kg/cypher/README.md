# kg/cypher/ — **Phase 2**

The demonstrated queries. The specification requires at least five, implemented and demonstrated.

## Planned files

| File | Query |
|------|-------|
| `q1_alerts_for_service.cypher` | All alerts affecting a given service |
| `q2_users_high_severity.cypher` | Users linked to HIGH or CRITICAL alerts |
| `q3_threats_for_service.cypher` | Threats targeting a given service |
| `q4_controls_for_alert.cypher` | Controls that mitigate the threat an alert indicates |
| `q5_dependency_impact.cypher` | Blast radius: which services depend, directly or transitively, on a failing service |
| `graph_service.py` | A small FastAPI service exposing each query as an endpoint, so the queries are reachable from the RAG layer and from a browser during the demo |

Each `.cypher` file opens with a comment stating the question it answers in plain English — the
demo narration is then a matter of reading the file.

Done when: all five return non-empty results against the seeded graph, and each is reachable through
`graph_service.py`.
