# registry/

Service discovery. Ten percent of the Deliverable 1 mark, and the submission sheet asks for the
registry to be opened on camera showing registered service instances *and their addresses*.

Consul runs as its own container. Each service registers itself at startup and deregisters on clean
shutdown, using `libs/common/registry.py` — the registration is done by the service, not by a
static configuration file, because the marker wants to see instances appear.

## Planned files

| File | Responsibility |
|------|----------------|
| `consul-config.json` | Consul agent configuration: datacenter, UI enabled, health-check interval and deregistration timeout |
| `README.md` | This specification, and the explanation of discovery the demo needs |

## How discovery works here — the explanation the mark asks for

1. Each service starts, reads its `SERVICE_NAME`, host and port from its environment, and calls
   `PUT /v1/agent/service/register` on Consul with a health-check definition pointing at its own
   `/health`.
2. Consul polls that `/health` endpoint on the interval in `consul-config.json`. An unhealthy
   instance is marked critical and, after the deregistration timeout, removed.
3. The Consul UI on `localhost:8500` lists every registered instance with its address and port —
   this is the screen shown in the demo.
4. Kong resolves upstreams by service name. In this deployment Docker Compose's own DNS resolves the
   name to the container, and Consul is the authoritative record of *which instances exist and
   whether they are healthy*. Both mechanisms are named in the report, because the specification
   accepts Docker Compose service discovery and Consul alike and asks the student to explain what is
   actually happening rather than gesture at it.
5. On shutdown the service deregisters, and the instance disappears from the UI — worth showing on
   camera immediately after `docker compose stop asset-service`.

## Integration

Depends on nothing. `libs/common/registry.py` talks to it; `gateway/` benefits from it. If Consul is
unreachable at startup, a service logs a warning and continues serving — discovery is not on the
request path, and a registry outage must not take the application down.

Done when: `GET localhost:8500/v1/agent/services` lists all three services with their addresses and
passing health checks, and stopping a service removes it from the list.
