# deploy/

Everything needed to run the whole system with one command. Fifteen percent of Deliverable 1 is that
services are *independently containerised*, and the submission sheet asks for proof on camera that
Docker hosts them — separate containers, separate images, separate lifecycles.

## Files

| File | Responsibility |
|------|----------------|
| `docker-compose.yml` | The stack: Consul, three PostgreSQL containers, three services. Health checks and `depends_on: condition: service_healthy` so `up` reaches a working system unattended. Kong, Prometheus and Grafana join it at build steps 10 and 11 |
| `Dockerfile.service` | The shared multi-stage build for a FastAPI service, selected by the `SERVICE_NAME` build argument. One file rather than three near-identical ones, per the DRY rule. Build context is the repository root, because every image needs `libs/` and `requirements.lock.txt` as well as its own `app/` |
| `.env.example` | Every environment variable with a safe placeholder: per-service database name, user and password (the `DATABASE_URL` is assembled from these three in `docker-compose.yml`, so no connection string is checked in), `JWT_SECRET`, token expiry, Consul address, log level, the resilience thresholds. Copied to `.env`, which is git-ignored; replace every `CHANGE_ME` before a real run |
| `postgres/init/` | Per-service database initialisation SQL, one file per service database — `auth-db.sql`, `incident-db.sql`, `asset-db.sql` |

## Running it

```
cp deploy/.env.example deploy/.env          # then replace every CHANGE_ME (JWT_SECRET, the *_DB_PASSWORD values)
docker compose --env-file deploy/.env -f deploy/docker-compose.yml build
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
```

### Build performance and the contended-connection failure

`Dockerfile.service` mounts a BuildKit cache at pip's download directory, shared by all three image
builds. This is the fix for the failure mode where a plain parallel `docker compose build` had
three `pip install` steps each pulling the same ~60 MB of wheels at once, saturating a modest link
and dying with `ReadTimeoutError` or a spurious "No matching distribution":

- **`docker compose build`** (no flag) — the everyday command. First run downloads each wheel once
  into the shared cache; every rebuild after that installs from disk with no network. Fast and safe
  to run in parallel.
- **`docker compose build --no-cache`** — the step-9 verification command, and the *only* one that
  reproduces a genuine clean build. `--no-cache` in Compose deliberately empties the cache mount
  too, so all wheels are re-downloaded. On a contended connection, run it serially so only one
  download is in flight at a time:

  ```
  for s in auth-service incident-service asset-service; do
    docker compose --env-file deploy/.env -f deploy/docker-compose.yml build --no-cache "$s"
  done
  ```

  A serial `--no-cache` run of all three takes about four minutes here and never times out. Use the
  plain `docker compose build` for every rebuild that is not specifically proving a from-scratch
  build.

BuildKit must be the builder for the cache mount to work; Docker Desktop and Compose v2 use it by
default, and `# syntax=docker/dockerfile:1.7` at the top of `Dockerfile.service` pins the frontend
that understands `--mount=type=cache`. The images are identical whichever way they are built.

Each service listens on its inspection port inside the container (`auth-service` 8001,
`incident-service` 8002, `asset-service` 8003), published only to `127.0.0.1`, and advertises itself
to Consul under its Compose service name so the health check and Kong both resolve it.

## Containers

| Container | Image | Port | Notes |
|-----------|-------|------|-------|
| `kong` | kong:3 | 8000 proxy, 8081 admin | DB-less, mounts `gateway/kong.yml` read-only. Admin moved off Kong's default 8001 because `auth-service` owns that port for direct inspection |
| `consul` | hashicorp/consul | 8500 | UI enabled |
| `auth-service` | built | 8001 | Own database, own image |
| `incident-service` | built | 8002 | Own database, own image |
| `asset-service` | built | 8003 | Own database, own image |
| `auth-db`, `incident-db`, `asset-db` | postgres:16 | internal | Three separate containers — see the note below |
| `prometheus` | prom/prometheus | 9090 | Mounts the scrape config |
| `grafana` | grafana/grafana | 3000 | Provisioned datasource and dashboard |

**Why three database containers.** Settled — see `DECISIONS.md` D-04. Three containers costs about
70 MB more than one container holding three databases, on a stack that runs roughly 1 GB either way,
so the resource argument does not decide it. What decides it is evidence: a marker reading
`docker compose ps` sees the separation without being asked to take it on faith, and stopping
`asset-db` on camera while the other two services keep serving is positive proof of the independent
deployment and fault isolation the non-functional requirements ask for. One shared container would
take all three services down in that same test.

## Integration

Reads `gateway/kong.yml`, `registry/consul-config.json` and `observability/`. Builds the three
services from their folders with `libs/` copied in. No host-specific paths, so a clean checkout on
another machine behaves identically.

Done when: `docker compose build --no-cache` then `docker compose up -d` reaches all-healthy from a
clean checkout, and `docker compose ps` shows each service as its own container.
