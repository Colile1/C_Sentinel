# soc/collector/ — **Phase 2**

Ingests the JSON event stream Phase 1 writes to stdout, validates it against `SecurityEvent`, and
stores it where rules can query it by user, source IP, service and time window.

## Files

| File | Responsibility |
|------|----------------|
| `reader.py` | `stream_events(lines) -> Iterator[SecurityEvent]` — takes any iterable of raw log lines (an open file, `sys.stdin`, the output of `docker compose logs`), skips blank lines, non-JSON lines and application log lines (those carry no `eventType`), and raises `MalformedEventError` on a line that has `eventType` but fails the schema — an off-schema key or a bad field value. `parse_event_line(raw)` does one line. |
| `store.py` | `EventStore` — in-process append and query: `append`, `extend`, `all_events`, `events_for_user(user_id, since)`, `events_for_ip(ip, since)`, `events_for_service(name, since)`, `by_correlation(correlation_id)`. Every query returns a new list, oldest event first. `since` is an optional timezone-aware UTC `datetime`. The query shapes exist because the Phase 2 rules need exactly these. `parse_timestamp` is the inverse of `common.events.utc_now_iso`. |
| `main.py` | Thin entry point: pick a source, `stream_events` through it into a fresh `EventStore`, print a `Description: value` summary (event count, distinct services, distinct correlation IDs, event types seen). No detection logic. |

## Running it

```bash
# from c_sentinel-ir/ , stack up — the default: shell out to docker compose logs
python -m soc.collector.main

# a captured file (offline evidence, tests)
python -m soc.collector.main --file docs/evidence/step12-correlated-logs.jsonl

# a live follow
docker compose -f deploy/docker-compose.yml logs -f --no-color --no-log-prefix | python -m soc.collector.main --stdin
```

## Integration

Depends on `libs/common/events.py` for the schema, and on nothing else in the tree. Read by
`soc/rules`. Never writes back into a Phase 1 service. The store is in-process, not a database — the
rules are pure functions of its contents and a clock, so persistence would add a technology without
serving step 15 or the demo (D-25).

The event schema names four emitters. `auth-service`, `incident-service` and `asset-service` write
to container stdout and the collector reads them from `docker compose logs`; `api-gateway`'s events
(`UNAUTHORISED_ACCESS`, `RATE_LIMIT_EXCEEDED`) come from Kong's own log stream. The reader validates
any of the four — a gateway-shaped line parses like any other — so wiring Kong's stream in is a
source addition at step 15, not a reader change.

Done when: a `docker compose logs` run of a stack that has served `client/demo_workflow.py` and
`client/failed_login_demo.py` leaves a store whose `by_correlation` returns the whole workflow
across all three services, and whose `events_for_user(user, since=window_start)` returns all five
failed logins for one user inside a five-minute window. Both are covered in `tests/`, and the
workflow query is captured live in `docs/evidence/step14-collector.txt`.
