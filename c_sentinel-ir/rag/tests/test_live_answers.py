"""
test_live_answers.py - the step-19 verification against a real graph.

The rest of this package proves the pipeline is correct given rows. This file
proves the rows are real: it loads the committed step-15 attack capture into a
live Neo4j, finds a Multiple Failed Logins alert the rules actually raised, and
asks the build order's own question about it - "Why was this alert created and
what should be done?" - then asserts every claim in the answer maps to a node
the graph returned.

Marked `neo4j`, like `kg/cypher/tests/test_live_queries.py`, and skipped when no
server answers:

    docker compose -f deploy/docker-compose.yml up -d neo4j
    NEO4J_PASSWORD=... python -m pytest rag/tests/test_live_answers.py -m neo4j

Author: Colile
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg.loader.connection import close_driver, get_driver, run_query
from kg.loader.main import collect_writes, schema_statements
from kg.loader.writes import apply
from rag.generation.main import DEMO_RULE_NAME, _first_alert_id, answer_question
from rag.generation.templates import generate
from rag.retrieval.retriever import retrieve
from soc.collector.main import build_store

from rag.tests.test_grounding import _claims, _evidence_vocabulary

pytestmark = pytest.mark.neo4j

_ATTACK_STREAM = (
    Path(__file__).resolve().parents[2]
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
        for statement in schema_statements():
            session.run(statement)
        with _ATTACK_STREAM.open(encoding="utf-8") as handle:
            store = build_store(handle)
        for _name, writes in collect_writes(store):
            apply(session, writes)
    yield
    close_driver()


@pytest.fixture(scope="module")
def failed_login_alert_id(loaded_graph) -> str:
    """
    Purpose: the id of a real Multiple Failed Logins alert in the loaded graph.
    Inputs:  the loaded graph.
    Output:  an `alt-` id.
    """
    rows = run_query(
        "MATCH (a:Alert {ruleName: 'Multiple Failed Logins'}) "
        "RETURN a.alertId AS id ORDER BY id LIMIT 1"
    )
    assert rows, "the attack capture should raise a Multiple Failed Logins alert"
    return rows[0]["id"]


def test_the_step_19_question_is_answered_and_fully_grounded(failed_login_alert_id):
    """
    Purpose: the build order's step-19 verification, on real data - the answer
             names the rule, the technique and a control, and every claim it
             makes maps to a node the graph returned.
    Inputs:  a real alert id from the loaded graph.
    Output:  assertions.
    """
    question = (
        f"Why was alert {failed_login_alert_id} created and what should be done?"
    )
    answer = answer_question(question)

    assert answer.is_grounded
    assert "Multiple Failed Logins" in answer.text
    assert "T1110" in answer.text

    unsupported = _claims(answer.text) - _evidence_vocabulary(answer.evidence)
    assert not unsupported, f"answer claims {unsupported} with no evidence"


def test_the_rendered_answer_displays_its_evidence(failed_login_alert_id):
    """
    Purpose: the four required headings appear, populated from the real graph.
    Inputs:  a real alert id.
    Output:  assertions.
    """
    rendered = answer_question(
        f"Why was alert {failed_login_alert_id} created and what should be done?"
    ).render()

    assert "Retrieved nodes:" in rendered
    assert "Retrieved relationships:" in rendered
    assert "Source documents:" in rendered
    assert "Retrieval method:" in rendered
    assert "-[:INDICATES]->" in rendered


@pytest.mark.parametrize(
    "question",
    [
        "Which alerts affect auth-service?",
        "What is auth-service exposed to?",
        "Which users are linked to repeated failed logins?",
        "What is the likely impact if asset-service fails?",
    ],
)
def test_every_supported_question_returns_grounded_evidence(loaded_graph, question):
    """
    Purpose: `rag/retrieval/README.md`'s done-condition - each supported
             question type returns a non-empty `Evidence` on the seeded graph.
    Inputs:  each supported question shape.
    Output:  assertions.
    """
    answer = generate(retrieve(question))
    assert answer.is_grounded, f"{question!r} retrieved nothing"

    unsupported = _claims(answer.text) - _evidence_vocabulary(answer.evidence)
    assert not unsupported, f"answer claims {unsupported} with no evidence"


def test_an_unsupported_question_is_refused_against_the_live_graph(loaded_graph):
    """
    Purpose: the refusal path holds with a real database behind it - the graph
             being reachable must not tempt an answer out of it.
    Inputs:  the loaded graph.
    Output:  assertions.
    """
    answer = answer_question("What is the weather in Potchefstroom?")
    assert not answer.is_grounded
    assert "does not hold an answer" in answer.text


def test_an_alert_that_is_not_in_the_graph_is_answered_honestly(loaded_graph):
    """
    Purpose: a well-formed but absent alert id retrieves nothing, and the
             answer says so rather than describing the alert generically.
    Inputs:  the loaded graph.
    Output:  assertions.
    """
    answer = answer_question("Why was alert alt-ffffffffffff created?")
    assert not answer.is_grounded
    assert "does not hold an answer" in answer.text


def test_the_demo_picks_the_alert_the_scenario_narrates(loaded_graph):
    """
    Purpose: `--demo` lands on a Multiple Failed Logins alert, which is the
             story the Phase 2 demonstration scenario tells. Every alert the
             attack raises is HIGH, so without the rule preference the choice
             falls to a content-hashed id and the demo narrates whichever alert
             happens to sort first.
    Inputs:  the loaded graph.
    Output:  assertions.
    """
    alert_id = _first_alert_id()
    assert alert_id, "the loaded attack capture should hold alerts"

    rows = run_query(
        "MATCH (a:Alert {alertId: $id}) RETURN a.ruleName AS rule", id=alert_id
    )
    assert rows[0]["rule"] == DEMO_RULE_NAME
