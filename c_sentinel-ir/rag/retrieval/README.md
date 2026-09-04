# rag/retrieval/ — **Phase 2**

Turns a natural-language question into graph evidence. This is the half the specification cares
most about, because it is the half a student can actually explain.

## Files

| File | Responsibility |
|------|----------------|
| `intent.py` | `classify(question) -> Intent` — maps the question to one of six intents (alert explanation, response procedure, service alerts, threat mitigation, user linkage, dependency impact) plus its extracted entity id. A keyword scoring table: each intent owns a set of phrases, a question scores one point per phrase present, highest score wins, ties break on declaration order. Deterministic and unit-testable |
| `cypher_builder.py` | `build_query(intent) -> tuple[str, dict]` — the intent's parameterised Cypher, taken from the `kg/cypher` catalogue. Parameters are bound, never interpolated |
| `retriever.py` | `retrieve(question, runner) -> Evidence` — classify, build, run, shape. One pure `_shape_*` function per query turns its rows into nodes and relationships; `runner` is injectable so everything but the live tests runs with no Neo4j |
| `evidence.py` | `Evidence`, `EvidenceNode`, `EvidenceRelationship` — the structured retrieval result, and `render()`, which prints the four things the specification requires shown: retrieved nodes, retrieved relationships, source documents, and the retrieval method |

## The three steps, in order

1. `intent.classify` — which question is this, and what is it about?
2. `cypher_builder.build_query` — which of the five demonstrated queries answers it?
3. `retriever.retrieve` — run it, and shape the rows into evidence.

Only step 3 needs a database, which is why the shapers are pure functions and the mapping from
"what the query returned" to "what the answer may claim" is tested against fixture rows.

## Two properties worth stating

- **Parameters are bound.** An entity id arrives from a user's question, so interpolating it into
  the query text would put user input into Cypher. `test_the_entity_id_is_bound_never_interpolated`
  asserts the id appears in the parameter dict and never in the query text.
- **The queries are the step-18 ones.** Nothing here writes new Cypher. The queries the marker sees
  demonstrated at step 18 are the queries the RAG layer runs at step 19, so there is one set to
  explain and none that can drift from the verified one.

## Integration

Reads `kg/cypher/queries.py` and `kg/loader/connection.py`. Read by `rag/generation`. Knows nothing
about how answers are worded.

Done when: each supported question type returns a non-empty `Evidence` on the seeded graph, and an
unsupported question returns an empty `Evidence` with a clear reason rather than a guess. **Done** —
`rag/tests/test_live_answers.py` asserts both halves against a live Neo4j.
