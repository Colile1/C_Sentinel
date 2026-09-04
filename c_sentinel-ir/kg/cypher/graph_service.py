"""
graph_service.py - a small HTTP service over the five demonstrated queries.

Thin by design: the shared JSON logging and typed-error handlers, a liveness
`/health`, and one GET endpoint per query plus `GET /api/v1/graph/queries` that
lists them. No database of its own - it reads Neo4j through
`kg.loader.connection.run_query`, the one place connection details live. Not on
the request path and not registered with Consul, for the same reason as the
alert service (D-30).

The endpoints exist so the queries are reachable from `rag/retrieval` at step 19
and from a browser during the demo.

Run locally with:
    uvicorn kg.cypher.graph_service:app --port 8008
from c_sentinel-ir/, with NEO4J_* set.

Author: Colile
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Query as QueryParam

from common.error_handlers import install_error_handlers
from common.errors import ValidationError
from common.health import build_health_router
from common.logging import configure_logging

from kg.cypher.queries import QUERIES, get_query
from kg.loader.connection import run_query

_SERVICE_NAME = "graph-service"

configure_logging(_SERVICE_NAME)

app = FastAPI(title="Sentinel-IR graph-service", version="0.1.0")
install_error_handlers(app)
app.include_router(build_health_router(_SERVICE_NAME))


@app.get("/api/v1/graph/queries", summary="List the demonstrated queries")
def list_queries() -> list[dict[str, Any]]:
    """
    Purpose: the catalogue of the five queries - key, question and required
             parameters - so a caller knows what to ask for.
    Inputs:  none.
    Output:  200 with a JSON array.
    """
    return [
        {"key": q.key, "question": q.question, "parameters": list(q.parameters)}
        for q in QUERIES
    ]


@app.get("/api/v1/graph/alerts", summary="Alerts affecting a service (q1)")
def alerts_for_service(
    service: Annotated[str, QueryParam(description="Service name")],
) -> list[dict[str, Any]]:
    """Purpose: q1. Inputs: service. Output: 200 with the matching alerts."""
    return _run("alerts_for_service", service=service)


@app.get("/api/v1/graph/users-high-severity", summary="Users on HIGH/CRITICAL alerts (q2)")
def users_high_severity() -> list[dict[str, Any]]:
    """Purpose: q2. Inputs: none. Output: 200 with the users and evidence."""
    return _run("users_high_severity")


@app.get("/api/v1/graph/threats", summary="Threats targeting a service (q3)")
def threats_for_service(
    service: Annotated[str, QueryParam(description="Service name")],
) -> list[dict[str, Any]]:
    """Purpose: q3. Inputs: service. Output: 200 with techniques and controls."""
    return _run("threats_for_service", service=service)


@app.get("/api/v1/graph/alert-controls", summary="Controls and runbooks for an alert (q4)")
def controls_for_alert(
    alert_id: Annotated[str, QueryParam(alias="alertId", description="Alert id")],
) -> list[dict[str, Any]]:
    """Purpose: q4. Inputs: alertId. Output: 200 with controls and runbooks."""
    return _run("controls_for_alert", alertId=alert_id)


@app.get("/api/v1/graph/dependency-impact", summary="Blast radius of a failing service (q5)")
def dependency_impact(
    service: Annotated[str, QueryParam(description="The failing service")],
) -> list[dict[str, Any]]:
    """Purpose: q5. Inputs: service. Output: 200 with the impacted services."""
    return _run("dependency_impact", service=service)


def _run(key: str, **parameters: Any) -> list[dict[str, Any]]:
    """
    Purpose: run one named query with its parameters and return the rows.
    Inputs:  key - the query key; parameters - its named parameters.
    Output:  a list of row dicts.
    Raises:  `ValidationError` (422) when a required parameter is blank.
    """
    query = get_query(key)
    for name in query.parameters:
        if not str(parameters.get(name, "")).strip():
            raise ValidationError(
                f"query {key!r} requires a non-empty {name!r}", {"parameter": name}
            )
    return run_query(query.text(), **parameters)
