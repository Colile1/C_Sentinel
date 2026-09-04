# soc/alert_service/ — **Phase 2**

> The folder is `alert_service`, with an underscore. `soc` is one importable Python package, so
> `soc.alert-service` is not a name that can be written; the services under `services/` avoid this
> only because each is its own rootdir with an inner `app/` package. Renamed at step 15, D-28.

Turns rule firings into alerts and makes them queryable. The alert schema is fixed by the Phase 2
specification and reproduced exactly.

## The alert schema

`alertId`, `timestamp`, `ruleName`, `severity`, `status`, `description`, `relatedEvents`,
`affectedService`, `affectedUser`, `affectedEntity`, `recommendedAction`.

`relatedEvents` holds real `eventId` values that resolve in the event store — this is what lets the
knowledge graph link an alert back to the events that caused it, and what lets the RAG answer cite
evidence rather than assert.

## Files

| File | Responsibility | Status |
|------|----------------|--------|
| `models.py` | `Alert` — the Pydantic model of the schema above, plus the `AlertStatus` enum (OPEN, ACKNOWLEDGED, CLOSED) and `new_alert_id()` | **built at step 15** |
| `store.py` | `AlertStore` — `add`/`extend`, `get`, `list` by severity, affected service and status, `set_status` (by replacement, not mutation), `resolve_events` | **built at step 16** |
| `dependencies.py` | `get_alert_store()` — the one process-wide `AlertStore` the API serves from, overridable in tests | **built at step 16** |
| `schemas.py` | `StatusChange` — the body of the status-change request; responses are the schema dict itself | **built at step 16** |
| `router.py` | `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}`, `PATCH /api/v1/alerts/{id}/status` | **built at step 16** |
| `main.py` | Thin entry point: shared JSON logging, shared typed-error handlers, a liveness `/health`, the alert router. No database, no Consul — the SOC layer is an operator tool, not a member of the request path (D-30) | **built at step 16** |

## The store is in-process

`AlertStore` mirrors `soc.collector.store.EventStore`: an append-and-query structure held for
the process, no database. The rules are pure functions of an event store and a clock, and the
alert API is a pure function of an alert store, so persistence would add a technology without
serving step 16 or the demo — the same reasoning as D-25. `soc.rules.main` fills the store: after
evaluating the catalogue it calls `persist_alerts`, which refuses any alert whose `relatedEvents`
do not all resolve to events in the collector's store and then `extend`s the rest in.

`Alert` is frozen, so `set_status` replaces the stored record with a `model_copy` carrying the new
status and the same id — an alert stays a faithful record of what the rule saw while still moving
through OPEN → ACKNOWLEDGED → CLOSED.

`models.py` was built one step early, at step 15, because the rules must return something and an
alert is a contract shared by the rules that raise it, the API that serves it and the graph loader
that projects it — the same reason the security event schema lives in `libs/common` rather than in
whichever service emits first. The alternative was a throwaway `Finding` type and a translation
layer at step 16. Logged as D-29.

`Alert` mirrors `common.events.SecurityEvent` deliberately: `extra="forbid"`, `frozen=True`,
camelCase serialization aliases, and an `alt-`+12-hex identifier alongside the event schema's
`evt-`. Two validators earn their place — `relatedEvents` may not be empty, because an alert citing
nothing is an assertion rather than evidence, and the id format is checked so the graph loader can
parse every one.

## Integration

Written to by `soc/rules`, which imports `models.py` only. Read by `kg/loader` when projecting
alerts into the graph, and by `rag/retrieval` when answering questions about a specific alert.

Done when: a fired rule produces an alert whose `relatedEvents` all resolve to stored events.
