# kg/loader/ — **Phase 2**

Populates the graph. One loader per required source, so a source can be reloaded without touching
the others, and so the "three sources" requirement is visible in the file list.

## Files

| File | Responsibility | Status |
|------|----------------|--------|
| `connection.py` | `get_driver()` — the Neo4j driver from the four `NEO4J_*` variables. The only place connection details live. Does **not** use `common.config.Settings` (that requires a `DATABASE_URL`/`JWT_SECRET` the loader has no use for) | **built at step 17** |
| `writes.py` | `Write` — one idempotent `(cypher, parameters)` operation; `apply(session, writes)` runs a list in one transaction | **built at step 17** |
| `load_topology.py` | Source 1: `topology()` → services, the endpoints each exposes and whether the gateway protects them, the real `incident-service -[:DEPENDS_ON]-> asset-service` edge, seeded users with roles (including the bootstrap admin the seed file omits), the asset register | **built at step 17** |
| `load_events.py` | Source 2: `events(store, alert_store)` → every collected `SecurityEvent` and every raised `Alert`, with `TRIGGERED`, `GENERATED_BY`, `TARGETED` and `CREATED_ALERT` edges. `stable_alert_id()` re-keys alerts deterministically so a reload MERGEs the same node | **built at step 17** |
| `load_security_knowledge.py` | Source 3: `knowledge()` → MITRE **T1110 Brute Force** and its four sub-techniques, one further technique per other detection rule (T1078, T1498, T1499), the vulnerabilities they exploit, the controls that mitigate them (account lockout, MFA, password reset, rate limiting), the response runbooks, and the `INDICATES` edge from each rule's alerts to its technique | **built at step 17** |
| `main.py` | Thin orchestrator: apply `kg/model/schema.cypher`, then run the three loaders in order. `--file`/`--stdin` choose the event source (same as the collector); `--dry-run` prints write counts without contacting Neo4j | **built at step 17** |

## Why the loaders are split in two

Each loader is a **pure function** from its source to a `list[Write]`, plus `apply`, which executes
that list. The write list is unit-testable with no database — `kg/loader/tests/` asserts the exact
statements and their parameters, and `kg/loader/tests/test_model_and_main.py` cross-checks every
node label and relationship type against `kg/model/graph_model.py` so the schema doc and the code
that builds the graph cannot drift. Only `main.py` and a manual live run call `apply`.

## Idempotence

Every statement is a `MERGE`, never a blind `CREATE`, so re-running during a demo does not duplicate
the graph. Events and alerts come from the same path `soc.rules.main` uses — the collector builds
the event store, the rule catalogue is evaluated, the alerts are raised — but the alert schema
mints a fresh random `alertId` per construction, which would make each reload create new Alert
nodes. `with_stable_ids` re-keys each alert onto `stable_alert_id`, a hash over the firing's rule
name, attributed subjects and cited event ids, before loading. Verified: two consecutive
`python -m kg.loader.main` runs against the same stream leave the graph at 65 nodes / 130 edges.

## Running it

```bash
# against the Compose Neo4j (deploy/.env sets NEO4J_PASSWORD)
docker compose -f deploy/docker-compose.yml up -d neo4j
python -m kg.loader.main --file docs/evidence/step15-attack-events.jsonl
# or against the running stack's own logs
python -m kg.loader.main
```

Done when: `python -m kg.loader.main` on an empty database yields a graph where a failed-login alert
reaches a control in three hops — `(:Alert)-[:INDICATES]->(:Threat)<-[:MITIGATES]-(:Control)`.
Verified live at step 17: all twelve node labels present, `incident-service -[:DEPENDS_ON]->
asset-service` returned, and a *Multiple Failed Logins* alert reaches all three named controls.
