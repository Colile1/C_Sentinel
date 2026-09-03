# scripts/

Operational scripts — the things run by hand during development and on camera during the demo. Each
one is a thin entry point over logic that lives elsewhere, and each prints `Description: value`.

Built at build step 12 (except `capture_breaker_evidence.py`, from step 8).

| File | Responsibility |
|------|----------------|
| `seed_data.py` | Loads `data/seed/` through the public API — the two analyst users and the asset register — as the bootstrap admin. Idempotent: a 409 conflict is treated as already present, so it can be re-run mid-demo without a duplicate-key error |
| `break_asset_service.py` | Stops `asset-service`, drives incident creation until the breaker opens, prints each response time, then restarts the service and waits for `CIRCUIT_CLOSED`. This is the ninety seconds that earns the pattern mark |
| `capture_breaker_evidence.py` | Drives `ResilientClient` against a dependency that is down and then recovers, printing each call's elapsed time and writing the security events. The offline twin of `break_asset_service.py`: it needs no Docker, so `docs/evidence/step8-*` is reproducible from a clean checkout while writing the report |
| `capture_evidence.py` | Runs the demo workflow with a fixed correlation ID and writes the request/response output and the correlated log lines from all three services into `docs/evidence/step12-*`, so the report's screenshots are reproducible rather than hand-cropped |
| `verify_stack.py` | Pre-demo preflight: every container healthy, all three services registered in Consul, every Prometheus target UP, the gateway answering. Run this before recording, not during |

## Integration

Scripts talk to the running stack over HTTP and to Docker through the CLI. They may not import a
service package — they are outside callers, like `client/`.

Done when: `python scripts/verify_stack.py` prints an all-green summary on a freshly started stack.
