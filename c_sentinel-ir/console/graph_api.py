"""
graph_api.py - the knowledge graph and GraphRAG screens' backend.

Four things, each delegating to the module that already owns it:
  - the six demonstrated Cypher queries    kg.cypher.queries + run_query
  - a per-label node count                 one read-only Cypher statement
  - reloading the graph                    kg.loader.main.main, as its CLI runs
  - asking a question                      rag.generation.main.answer_question

Every call checks Neo4j's Bolt port first (`bolt_reachable`), so with no graph
running the UI gets a plain 503 in a second rather than waiting out the
driver's connection timeout.

Author: Colile
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import asdict
from datetime import date, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from common.errors import NotFoundError, ValidationError

from kg.cypher.queries import QUERIES, get_query
from kg.loader.connection import run_query
from rag.generation.main import DEMO_QUESTION, _first_alert_id, answer_question
from rag.retrieval.intent import INTENTS

from console.settings import CAPTURED_EVENTS
from console.stack_status import bolt_reachable

router = APIRouter(prefix="/console/api/graph", tags=["graph"])

_NEO4J_DOWN = {
    "error": "NEO4J_UNREACHABLE",
    "message": "Neo4j is not reachable on NEO4J_URI. Start the stack (start.bat) "
    "and load the graph, then try again.",
    "details": {},
}


class LoadRequest(BaseModel):
    """Body of a graph load: the event source, and whether to only count."""

    source: str = "capture"
    dry_run: bool = False


class Question(BaseModel):
    """Body of a GraphRAG question."""

    question: str
    use_llm: bool = False


def _plain(value: Any) -> Any:
    """
    Purpose: make a Neo4j row JSON-safe - temporal and graph types become
             strings, containers are walked.
    Inputs:  value - anything a query returned.
    Output:  a value `json` can encode.
    """
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _require_graph() -> JSONResponse | None:
    """
    Purpose: the shared Neo4j guard.
    Inputs:  none.
    Output:  a 503 response to return when the graph is down, else None.
    """
    return None if bolt_reachable() else JSONResponse(_NEO4J_DOWN, status_code=503)


@router.get("/queries", summary="The six demonstrated queries")
def list_queries() -> list[dict[str, Any]]:
    """
    Purpose: the query catalogue with each query's Cypher, so the UI can show
             what it is about to run.
    Inputs:  none.
    Output:  a JSON array of {key, question, parameters, cypher}.
    """
    return [
        {
            "key": query.key,
            "question": query.question,
            "parameters": list(query.parameters),
            "cypher": query.text(),
        }
        for query in QUERIES
    ]


@router.get("/queries/{key}", summary="Run one demonstrated query")
def run_named_query(key: str, request: Request) -> Any:
    """
    Purpose: run one of the six queries with its parameters from the query
             string - the same validation `kg.cypher.graph_service` applies.
    Inputs:  key - the query key; the query string carries its parameters.
    Output:  200 with the rows, 422 on a blank parameter, 503 with no Neo4j.
    """
    query = get_query(key)
    parameters = {name: request.query_params.get(name, "") for name in query.parameters}
    for name, value in parameters.items():
        if not value.strip():
            raise ValidationError(
                f"query {key!r} requires a non-empty {name!r}", {"parameter": name}
            )
    if (down := _require_graph()) is not None:
        return down
    return _plain(run_query(query.text(), **parameters))


@router.get("/summary", summary="Node counts per label")
def graph_summary() -> Any:
    """
    Purpose: how much the graph holds, by label, for the graph screen header.
    Inputs:  none.
    Output:  {labels: [{label, count}], relationships: n, services: [...]} or
             a 503.
    """
    if (down := _require_graph()) is not None:
        return down
    labels = run_query(
        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS count ORDER BY count DESC"
    )
    relationships = run_query("MATCH ()-[r]->() RETURN count(r) AS count")
    services = run_query("MATCH (s:Service) RETURN s.name AS name ORDER BY name")
    return {
        "labels": _plain(labels),
        "relationships": relationships[0]["count"] if relationships else 0,
        "services": [row["name"] for row in services],
    }


@router.get("/alerts", summary="The alerts the graph holds")
def graph_alerts() -> Any:
    """
    Purpose: the Alert nodes in the graph, for the alert pickers on the query
             and GraphRAG screens. These are the loader's alerts, which carry
             their own ids, not the ones a console detection run minted.
    Inputs:  none.
    Output:  a JSON array of {alertId, ruleName, severity} or a 503.
    """
    if (down := _require_graph()) is not None:
        return down
    return _plain(run_query(
        "MATCH (a:Alert) RETURN a.alertId AS alertId, a.ruleName AS ruleName, "
        "a.severity AS severity ORDER BY a.ruleName, alertId"
    ))


#: An alert's neighbourhood, as distinct relationships: everything one hop
#: from the alert, the threat's own links (controls, runbooks, targeted
#: service, vulnerabilities - but not other alerts), and the users behind the
#: events. The two chains of Phase 2 demo section 4 in one picture.
_NEIGHBOURHOOD = """
MATCH (a:Alert {alertId: $alertId})
CALL {
  WITH a MATCH (a)-[r]-() RETURN r
  UNION
  WITH a MATCH (a)-[:INDICATES]->(:Threat)-[r]-(m) WHERE NOT m:Alert RETURN r
  UNION
  WITH a MATCH (a)<-[:CREATED_ALERT]-(:Event)<-[r:TRIGGERED]-(:User) RETURN r
}
WITH DISTINCT r
RETURN elementId(startNode(r)) AS source, labels(startNode(r))[0] AS sourceLabel,
       properties(startNode(r)) AS sourceProps, type(r) AS type,
       elementId(endNode(r)) AS target, labels(endNode(r))[0] AS targetLabel,
       properties(endNode(r)) AS targetProps
