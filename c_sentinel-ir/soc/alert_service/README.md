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
| `store.py` | `AlertStore` — create, get, list by severity, list by affected service, update status | step 16 |
| `router.py` | `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}`, `PATCH /api/v1/alerts/{id}/status` | step 16 |
| `main.py` | Thin entry point, same wiring shape as a Phase 1 service | step 16 |

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
