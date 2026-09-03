# soc/alert-service/ — **Phase 2**

Turns rule firings into alerts and makes them queryable. The alert schema is fixed by the Phase 2
specification and reproduced exactly.

## The alert schema

`alertId`, `timestamp`, `ruleName`, `severity`, `status`, `description`, `relatedEvents`,
`affectedService`, `affectedUser`, `affectedEntity`, `recommendedAction`.

`relatedEvents` holds real `eventId` values that resolve in the event store — this is what lets the
knowledge graph link an alert back to the events that caused it, and what lets the RAG answer cite
evidence rather than assert.

## Planned files

| File | Responsibility |
|------|----------------|
| `models.py` | `Alert` — the Pydantic model of the schema above, plus the `AlertStatus` enum (OPEN, ACKNOWLEDGED, CLOSED) |
| `store.py` | `AlertStore` — create, get, list by severity, list by affected service, update status |
| `router.py` | `GET /api/v1/alerts`, `GET /api/v1/alerts/{id}`, `PATCH /api/v1/alerts/{id}/status` |
| `main.py` | Thin entry point, same wiring shape as a Phase 1 service |

## Integration

Written to by `soc/rules`. Read by `kg/loader` when projecting alerts into the graph, and by
`rag/retrieval` when answering questions about a specific alert.

Done when: a fired rule produces an alert whose `relatedEvents` all resolve to stored events.
