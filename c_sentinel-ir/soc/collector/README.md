# soc/collector/ — **Phase 2**

Ingests the JSON event stream Phase 1 writes to stdout, validates it against `SecurityEvent`, and
stores it where rules can query it by user, source IP, service and time window.

## Planned files

| File | Responsibility |
|------|----------------|
| `reader.py` | `stream_events(source) -> Iterator[SecurityEvent]` — reads newline-delimited JSON from Docker logs or a file, skips non-event log lines, and raises on a line that claims to be an event but fails validation |
| `store.py` | `EventStore` — append and query: `events_for_user(user_id, since)`, `events_for_ip(ip, since)`, `events_for_service(name, since)`, `by_correlation(correlation_id)`. The query shapes exist because the rules need exactly these |
| `main.py` | Thin entry point: stream, validate, store. No detection logic |

## Integration

Depends on `libs/common/events.py` for the schema. Read by `soc/rules`. Never writes back into a
Phase 1 service.

Done when: one `client/demo_workflow.py` run plus one `client/failed_login_demo.py` run leaves a
store that can return all five failed logins for a single user inside a five-minute window.
