# scripts/

Operational scripts — the things run by hand during development and on camera during the demo. Each
one is a thin entry point over logic that lives elsewhere, and each prints `Description: value`.

Most were built at build step 12; the build step each of the others belongs to is named in its row.

| File | Responsibility |
|------|----------------|
| `seed_data.py` | Loads `data/seed/` through the public API — the two analyst users and the asset register — as the bootstrap admin. Idempotent: a 409 conflict is treated as already present, so it can be re-run mid-demo without a duplicate-key error |
| `break_asset_service.py` | Stops `asset-service`, drives incident creation until the breaker opens, prints each response time, then restarts the service and waits for `CIRCUIT_CLOSED`. This is the ninety seconds that earns the pattern mark |
| `capture_breaker_evidence.py` | Drives `ResilientClient` against a dependency that is down and then recovers, printing each call's elapsed time and writing the security events. The offline twin of `break_asset_service.py`: it needs no Docker, so `docs/evidence/step8-*` is reproducible from a clean checkout while writing the report (step 8) |
| `capture_evidence.py` | Runs the demo workflow with a fixed correlation ID and writes the request/response output and the correlated log lines from all three services into `docs/evidence/step12-*`, so the report's screenshots are reproducible rather than hand-cropped |
| `verify_stack.py` | Pre-demo preflight: every container healthy, all three services registered in Consul, every Prometheus target UP, the gateway answering. Run this before recording, not during |
| `capture_attack_evidence.py` | Writes the 22-event scripted attack the detection rules fire on (`docs/evidence/step15-attack-events.jsonl`). Offline, like `capture_breaker_evidence.py`, so the rules can be demonstrated without staging a live attack against the stack (step 15) |
| `run_security_workflow.py` | The Phase 2 demonstration scenario in one pass: attack events → detection rules → Neo4j load → the RAG answer. Four stages, each announced, stopping at the first failure and naming it. `--dry-run` prints the commands; `--skip-capture` keeps the committed capture. Stages 3 and 4 need Neo4j (step 20) |

## Integration

Scripts talk to the running stack over HTTP and to Docker through the CLI. They may not import a
service package — they are outside callers, like `client/`. `run_security_workflow.py` holds to the
same rule for the Phase 2 modules: it shells out to the `soc`, `kg` and `rag` CLIs rather than
importing them, so what it runs is exactly what the demo script tells the presenter to type.

Done when: `python scripts/verify_stack.py` prints an all-green summary on a freshly started stack.
