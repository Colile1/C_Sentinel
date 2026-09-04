"""
test_retrieval.py - the query builder binds parameters, and the shapers turn
rows into evidence.

The parameter-binding test is the security-relevant one: an entity id comes
from a user's question, so a builder that interpolated it into the query text
would put user input into Cypher. The test asserts the id appears in the bound
parameters and never in the query text.

Author: Colile
"""

from __future__ import annotations

import pytest

from rag.retrieval.cypher_builder import (
    INTENT_QUERIES,
    UnsupportedQuestionError,
    build_query,
    query_key_for,
)
from rag.retrieval.intent import IntentName, classify
from rag.retrieval.retriever import retrieve, shape_rows

from rag.tests.conftest import ALERT_ID


def test_every_intent_maps_to_a_demonstrated_query():
    """
    Purpose: no supported intent is left without a query, and every query it
             names is one of the five demonstrated at step 18.
    Inputs:  none.
    Output:  assertions.
    """
    from kg.cypher.queries import BY_KEY

    supported = {name for name in IntentName if name is not IntentName.UNSUPPORTED}
    assert set(INTENT_QUERIES) == supported
    for key, _parameter in INTENT_QUERIES.values():
        assert key in BY_KEY


def test_the_entity_id_is_bound_never_interpolated():
    """
    Purpose: user input reaches the driver as a parameter, not as query text.
    Inputs:  none.
    Output:  assertions.
    """
    intent = classify(f"Why was alert {ALERT_ID} created?")
    text, parameters = build_query(intent)
    assert parameters == {"alertId": ALERT_ID}
    assert ALERT_ID not in text
    assert "$alertId" in text


def test_a_parameterless_intent_binds_nothing():
    """
    Purpose: the users query takes no parameter and is built without one.
    Inputs:  none.
    Output:  assertions.
    """
    intent = classify("Which users are linked to repeated failed logins?")
    _text, parameters = build_query(intent)
    assert parameters == {}


def test_an_unsupported_question_cannot_be_built():
    """
    Purpose: building refuses rather than falling back to some default query.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(UnsupportedQuestionError):
        build_query(classify("What is the weather?"))
    with pytest.raises(UnsupportedQuestionError):
        query_key_for(classify("What is the weather?"))


def test_a_supported_question_missing_its_entity_is_refused():
    """
    Purpose: "why was this alert created?" with no id names no alert, and the
             error says which parameter is missing rather than guessing one.
    Inputs:  none.
    Output:  assertions.
    """
    with pytest.raises(UnsupportedQuestionError, match="alertId"):
        build_query(classify("Why was this alert created?"))


def test_q4_rows_shape_into_the_alert_threat_control_path(q4_rows):
    """
    Purpose: the demo question's subgraph - the alert, its technique, the
             controls and the runbook - with the relationships that join them.
    Inputs:  the q4 fixture rows.
    Output:  assertions.
    """
    nodes, relationships = shape_rows("controls_for_alert", q4_rows)

    labels = {node.label for node in nodes}
    assert labels == {"Alert", "Threat", "Control", "Document"}
    assert [node.key for node in nodes if node.label == "Control"] == [
        "Account Lockout Policy",
        "Multi-Factor Authentication",
    ]

    edges = {(e.type, e.end) for e in relationships}
    assert ("INDICATES", "T1110") in edges
    assert ("MITIGATES", "T1110") in edges
    assert ("SUPPORTS_RESPONSE_TO", "T1110") in edges


def test_shapers_drop_the_nulls_an_optional_match_returns():
    """
    Purpose: `collect(DISTINCT c.name)` returns `[null]` when the OPTIONAL
             MATCH found nothing; that must not become a node with an empty
             key, which would be evidence citing nothing.
    Inputs:  none.
    Output:  assertions.
    """
    rows = [
        {
            "alertId": ALERT_ID,
            "ruleName": "Service Failure",
            "techniqueId": "T1499",
            "technique": "Endpoint Denial of Service",
            "controls": [None],
            "runbooks": [],
            "ruleRecommendedAction": "Check the dependency",
        }
    ]
    nodes, _relationships = shape_rows("controls_for_alert", rows)
    assert all(node.key for node in nodes)
    assert not [node for node in nodes if node.label == "Control"]


def test_repeated_evidence_is_shown_once(q4_rows):
    """
    Purpose: two rows citing the same control produce one evidence node, so
             the displayed block is not padded with duplicates.
    Inputs:  the q4 fixture rows, duplicated.
    Output:  assertions.
    """
    nodes, relationships = shape_rows("controls_for_alert", q4_rows * 3)
    assert len(nodes) == len(set((n.label, n.key) for n in nodes))
    assert len(relationships) == len(set((r.start, r.type, r.end) for r in relationships))


@pytest.mark.parametrize(
    "key, fixture, expected_label",
    [
        ("alerts_for_service", "q1_rows", "Alert"),
        ("threats_for_service", "q3_rows", "Threat"),
        ("users_high_severity", "q2_rows", "User"),
        ("dependency_impact", "q5_rows", "Service"),
    ],
)
def test_every_query_has_a_shaper_that_produces_nodes(
    key, fixture, expected_label, request
):
    """
    Purpose: all five queries shape into evidence, not only the demo one.
    Inputs:  a query key, its fixture name and the label it must produce.
    Output:  assertions.
    """
    rows = request.getfixturevalue(fixture)
    nodes, _relationships = shape_rows(key, rows)
    assert nodes
    assert any(node.label == expected_label for node in nodes)


def test_retrieve_runs_the_query_and_fills_the_evidence(q4_rows, runner_for):
    """
    Purpose: the pipeline end to end with an injected runner - no Neo4j.
    Inputs:  the q4 fixture rows and the recording runner.
    Output:  assertions.
    """
    runner, calls = runner_for(q4_rows)
    evidence = retrieve(
        f"Why was alert {ALERT_ID} created and what should be done?", runner
    )

    assert len(calls) == 1
    assert calls[0][1] == {"alertId": ALERT_ID}
    assert evidence.query_key == "controls_for_alert"
    assert not evidence.is_empty
    assert evidence.documents == ("Runbook: Credential Attack Response",)


def test_retrieve_returns_empty_evidence_with_a_reason_when_unsupported(runner_for):
    """
    Purpose: an unsupported question runs no query at all and comes back empty
             with a stated reason.
    Inputs:  the recording runner.
    Output:  assertions.
    """
    runner, calls = runner_for([])
    evidence = retrieve("What is the weather?", runner)

    assert calls == []
    assert evidence.is_empty
    assert evidence.reason
    assert evidence.intent == IntentName.UNSUPPORTED.value


def test_retrieve_returns_empty_evidence_when_the_graph_knows_nothing(runner_for):
    """
    Purpose: a supported question the graph cannot answer is empty with a
             reason naming the query and parameters that found nothing.
    Inputs:  the recording runner, returning no rows.
    Output:  assertions.
    """
    runner, _calls = runner_for([])
    evidence = retrieve(f"Why was alert {ALERT_ID} created?", runner)

    assert evidence.is_empty
    assert "controls_for_alert" in evidence.reason