LIMIT 200
"""


def _caption(label: str, properties: dict[str, Any]) -> str:
    """
    Purpose: a short display name for a node - a readable name where the
             node has one, else its natural key.
    Inputs:  label - the node label; properties - its properties.
    Output:  the caption string.
    """
    from kg.model.graph_model import NODE_KEYS

    for name in ("name", "title", "username"):
        if properties.get(name):
            return str(properties[name])
    return str(properties.get(NODE_KEYS.get(label, ""), label))


@router.get("/neighbourhood", summary="An alert's neighbourhood, for drawing")
def neighbourhood(alert_id: Annotated[str, Query(alias="alertId")] = "") -> Any:
    """
    Purpose: the nodes and relationships around one alert, shaped for the
             graph picture on the Knowledge graph screen.
    Inputs:  alertId - the alert at the centre.
    Output:  {centre, nodes: [{id, label, caption, properties}],
             links: [{source, target, type}]}; 422 on a blank id, 404 when no
             alert carries it, 503 with no Neo4j.
    """
    if not alert_id.strip():
        raise ValidationError("an alertId is required", {"parameter": "alertId"})
    if (down := _require_graph()) is not None:
        return down
    rows = run_query(_NEIGHBOURHOOD, alertId=alert_id)
    if not rows:
        raise NotFoundError(f"no alert {alert_id!r} in the graph", {"alertId": alert_id})
    nodes: dict[str, dict[str, Any]] = {}
    links = []
    for row in rows:
        for end in ("source", "target"):
            label, properties = row[f"{end}Label"], _plain(row[f"{end}Props"])
            nodes.setdefault(row[end], {
                "id": row[end], "label": label,
                "caption": _caption(label, properties), "properties": properties,
            })
        links.append({"source": row["source"], "target": row["target"], "type": row["type"]})
    centre = next(n["id"] for n in nodes.values()
                  if n["label"] == "Alert" and n["properties"].get("alertId") == alert_id)
    return {"centre": centre, "nodes": list(nodes.values()), "links": links}


@router.post("/load", summary="Reload the knowledge graph")
def load_graph(request: LoadRequest) -> Any:
    """
    Purpose: run the graph loader exactly as `python -m kg.loader.main` does,
             capturing what it prints.
    Inputs:  request - source (capture or live) and dry_run.
    Output:  {exitCode, output}. A dry run needs no Neo4j; a real load
             returns a 503 first when the graph is down.
    """
    from kg.loader.main import main as loader_main

    argv = ["--file", str(CAPTURED_EVENTS)] if request.source == "capture" else []
    if request.dry_run:
        argv.append("--dry-run")
    elif (down := _require_graph()) is not None:
        return down
    buffer = io.StringIO()
    with contextlib.redirect_stdout(buffer), contextlib.redirect_stderr(buffer):
        exit_code = loader_main(argv)
    return {"exitCode": exit_code, "output": buffer.getvalue()}


@router.get("/rag/questions", summary="Supported GraphRAG question shapes")
def rag_questions() -> list[dict[str, str]]:
    """
    Purpose: one example phrase per supported intent, from the intent table
             itself, so the suggestion chips cannot drift from the retriever.
    Inputs:  none.
    Output:  a JSON array of {intent, phrase}.
    """
    return [{"intent": rule.name.value, "phrase": rule.phrases[0]} for rule in INTENTS]


@router.get("/rag/demo-question", summary="The step-19 demo question")
def rag_demo_question() -> Any:
    """
    Purpose: the demo question with a real alert id from the graph filled in.
    Inputs:  none.
    Output:  {question} or a 503 when the graph is down or holds no alert.
    """
    if (down := _require_graph()) is not None:
        return down
    alert_id = _first_alert_id()
    if alert_id is None:
        return JSONResponse(
            {"error": "NO_ALERTS", "message": "The graph holds no alert yet. "
             "Load the graph first.", "details": {}},
            status_code=503,
        )
    return {"question": DEMO_QUESTION.format(alert_id=alert_id)}


@router.post("/rag/ask", summary="Ask the GraphRAG interface a question")
def rag_ask(request: Question) -> Any:
    """
    Purpose: a question in, a grounded answer and its full evidence out - the
             four evidence parts the specification requires, as JSON.
    Inputs:  request - the question and whether to try the LLM phrasing.
    Output:  {question, text, method, grounded, evidence: {...}} or a 503.
    """
    if not request.question.strip():
        raise ValidationError("a question is required", {"field": "question"})
    if (down := _require_graph()) is not None:
        return down
    answer = answer_question(request.question, use_llm=request.use_llm)
    return {
        "question": answer.question,
        "text": answer.text,
        "method": answer.method,
        "grounded": answer.is_grounded,
        "rendered": answer.render(),
        "evidence": _plain(asdict(answer.evidence)),
    }
