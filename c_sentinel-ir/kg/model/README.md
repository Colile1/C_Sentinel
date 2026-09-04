# kg/model/ — **Phase 2**

The graph schema, as code and as documentation.

## Files

| File | Responsibility | Status |
|------|----------------|--------|
| `schema.cypher` | Constraints and indexes: a uniqueness constraint per node label's natural key, and indexes on the properties the five demonstrated queries filter by | **built at step 17** |
| `graph_model.py` | The model as importable data — `NODE_KEYS`, `NODE_LABELS`, `RELATIONSHIPS`, `RELATIONSHIP_TYPES`. The loaders and `kg/cypher` check themselves against this; `kg/loader/tests` asserts no drift from the loaders | **built at step 17** |
| `graph_model.md` | The model as a table — node label, its properties, and every relationship it participates in — plus the diagram. This is the "knowledge graph model" the specification requires as a deliverable | **built at step 17** |

## Required node labels

`User`, `Service`, `Endpoint`, `Asset`, `Event`, `Alert`, `Incident`, `Threat`, `Control`,
`Vulnerability`, `Role`, `Document`.

## Relationship types

```
(:User)-[:TRIGGERED]->(:Event)
(:Event)-[:GENERATED_BY]->(:Service)
(:Event)-[:TARGETED]->(:Endpoint)
(:Event)-[:CREATED_ALERT]->(:Alert)
(:Alert)-[:INDICATES]->(:Threat)
(:Threat)-[:TARGETS]->(:Service)
(:Threat)-[:EXPLOITS]->(:Vulnerability)
(:Threat)-[:SUBTECHNIQUE_OF]->(:Threat)
(:Control)-[:MITIGATES]->(:Threat)
(:Incident)-[:CONTAINS]->(:Alert)
(:Service)-[:DEPENDS_ON]->(:Service)
(:Service)-[:EXPOSES]->(:Endpoint)
(:User)-[:HAS_ROLE]->(:Role)
(:Document)-[:DESCRIBES]->(:Control)
(:Document)-[:SUPPORTS_RESPONSE_TO]->(:Threat)
```

Done when: `schema.cypher` applies cleanly to an empty database and `graph_model.md` documents every
label and relationship actually created by the loaders — with no drift between the two.
