# deploy/

Everything needed to run the whole system with one command. Fifteen percent of Deliverable 1 is that
services are *independently containerised*, and the submission sheet asks for proof on camera that
Docker hosts them — separate containers, separate images, separate lifecycles.

## Planned files

| File | Responsibility |
|------|----------------|
| `docker-compose.yml` | The full stack: Kong gateway, Consul, three services, their databases, Prometheus, Grafana. Health checks and `depends_on` conditions so `up` reaches a working system unattended |
| `Dockerfile.service` | The shared multi-stage build for a FastAPI service, parameterised by build argument. One file rather than three near-identical ones, per the DRY rule |
| `.env.example` | Every environment variable with a safe placeholder: database credentials, `JWT_SECRET`, token expiry, Consul address, log level, Grafana admin password. Copied to `.env`, which is git-ignored |
| `postgres/init/` | Per-service database initialisation SQL, one file per service database |

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
