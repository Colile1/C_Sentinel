# scripts/

Operational scripts — the things run by hand during development and on camera during the demo. Each
one is a thin entry point over logic that lives elsewhere, and each prints `Description: value`.

| File | Responsibility |
|------|----------------|
| `seed_data.py` | Loads `data/seed/` through the public API — users, roles and assets. Idempotent, so it can be re-run mid-demo without a duplicate-key error |
| `break_asset_service.py` | Stops `asset-service`, drives incident creation until the breaker opens, prints each response time, then restarts the service and waits for `CIRCUIT_CLOSED`. This is the ninety seconds that earns the pattern mark |
| `capture_evidence.py` | Runs the demo workflow and writes the request/response pairs and correlated log extracts into `docs/evidence/`, so the report's screenshots are reproducible rather than hand-cropped |
| `verify_stack.py` | Pre-demo preflight: every container healthy, all three services registered in Consul, every Prometheus target UP, the gateway answering. Run this before recording, not during |

## Integration

Scripts talk to the running stack over HTTP and to Docker through the CLI. They may not import a
service package — they are outside callers, like `client/`.

Done when: `python scripts/verify_stack.py` prints an all-green summary on a freshly started stack.
