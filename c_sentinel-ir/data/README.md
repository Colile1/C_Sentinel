# data/

Demo data and runtime state.

| Path | Purpose |
|------|---------|
| `seed/` | Version-controlled JSON seed files loaded by `scripts/seed_data.py`: users with roles, and an asset register |
| `postgres/`, `neo4j/` | Docker volume mounts for database state. Git-ignored, never committed, never edited by hand |

## What the seed data must contain

The specification asks for enough data to demonstrate meaningful interaction between services. The
minimum that makes the demo tell a story:

- Two analyst users, so role-restricted endpoints can be shown succeeding and failing. The **admin**
  is not in `seed/` — it is the one account that cannot be created through the API it would be
  loaded by (that route needs an admin token), so auth-service seeds it at startup from
  `BOOTSTRAP_ADMIN_*` (D-23). `scripts/seed_data.py` logs in as that admin to create everything
  here.
- Six assets across types and criticalities, including at least one CRITICAL asset — reading it
  emits the `ASSET_ACCESSED` event that Phase 2 treats as sensitive-asset access. `seed/assets.json`
  ships six, two of them CRITICAL.
- No pre-loaded incidents. Incidents are created live on camera, because a workflow the marker
  watches happen is worth more than a table that was already populated.

Seed data is loaded through the public API, not by SQL insert. If seeding needs a direct database
write, an endpoint is missing. The single exception is the bootstrap admin above, which auth-service
itself creates at startup because no API path to the first admin can exist — see `DECISIONS.md`
D-23.

Done when: `python scripts/seed_data.py` on a fresh stack completes twice in a row with no error and
no duplicated rows.
