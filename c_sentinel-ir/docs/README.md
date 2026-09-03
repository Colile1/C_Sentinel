# docs/

Everything the marker reads and everything a future session needs that is not code.

| Path | Purpose |
|------|---------|
| `build-order.md` | The numbered build steps and the verification that closes each. The spine of the project |
| `soc-events.md` | **The event schema contract.** Fixed at build step 3; every service obeys it; Phase 2 depends on it |
| `api.md` | The endpoint catalogue: base URL, every route, method, request body, response body, auth requirement, status codes |
| `architecture.md` | The architecture in prose, with the diagram and the decisions behind it |
| `patterns.md` | The two claimed patterns: what each is, how it is implemented here, where the code lives, and how the demo proves it fires |
| `specs/` | The original course specification PDFs, kept in-repo so the source of truth travels with the project |
| `report/` | The submitted document and the demo script |
| `diagrams/` | Diagram sources and exports |
| `evidence/` | Screenshots and captures taken *during* the build, for the report and the video |

`diagrams/` and `evidence/` hold artefacts rather than specifications and are documented by this
README rather than each carrying their own.

## The rule for this folder

Documentation is written at the step that produces it, not at the end. `docs/api.md` gains a section
when an endpoint is built, not in step 13. Step 13 assembles and polishes; it does not discover.
