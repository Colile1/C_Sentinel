# tests/

Cross-service tests. Tests that belong to a single service live with that service, in
`services/<name>/tests/`, and run without containers. This folder holds only what cannot live
inside one service.

## Subfolders

| Folder | Purpose |
|--------|---------|
| `contract/` | Guards the shared contracts — the event schema and the API error shape |
| `integration/` | End-to-end tests against a running stack, marked `@pytest.mark.integration` |

## The split, and why it matters

Unit tests run in seconds with no Docker and are run on every step. Integration tests need the stack
up and are run before a commit that touches deployment, the gateway or the client. Marking the
integration tests keeps `python -m pytest` fast enough that it actually gets run.

Done when: `python -m pytest` passes with no containers running, and
`python -m pytest tests/integration -m integration` passes with the stack up.
