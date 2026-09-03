# rag/retrieval/ — **Phase 2**

Turns a natural-language question into graph evidence. This is the half the specification cares
most about, because it is the half a student can actually explain.

## Planned files

| File | Responsibility |
|------|----------------|
| `intent.py` | `classify(question) -> Intent` — maps the question to one of the supported intents (alert explanation, incident impact, threat mitigation, user linkage, dependency impact, response procedure) plus its extracted entity id. Rule- and keyword-based; deterministic and unit-testable |
| `cypher_builder.py` | `build_query(intent, entity_id) -> tuple[str, dict]` — the intent's parameterised Cypher. Parameters only, never string interpolation into a query |
| `retriever.py` | `retrieve(question) -> Evidence` — runs the query and returns an `Evidence` object holding the nodes, the relationships and the source documents found |
| `evidence.py` | `Evidence` — the structured retrieval result, and `render()` for display. The specification requires retrieved nodes, retrieved relationships, source documents and an explanation of the retrieval method to be shown |

## Integration

Reads `kg/cypher` and `kg/loader/connection.py`. Read by `rag/generation`. Knows nothing about how
answers are worded.

Done when: each supported question type returns a non-empty `Evidence` on the seeded graph, and an
unsupported question returns an empty `Evidence` with a clear reason rather than a guess.
