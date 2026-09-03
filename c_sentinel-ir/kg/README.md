# kg/ — **Phase 2**

The Neo4j security knowledge graph. It holds three kinds of knowledge in one connected structure:
what the application *is*, what *happened* in it, and what is *known* about the threats those
happenings suggest.

The specification requires data from three sources, and that is exactly the split above:
application structure from Phase 1, events and alerts from Phase 2, and formal security knowledge
such as MITRE ATT&CK techniques, controls and response procedures.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `model/` | The graph schema: node labels, relationship types, properties, constraints |
| `loader/` | One loader per source, plus the orchestrator |
| `cypher/` | The demonstrated queries and the graph service API |

## Why the Phase 1 design makes this cheap

Every required node type already exists as a first-class thing in Phase 1: `User` from auth-service,
`Service` and `Endpoint` from the gateway routes and the registry, `Asset` from asset-service,
`Event` from the event schema, `Incident` from incident-service. Only `Alert`, `Threat`, `Control`,
`Vulnerability` and `Document` are new in Phase 2. That was the point of choosing this domain.

## Integration

Reads `soc/`'s event and alert stores and Phase 1's configuration. Read by `rag/`. Imports no Phase
1 service.

Done when: every required node label is present, the service dependency edge reflects the real
`incident -> asset` call, and MITRE T1110 with its controls is loaded and reachable from a
failed-login alert.
