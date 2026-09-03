# Architecture

Written up at build step 13; the structure below is what it must contain, so nothing is discovered
the night before submission.

## The diagram

Required by the mark schedule to be professional and to show: client/frontend, API Gateway, service
registry, domain services, databases, the logging and metrics component, the container structure,
and the patterns applied. Source and export live in `docs/diagrams/`.

The request path the diagram must make obvious:

```
client  ->  Kong (8000)  ->  auth | incident | asset  ->  its own Postgres
              |                        |
              |                   incident -> asset, via retry + circuit breaker
              |
         Consul registry (health, instance addresses)
         Prometheus -> Grafana        Docker logs -> JSON security events
```

## Sections to write

1. **The domain and why microservices suit it.** Incident reporting has three genuinely separate
   concerns with different rates of change and different sensitivity — identity, incidents, assets.
2. **The services and each one's role.** One paragraph each, from the service READMEs.
3. **Endpoint design.** The conventions in `docs/api.md` and the reasoning: nouns, plural,
   consistent status codes, one error shape, JSON everywhere.
4. **The API Gateway.** What it routes, what it terminates (JWT), what it limits, what it stamps
   (correlation ID), and why a single entry point matters more as services multiply.
5. **Service registry and discovery.** The five-step explanation in `registry/README.md`, stating
   honestly what Consul does here and what Docker Compose DNS does.
6. **The two patterns.** Summarised from `docs/patterns.md`.
7. **Deployment.** The container inventory, health checks and startup ordering from
   `deploy/README.md`.
8. **Observability.** Logs, metrics, health, and the event schema.
9. **Preparation for the SOC and knowledge graph.** How `docs/soc-events.md` was designed backwards
   from Phase 2's requirements — the events, the correlation ID that links them, and the entities
   (user, service, endpoint, asset, incident) that become graph nodes with no remodelling.

## Dependency direction

Acyclic, and stated explicitly because the coding rules require it:

```
client  ->  gateway  ->  services  ->  libs/common
                             |
                             +->  its own database
soc  ->  libs/common (event schema only)
kg   ->  soc
rag  ->  kg
```

Nothing points leftward. `libs/common` imports no service. Phase 2 packages read Phase 1 output and
are never imported by it.
