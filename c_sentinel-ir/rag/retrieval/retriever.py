"""
retriever.py - question in, `Evidence` out. The whole retrieval pipeline.

Three steps, in order, each in its own module so each can be explained and
tested alone:

  1. `intent.classify`      - which question is this, and what is it about?
  2. `cypher_builder.build` - which of the five demonstrated queries answers it?
  3. this module            - run it, and shape the rows into evidence.

Step 3 is the only part that needs a database. The row-shaping functions below
are pure - a row dict in, nodes and relationships out - so the mapping from
"what the query returned" to "what the answer may claim" is unit-tested against
fixture rows with no Neo4j running, and only the live tests need a server.

Each shaper is written against one query's RETURN clause. When a `.cypher` file
changes its returned column names, the shaper for it is the one place that
needs to follow.

Author: Colile
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from kg.loader.connection import run_query
from rag.retrieval.cypher_builder import (
    UnsupportedQuestionError,
    build_query,
    query_key_for,
)
from rag.retrieval.evidence import Evidence, EvidenceNode, EvidenceRelationship
from rag.retrieval.intent import Intent, classify

#: The signature every row shaper has: one row, its nodes and relationships.
Shaper = Callable[
    [dict[str, Any]], tuple[list[EvidenceNode], list[EvidenceRelationship]]
]


def _shape_controls_for_alert(
    row: dict[str, Any],
) -> tuple[list[EvidenceNode], list[EvidenceRelationship]]:
    """
    Purpose: shape one q4 row - the alert, the technique it indicates, and the
             controls and runbooks reached from that technique.
    Inputs:  row - a `q4_controls_for_alert.cypher` row.
    Output:  (nodes, relationships).
    """
    alert_id = row.get("alertId", "")
    technique_id = row.get("techniqueId", "")
    nodes = [
        EvidenceNode(
            "Alert",
            alert_id,
            {
                "ruleName": row.get("ruleName"),
                "recommendedAction": row.get("ruleRecommendedAction"),
            },
        ),
        EvidenceNode(
            "Threat", technique_id, {"name": row.get("technique")}
        ),
    ]
    relationships = [EvidenceRelationship(alert_id, "INDICATES", technique_id)]

    for control in _values(row.get("controls")):
        nodes.append(EvidenceNode("Control", control, key_property="name"))
        relationships.append(EvidenceRelationship(control, "MITIGATES", technique_id))
    for runbook in _values(row.get("runbooks")):
        nodes.append(EvidenceNode("Document", runbook, key_property="title"))
        relationships.append(
            EvidenceRelationship(runbook, "SUPPORTS_RESPONSE_TO", technique_id)
        )
    return nodes, relationships


def _shape_alerts_for_service(
    row: dict[str, Any],
) -> tuple[list[EvidenceNode], list[EvidenceRelationship]]:
    """
    Purpose: shape one q1 row - an alert affecting the named service.
    Inputs:  row - a `q1_alerts_for_service.cypher` row.
    Output:  (nodes, relationships). q1 matches on a property, so it retrieves
             no relationship; the evidence block honestly shows none.
    """
    node = EvidenceNode(
        "Alert",
        row.get("alertId", ""),
        {
            "ruleName": row.get("ruleName"),
            "severity": row.get("severity"),
            "status": row.get("status"),
            "description": row.get("description"),
            "recommendedAction": row.get("recommendedAction"),
            "timestamp": row.get("timestamp"),
        },
    )
    return [node], []


def _shape_threats_for_service(
    row: dict[str, Any],
) -> tuple[list[EvidenceNode], list[EvidenceRelationship]]:
    """
    Purpose: shape one q3 row - a technique targeting the service, with the
             vulnerabilities it exploits and the controls that mitigate it.
    Inputs:  row - a `q3_threats_for_service.cypher` row.
    Output:  (nodes, relationships).
    """
    technique_id = row.get("techniqueId", "")
    nodes = [
        EvidenceNode(
            "Threat",
            technique_id,
            {"name": row.get("technique"), "tactic": row.get("tactic")},
        )
    ]
    relationships: list[EvidenceRelationship] = []

    for vulnerability in _values(row.get("exploitsVulnerabilities")):
        nodes.append(EvidenceNode("Vulnerability", vulnerability, key_property="name"))
        relationships.append(
            EvidenceRelationship(technique_id, "EXPLOITS", vulnerability)
        )
    for control in _values(row.get("mitigatedBy")):
        nodes.append(EvidenceNode("Control", control, key_property="name"))
        relationships.append(EvidenceRelationship(control, "MITIGATES", technique_id))
    return nodes, relationships


def _shape_users_high_severity(
    row: dict[str, Any],
) -> tuple[list[EvidenceNode], list[EvidenceRelationship]]:
    """
    Purpose: shape one q2 row - a user, the rule that flagged them, and the
             events that are the evidence for it.
    Inputs:  row - a `q2_users_high_severity.cypher` row.
    Output:  (nodes, relationships).
    """
    username = row.get("username", "")
    nodes = [
        EvidenceNode(
            "User",
            username,
            {
                "role": row.get("role"),
                "ruleName": row.get("ruleName"),
                "severity": row.get("severity"),
                "alertCount": row.get("alertCount"),
            },
        )
    ]
    relationships: list[EvidenceRelationship] = []
    for event_id in _values(row.get("evidenceEvents")):
        nodes.append(EvidenceNode("Event", event_id))
        relationships.append(EvidenceRelationship(username, "TRIGGERED", event_id))
    return nodes, relationships


def _shape_dependency_impact(
    row: dict[str, Any],
) -> tuple[list[EvidenceNode], list[EvidenceRelationship]]:
    """
    Purpose: shape one q5 row - a service that depends on the failing one.
    Inputs:  row - a `q5_dependency_impact.cypher` row.
    Output:  (nodes, relationships).
    """
    impacted = row.get("impactedService", "")
    node = EvidenceNode("Service", impacted, {"hops": row.get("hops")})
    return [node], []


#: One shaper per demonstrated query, keyed by the `kg/cypher` query key.
SHAPERS: dict[str, Shaper] = {
    "controls_for_alert": _shape_controls_for_alert,
    "alerts_for_service": _shape_alerts_for_service,
    "threats_for_service": _shape_threats_for_service,
    "users_high_severity": _shape_users_high_severity,
    "dependency_impact": _shape_dependency_impact,
}

#: Which retrieved label counts as a source document, for the evidence block's
#: "source documents" heading.
_DOCUMENT_LABEL = "Document"


def shape_rows(
    query_key: str, rows: Iterable[dict[str, Any]]
) -> tuple[tuple[EvidenceNode, ...], tuple[EvidenceRelationship, ...]]:
    """
    Purpose: turn a query's rows into deduplicated evidence nodes and
             relationships - the pure half of retrieval, tested without a
             database.
    Inputs:  query_key - which of the five ran; rows - its result rows.
    Output:  (nodes, relationships), each deduplicated, in retrieval order.
    Raises:  `KeyError` when no shaper is registered for the key.
    """
    shaper = SHAPERS[query_key]
    nodes: list[EvidenceNode] = []
    relationships: list[EvidenceRelationship] = []

    for row in rows:
        row_nodes, row_relationships = shaper(row)
        nodes.extend(node for node in row_nodes if node.key)
        relationships.extend(
            edge for edge in row_relationships if edge.start and edge.end
        )
    return _unique(nodes), _unique(relationships)


def retrieve(question: str, runner: Callable[..., list[dict[str, Any]]] = run_query) -> Evidence:
    """
    Purpose: the retrieval entry point - classify the question, build its
             query, run it, and return the evidence found.
    Inputs:  question - the user's natural-language question; runner - the
             query executor, injectable so tests supply rows without a Neo4j.
    Output:  an `Evidence`. Empty with a stated reason when the question is
             unsupported, names no entity, or the graph holds no answer -
             never a guess.
    """
    intent = classify(question)
    try:
        query_text, parameters = build_query(intent)
        query_key = query_key_for(intent)
    except UnsupportedQuestionError as error:
        return Evidence(
            question=question, intent=intent.name.value, reason=str(error)
        )

    rows = runner(query_text, **parameters)
    nodes, relationships = shape_rows(query_key, rows)
    documents = tuple(
        node.key for node in nodes if node.label == _DOCUMENT_LABEL
    )

    return Evidence(
        question=question,
        intent=intent.name.value,
        query_key=query_key,
        query_text=query_text,
        parameters=parameters,
        nodes=nodes,
        relationships=relationships,
        documents=documents,
        rows=tuple(rows),
        reason=(
            ""
            if nodes
            else f"the graph holds no {query_key} result for {parameters or 'this question'}"
        ),
    )


def _values(value: Any) -> list[str]:
    """
    Purpose: read a collected column safely - Cypher's `collect(DISTINCT x)`
             returns `[null]` when the OPTIONAL MATCH found nothing.
    Inputs:  value - the column, a list or None.
    Output:  the non-empty string entries.
    """
    if not value:
        return []
    return [str(entry) for entry in value if entry]


def _unique(items: list[Any]) -> tuple[Any, ...]:
    """
    Purpose: deduplicate while keeping retrieval order - several rows can cite
             the same control, and the evidence block should show it once.
    Inputs:  items - the frozen dataclass instances to deduplicate.
    Output:  a tuple, first occurrence kept.
    """
    ordered: list[Any] = []
    marks: set[Any] = set()
    for item in items:
        mark = _identity(item)
        if mark not in marks:
            marks.add(mark)
            ordered.append(item)
    return tuple(ordered)


def _identity(item: Any) -> tuple[Any, ...]:
    """
    Purpose: the identity of an evidence item for deduplication - its label and
             key, or its whole triple, ignoring the properties a second row may
             have filled differently.
    Inputs:  item - an `EvidenceNode` or `EvidenceRelationship`.
    Output:  a hashable identity tuple.
    """
    if isinstance(item, EvidenceNode):
        return (item.label, item.key)
    return (item.start, item.type, item.end)
