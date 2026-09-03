# kg/loader/ — **Phase 2**

Populates the graph. One loader per required source, so a source can be reloaded without touching
the others, and so the "three sources" requirement is visible in the file list.

## Planned files

| File | Responsibility |
|------|----------------|
| `connection.py` | `get_driver()` — the Neo4j driver from settings. The only place connection details live |
| `load_topology.py` | Source 1: application structure. Services, the endpoints each exposes, the real `incident -> asset` dependency, users and their roles |
| `load_events.py` | Source 2: events and alerts from `soc/`, with `TRIGGERED`, `GENERATED_BY`, `TARGETED` and `CREATED_ALERT` edges |
| `load_security_knowledge.py` | Source 3: threats, vulnerabilities, controls and procedures — starting from MITRE ATT&CK T1110 Brute Force and its sub-techniques, with `MITIGATES` edges from account lockout, MFA and password reset |
| `main.py` | Thin orchestrator: apply the schema, then run the three loaders in order |

All loaders are idempotent — `MERGE`, never blind `CREATE` — so reloading during a demo does not
duplicate the graph.

Done when: `python -m kg.loader.main` on an empty database yields a graph where a failed-login alert
reaches a control in three hops.
