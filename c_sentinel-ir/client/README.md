# client/

The "very basic client" the mark schedule asks for. Twenty-five percent of Deliverable 1 is that the
system executes the required business functionality *from a client*, so this folder is not a
convenience — it is the thing being marked.

Every request it makes goes to `http://localhost:8000`, the gateway. It never calls a service port
directly. That is deliberate: the endpoint addresses printed by this client are the evidence the
submission sheet asks for.

## Files

Built at build step 12.

| File | Responsibility |
|------|----------------|
| `demo_workflow.py` | `main()` — runs the complete marked workflow end to end and prints each step as `Description: value`, including the full URL called and the correlation ID returned. Login, list assets, create an incident against an asset, read it back, escalate its severity. One correlation ID for the whole run |
| `api_client.py` | `ApiClient` — a thin wrapper over httpx holding the base URL and the bearer token. One method per endpoint. No business logic, no retry (resilience is a server-side concern and belongs to `libs/common/http_client.py`). Reads `GATEWAY_URL` from the environment, defaulting to `http://localhost:8000/api/v1` |
| `failed_login_demo.py` | Drives five consecutive failed logins, then a successful one. Harmless in Phase 1 where it demonstrates auth event capture; in Phase 2 it is the attack that fires detection Rule 1 |

The admin username and password come from `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD`
in the environment (defaulting to `admin` and a placeholder), matching what auth-service seeds at
startup (D-23) — no credential is written into these files.

## Integration

Depends on the running stack and nothing in this repository — it is an outside caller by design, so
it may not import `libs/common` or any service package. It talks HTTP only.

Called by hand during the demo, and by `tests/integration` in build step 12.

Done when: `python client/demo_workflow.py` completes against a freshly started stack, prints a URL
on `localhost:8000` for every step, and the correlation ID it prints can be grepped out of all three
services' container logs.
