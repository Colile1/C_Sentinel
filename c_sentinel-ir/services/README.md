# services/

The three independently deployable domain services. Each has its own folder, its own Dockerfile, its
own database, and its own README specifying the files inside it.

There are exactly three. A fourth service is a design change requiring a `DECISIONS.md` entry —
see the fixed-design guard in `CLAUDE.md` section 2.

| Service | Port (direct) | Owns | Calls |
|---------|---------------|------|-------|
| `auth-service` | 8001 | Users, credentials, roles, JWT issuance | Nothing |
| `incident-service` | 8002 | Incidents, severity, status | `asset-service`, through `ResilientClient` only |
| `asset-service` | 8003 | Assets, criticality, ownership | Nothing |

The direct ports exist for inspection during development and for the demo's contrast shot. Clients
use the gateway on port 8000 and nothing else.

## The shape every service follows

Each service repeats the same internal layering, so a reader who understands one understands all
three:

```
app/
  main.py          thin wiring: create the app, install middleware, mount routers, register
  routers/         HTTP only — parse, delegate, return. No business logic.
  services/        business logic. Pure where possible; no FastAPI imports.
  repositories/    persistence. SQLAlchemy only lives here.
  models.py        SQLAlchemy tables
  schemas.py       Pydantic request and response models
tests/             unit tests for services/ and repositories/, runnable without containers
```

`app/` and `tests/` are specified by their service's README rather than carrying their own.

## The rule that must never be broken

No service may read another service's database. Cross-service data travels over HTTP through the
gateway or through `ResilientClient`. This is the Database-per-Service pattern claimed for the mark,
and a single cross-schema query destroys the claim.
