# observability/logging/

The centralised logging contract and the commands used to demonstrate it.

| File | Responsibility |
|------|----------------|
| `log_query_examples.md` | The exact shell commands run on camera: follow all services, filter one correlation ID across services, filter `AUTH_FAILED` events, show a circuit-breaker state change |

## The contract

One log line is one JSON object. Operational lines carry `level`, `service`, `timestamp`, `message`
and `correlationId`. Security-relevant lines are a full `SecurityEvent` from `libs/common/events.py`
and carry `eventType` — that field is what separates a log line from an event, and it is what
Phase 2's collector filters on.

No service may use `print`, and no service may format a log line by hand. The single formatter in
`libs/common/logging.py` is the reason the stream is parseable at all.

Done when: piping `docker compose logs` through `jq` succeeds on every line, and filtering by one
correlation ID returns the whole workflow across three services.
