# kg/cypher/ — **Phase 2**

The demonstrated queries. The specification requires at least five, implemented and demonstrated.

## Files

| File | Query / role | Status |
|------|--------------|--------|
| `q1_alerts_for_service.cypher` | All alerts affecting a given service (`$service`) | **built at step 18** |
| `q2_users_high_severity.cypher` | Users linked to HIGH or CRITICAL alerts, with the events as evidence (no parameters) | **built at step 18** |
| `q3_threats_for_service.cypher` | ATT&CK techniques targeting a given service, with the vulnerabilities they exploit and the controls that mitigate them (`$service`) | **built at step 18** |
| `q4_controls_for_alert.cypher` | Controls and runbooks that address the threat a given alert indicates (`$alertId`) — the query the RAG layer runs for "what should be done?" | **built at step 18** |
| `q5_dependency_impact.cypher` | Blast radius: which services depend, directly or transitively, on a failing service (`$service`) | **built at step 18** |
| `queries.py` | `QUERIES` — the catalogue: each query's key, plain-English question, `.cypher` file and required parameters. One definition shared by `graph_service.py` and the tests | **built at step 18** |
| `graph_service.py` | A thin FastAPI service: `GET /api/v1/graph/queries` lists the catalogue, and one GET endpoint per query. Reads Neo4j through `kg.loader.connection.run_query`; no database of its own, no Consul (D-30) | **built at step 18** |

Each `.cypher` file opens with a `// Question:` line stating what it answers in plain English — the
demo narration is then a matter of reading the file.

## Running

```bash
docker compose -f deploy/docker-compose.yml up -d neo4j
python -m kg.loader.main --file docs/evidence/step15-attack-events.jsonl   # seed the graph
uvicorn kg.cypher.graph_service:app --port 8008                            # then the API
curl 'http://localhost:8008/api/v1/graph/alerts?service=auth-service'
curl 'http://localhost:8008/api/v1/graph/dependency-impact?service=asset-service'
```

## Tests

- `tests/test_queries.py` and `tests/test_graph_service.py` run without Neo4j: the catalogue is
  complete, every declared parameter is referenced in its Cypher, and the API validates and
  forwards parameters correctly (`run_query` patched).
- `tests/test_live_queries.py` is marked `neo4j` — skipped unless a server answers at `NEO4J_URI`.
  It loads the graph from the committed step-15 attack capture and asserts all five queries return
  non-empty rows, q5 returns the real `incident-service` dependency, and q4 reaches a control for a
  *Multiple Failed Logins* alert. This is the step-18 verification; run it with
  `docker compose up -d neo4j` and `NEO4J_PASSWORD=... python -m pytest kg/cypher/tests/test_live_queries.py -m neo4j`.

## Known caveat

`q2` returns `role: null` for a user whose events name them `analyst-1` while the seed file loads
`analyst1` — the step-15 attack capture and `data/seed/users.json` use different username
conventions. The query is correct; it returns exactly what the graph links. A live workflow capture
(as opposed to the scripted attack) carries the seed usernames and resolves the role.

Done when: all five return non-empty results against the seeded graph, and each is reachable through
`graph_service.py`. Verified live at step 18.
