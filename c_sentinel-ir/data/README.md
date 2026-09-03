# data/

Demo data and runtime state.

| Path | Purpose |
|------|---------|
| `seed/` | Version-controlled JSON seed files loaded by `scripts/seed_data.py`: users with roles, and an asset register |
| `postgres/`, `neo4j/` | Docker volume mounts for database state. Git-ignored, never committed, never edited by hand |

## What the seed data must contain

The specification asks for enough data to demonstrate meaningful interaction between services. The
minimum that makes the demo tell a story:

- An admin user and two analyst users, so role-restricted endpoints can be shown succeeding and
  failing.
- Six or so assets across types and criticalities, including at least one CRITICAL asset — reading
  it emits the `ASSET_ACCESSED` event that Phase 2 treats as sensitive-asset access.
- No pre-loaded incidents. Incidents are created live on camera, because a workflow the marker
  watches happen is worth more than a table that was already populated.

Seed data is loaded through the public API, not by SQL insert. If seeding needs a direct database
write, an endpoint is missing.

Done when: `python scripts/seed_data.py` on a fresh stack completes twice in a row with no error and
no duplicated rows.
