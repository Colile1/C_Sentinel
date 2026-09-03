# tests/integration/

End-to-end tests against a running stack. All marked `@pytest.mark.integration` so they stay out of
the fast unit run.

| File | Responsibility |
|------|----------------|
| `conftest.py` | Fixtures: the gateway base URL from the environment, a logged-in bearer token, a per-test correlation ID, and a readiness wait that polls `/health` rather than sleeping |
| `test_workflow.py` | The marked business workflow: log in, list assets, create an incident against one, read it back, escalate it. Every request goes through the gateway |
| `test_gateway_enforcement.py` | A request without a token to a protected route returns 401 and the upstream service log stays silent — the gateway blocked it, not the service. Exceeding the rate limit returns 429 |
| `test_registry.py` | All three services appear in Consul with passing health checks |
| `test_circuit_breaker.py` | With `asset-service` stopped, incident creation still succeeds with the degraded asset summary, and `CIRCUIT_OPENED` appears in the log. The pattern demonstrated as a test, not just on camera |
| `test_correlation.py` | One correlation ID sent by the client is found in all three services' logs for the same workflow |

`test_circuit_breaker.py` stops and starts a container, so it runs last and restores state in a
teardown that runs even on failure.

Done when: the whole file set passes against a freshly built stack, twice in a row.
