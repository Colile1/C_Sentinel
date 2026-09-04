"""
test_live_queries.py - the five queries return non-empty results on a real graph.

Marked `neo4j`: skipped unless a Neo4j is reachable at `NEO4J_URI`. When it
runs, it loads the graph from the committed step-15 attack capture and then
asserts each of the five demonstrated queries comes back non-empty - the
build order's step-18 verification.

    docker compose -f deploy/docker-compose.yml up -d neo4j
    NEO4J_PASSWORD=... python -m pytest kg/cypher/tests/test_live_queries.py -m neo4j

Author: Colile
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg.cypher.queries import QUERIES, get_query
from kg.loader.connection import close_driver, get_driver, run_query
from kg.loader.main import collect_writes
from kg.loader.writes import apply
from soc.collector.main import build_store

pytestmark = pytest.mark.neo4j

_ATTACK_STREAM = (
    Path(__file__).resolve().parents[3]
    / "docs" / "evidence" / "step15-attack-events.jsonl"
)


def _neo4j_reachable() -> bool:
    """Purpose: whether a Neo4j answers. Inputs: none. Output: bool."""
    try:
        get_driver().verify_connectivity()
        return True
    except Exception:  # noqa: BLE001 - any failure means "not available"
        return False


@pytest.fixture(scope="module")
def loaded_graph():
    """
    Purpose: a Neo4j loaded from the committed attack capture, wiped first so
             the run is deterministic. Skips the module if no server answers.
    Inputs:  none.
    Output:  yields nothing; the graph is the side effect.
    """
    if not _ATTACK_STREAM.exists():
        pytest.skip("regenerate docs/evidence/step15-attack-events.jsonl")
    if not _neo4j_reachable():
        pytest.skip("no Neo4j at NEO4J_URI")

    driver = get_driver()
    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
        from kg.loader.main import schema_statements

        for statement in schema_statements():
            session.run(statement)
        with _ATTACK_STREAM.open(encoding="utf-8") as handle:
            store = build_store(handle)
        for _name, writes in collect_writes(store):
            apply(session, writes)
    yield
    close_driver()


@pytest.mark.parametrize("query", QUERIES, ids=lambda q: q.key)
def test_each_demonstrated_query_returns_rows(loaded_graph, query):
    """
    Purpose: the step-18 verification - all five queries return non-empty
             results on the seeded graph.
    Inputs:  each `Query` in the catalogue.
    Output:  assertions.
    """
    sample = {
        "service": "auth-service"
        if query.key != "dependency_impact"
        else "asset-service",
        "alertId": _a_failed_login_alert_id(),
    }
    parameters = {name: sample[name] for name in query.parameters}
    rows = run_query(query.text(), **parameters)
    assert rows, f"{query.key} returned no rows"


def test_q5_returns_the_real_dependency(loaded_graph):
    """Failing asset-service impacts incident-service, one hop."""
    rows = run_query(get_query("dependency_impact").text(), service="asset-service")
    assert any(r["impactedService"] == "incident-service" for r in rows)


def test_q4_reaches_a_control_for_a_failed_login_alert(loaded_graph):
    """The RAG path: a Multiple Failed Logins alert -> T1110 -> a control."""
    rows = run_query(
        get_query("controls_for_alert").text(), alertId=_a_failed_login_alert_id()
    )
    assert rows
    assert rows[0]["techniqueId"] == "T1110"
    assert rows[0]["controls"]


def _a_failed_login_alert_id() -> str:
    """Purpose: the id of a stored Multiple Failed Logins alert in the loaded
    graph. Inputs: none. Output: an `alt-` id."""
    rows = run_query(
        "MATCH (a:Alert {ruleName: 'Multiple Failed Logins'}) "
        "RETURN a.alertId AS id ORDER BY id LIMIT 1"
    )
    assert rows, "the attack capture should raise a Multiple Failed Logins alert"
    return rows[0]["id"]
