# libs/common/

The shared foundation every service is built on. Its job is to make the things that must be
identical across services — the event schema, the log format, the correlation ID, the way one
service calls another — impossible to get wrong locally, because there is only one implementation.

This package is pure infrastructure with no domain knowledge. It must not know what an incident or
an asset is.

## Planned files

| File | Responsibility |
|------|----------------|
| `config.py` | `load_settings(service_name: str) -> Settings` — reads environment variables into a validated Pydantic settings object (database URL, JWT secret, Consul address, service name, port, log level). A missing required variable raises `ConfigurationError` naming the variable. No defaults for secrets. |
| `errors.py` | The typed error hierarchy: `SentinelError` base, then `ConfigurationError`, `NotFoundError`, `ValidationError`, `AuthenticationError`, `AuthorisationError`, `ConflictError`, `DependencyUnavailableError`. No framework import, so business logic may raise without depending on FastAPI. |
| `error_handlers.py` | `install_error_handlers(app)` — the single place errors become HTTP status codes, so no router writes its own. Split from `errors.py` because it needs FastAPI; see D-06. |
| `events.py` | `SecurityEvent` — the Pydantic model of the schema in `docs/soc-events.md`, and `EventType` / `Severity` enums. `build_event(...) -> SecurityEvent` is the only sanctioned way to construct one. Extra fields are forbidden; missing required fields raise. |
| `correlation.py` | The request-scoped correlation id, held in a `ContextVar` so it is per-task and safe under concurrency. `get_correlation_id`, `set_correlation_id`, `new_correlation_id`, and the `CORRELATION_ID_HEADER` constant. |
| `logging.py` | `configure_logging(service_name, log_level)` installs a JSON formatter on stdout. `emit_event(event: SecurityEvent) -> None` writes one event as a single JSON line, in the bare published schema with no log-record wrapping. The only sanctioned event writer. |
| `middleware.py` | `CorrelationIdMiddleware` reads `X-Correlation-ID`, generates one when absent, binds it for the request and echoes it on the response. `SecurityEventMiddleware` emits the `REQUEST_RECEIVED` / `REQUEST_COMPLETED` pair and `SERVICE_ERROR` on a 5xx. Split from `logging.py` because it needs Starlette; see D-06. |
| `registry.py` | `register_service(settings) -> None` and `deregister_service(settings) -> None` — Consul self-registration on startup and clean deregistration on shutdown, including the HTTP health-check definition Consul polls. When Consul is unreachable or `CONSUL_ENABLED` is false, a warning is logged and the service continues: discovery is not on the request path. |
| `http_client.py` | `ResilientClient.get(path, correlation_id, fallback)` — the only way one service may call another. Nests retry **inside** the breaker, so a retried request counts as one failure against the threshold, not one per attempt. Only transient faults (connection error, timeout, 5xx) are retried and counted; a 4xx is a healthy dependency's real answer and propagates unretried. Once open it returns the caller's declared fallback without touching the network, or raises `DependencyUnavailableError` when none was declared. |
| `circuit_events.py` | The resilience events, split from `http_client.py` so that file holds the calling policy and this one the Phase 2 contract. One `DEPENDENCY_FAILURE` per request that failed after retries, and the `CIRCUIT_OPENED` / `CIRCUIT_CLOSED` pair, emitted from a `pybreaker` listener so no state change can be missed by a call path that forgot to look. |
| `health.py` | `build_health_router(service_name, check_database)` — the shared router carrying `GET /health` (liveness plus database reachability; 200 when the database answers or the service has none, 503 when a configured database does not) and `GET /health/live` (bare liveness for the container restart policy, never touches the database). Framework-coupled, so it is its own file; see D-06. |
| `service.py` | `create_service_app(service_name, *, check_database=None, settings=None, on_startup=None, on_shutdown=None) -> FastAPI` — the one wiring all three services share: `configure_logging`, the correlation and security-event middleware, `install_error_handlers`, the Prometheus `/metrics` endpoint, the `/health` router, and a lifespan that registers with Consul on startup and deregisters on shutdown. Each service's `app/main.py` calls this and then mounts only its own routers. A mild departure from "wiring lives in `app/main.py`"; see D-08. |

## Integration

Imported by all three services and, in Phase 2, by `soc/` for the event schema. Depends only on
third-party libraries — never on a service, never on `soc`, `kg` or `rag`. `http_client.py` depends
on `circuit_events.py`, `config.py`, `correlation.py` and `errors.py`, and `circuit_events.py` on `events.py` and `logging.py`; nothing in this package depends on `http_client.py`. `service.py`
composes `config`, `logging`, `middleware`, `error_handlers`, `health` and `registry`; nothing in
this package depends on `service.py`.

Done when: a service can be started with nothing of its own but a router, and it already registers
with Consul, serves `/health`, logs JSON with a correlation ID, and emits schema-valid events.
