# rag/ — **Phase 2**

Retrieval-augmented generation over the knowledge graph. A user asks a security question in plain
English; the system retrieves the relevant subgraph and produces an answer whose every claim is
backed by a node or relationship it shows alongside.

The specification is emphatic on two points: the answer must be grounded in evidence retrieved from
the graph, and the student must be able to explain the retrieval process rather than merely call a
model. The design here follows Option A, Cypher-based GraphRAG, because its retrieval step is a
query the student can read out loud.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `retrieval/` | Question to Cypher to subgraph |
| `generation/` | Subgraph to answer, with the evidence attached |

## The questions it must answer

Why was this alert created? Which services are affected by this incident? What controls can mitigate
this threat? Which users are linked to repeated failed logins? What is the likely impact if this
service fails? What response procedure should be followed?

## Integration

Reads `kg/` and nothing else. Never queries a Phase 1 database directly — if the graph does not know
something, the honest answer is that the graph does not know it.

Done when: "Why was this alert created and what should be done?" returns an answer in which every
claim maps to a displayed retrieved node or relationship.
