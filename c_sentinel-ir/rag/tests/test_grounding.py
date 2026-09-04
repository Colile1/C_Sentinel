"""
test_grounding.py - the step-19 verification: every claim maps to displayed
evidence.

This is the file the build order's step-19 row is asking for. The others test
that the pipeline works; this one tests the property the specification actually
marks - that the answer contains no fact which is not present in the retrieved
evidence, and that the evidence is displayed alongside it.

The check is mechanical rather than a reading: every capitalised identifier,
technique id and control name in the answer text is looked up in the evidence's
nodes. A template that started asserting "T1110 is commonly used by ransomware
operators" - true, but not in the graph - fails here.

Author: Colile
"""

from __future__ import annotations

import re

import pytest

from rag.generation.templates import generate
from rag.retrieval.retriever import retrieve

from rag.tests.conftest import ALERT_ID

#: The tokens a claim is made of: alert ids, technique ids, event ids and
#: service names. Anything the answer states in these shapes must be in the
#: evidence.
_CLAIM_TOKEN = re.compile(
    r"\b(alt-[0-9a-f]{12}|evt-[0-9a-f]{12}|T\d{4}(?:\.\d{3})?|[a-z]+-service)\b"
)


def _evidence_vocabulary(evidence) -> set[str]:
    """
    Purpose: every string a grounded answer is allowed to state - the node
             keys, their property values, and the bound parameters.
    Inputs:  evidence - the retrieval result.
    Output:  the set of allowed tokens.
    """
    vocabulary: set[str] = set(evidence.parameters.values())
    for node in evidence.nodes:
        vocabulary.add(node.key)
        for value in node.properties.values():
            if value is not None:
                vocabulary.update(_CLAIM_TOKEN.findall(str(value)))
    for edge in evidence.relationships:
        vocabulary.update({edge.start, edge.end})
    return vocabulary


def _claims(text: str) -> set[str]:
    """
    Purpose: the identifiers an answer asserts.
    Inputs:  text - the answer text.
    Output:  the set of claim tokens in it.
    """
    return set(_CLAIM_TOKEN.findall(text))


@pytest.mark.parametrize(
    "question, fixture",
    [
        (
            f"Why was alert {ALERT_ID} created and what should be done?",
            "q4_rows",
        ),
        (f"What should I do about alert {ALERT_ID}?", "q4_rows"),
        ("Which alerts affect auth-service?", "q1_rows"),
        ("What is auth-service exposed to?", "q3_rows"),
        ("Which users are linked to repeated failed logins?", "q2_rows"),
        ("What is the likely impact if asset-service fails?", "q5_rows"),
    ],
)
def test_every_claim_in_an_answer_appears_in_its_evidence(
    question, fixture, request, runner_for
):
    """
    Purpose: the step-19 verification, for every supported question - no
             identifier is asserted that retrieval did not return.
    Inputs:  a question and the fixture rows its query returns.
    Output:  assertions.
    """
    runner, _calls = runner_for(request.getfixturevalue(fixture))
    answer = generate(retrieve(question, runner))

    unsupported = _claims(answer.text) - _evidence_vocabulary(answer.evidence)
    assert not unsupported, f"answer claims {unsupported} with no evidence"


def test_the_demo_question_answers_both_halves_from_one_retrieval(
    q4_rows, runner_for
):
    """
    Purpose: "why was this alert created **and what should be done?**" - the
             answer states the cause and the response, both grounded.
    Inputs:  the q4 fixture rows.
    Output:  assertions.
    """
    runner, _calls = runner_for(q4_rows)
    answer = generate(
        retrieve(f"Why was alert {ALERT_ID} created and what should be done?", runner)
    )

    assert answer.is_grounded
    assert "Multiple Failed Logins" in answer.text
    assert "T1110" in answer.text
    assert "Account Lockout Policy" in answer.text
    assert "Runbook: Credential Attack Response" in answer.text


def test_a_retrieved_sentence_is_embedded_without_doubling_its_full_stop(
    q4_rows, runner_for
):
    """
    Purpose: a rule's `recommendedAction` is a complete sentence; embedding it
             mid-answer must not produce "..".  The trim is punctuation only,
             so the retrieved wording itself is unchanged.
    Inputs:  the q4 fixture rows, whose action ends in a full stop.
    Output:  assertions.
    """
    rows = [dict(q4_rows[0], ruleRecommendedAction="Lock the account.")]
    runner, _calls = runner_for(rows)
    answer = generate(retrieve(f"What should I do about alert {ALERT_ID}?", runner))

    assert ".." not in answer.text
    assert "Lock the account" in answer.text


def test_evidence_names_the_property_a_node_key_actually_holds(
    q4_rows, runner_for
):
    """
    Purpose: q4 returns `c.name` for a Control, not its `controlId`, so the
             evidence block must show `name:` - claiming a `controlId` it never
             retrieved would be an ungrounded claim in the evidence itself.
    Inputs:  the q4 fixture rows.
    Output:  assertions.
    """
    runner, _calls = runner_for(q4_rows)
    rendered = retrieve(f"Why was alert {ALERT_ID} created?", runner).render()

    assert "(:Control {name: 'Account Lockout Policy'})" in rendered
    assert "(:Document {title: 'Runbook: Credential Attack Response'})" in rendered
    assert "controlId" not in rendered


def test_the_rendered_output_shows_all_four_required_evidence_headings(
    q4_rows, runner_for
):
    """
    Purpose: the specification names four things that must be displayed -
             retrieved nodes, retrieved relationships, source documents, and
             the retrieval method. All four appear in the rendered block.
    Inputs:  the q4 fixture rows.
    Output:  assertions.
    """
    runner, _calls = runner_for(q4_rows)
    rendered = generate(
        retrieve(f"Why was alert {ALERT_ID} created?", runner)
    ).render()

    assert "Retrieved nodes:" in rendered
    assert "Retrieved relationships:" in rendered
    assert "Source documents:" in rendered
    assert "Retrieval method:" in rendered
    assert "controls_for_alert" in rendered


def test_the_evidence_block_shows_the_relationships_not_only_the_nodes(
    q4_rows, runner_for
):
    """
    Purpose: a relationship is displayed in the arrow notation the `.cypher`
             files use, so the marker can trace the path the answer walked.
    Inputs:  the q4 fixture rows.
    Output:  assertions.
    """
    runner, _calls = runner_for(q4_rows)
    rendered = retrieve(f"Why was alert {ALERT_ID} created?", runner).render()
    assert f"({ALERT_ID}) -[:INDICATES]-> (T1110)" in rendered


@pytest.mark.parametrize(
    "question, fixture",
    [
        (f"Why was alert {ALERT_ID} created and what should be done?", "q4_rows"),
        ("Which alerts affect auth-service?", "q1_rows"),
        ("What is auth-service exposed to?", "q3_rows"),
        ("Which users are linked to repeated failed logins?", "q2_rows"),
        ("What is the likely impact if asset-service fails?", "q5_rows"),
    ],
)
def test_a_missing_property_is_omitted_not_printed_as_none(
    question, fixture, request, runner_for
):
    """
    Purpose: the graph does not carry every optional property - a User loaded
             from an event stream has no `role`. A template reading one must
             leave it out, not print Python's `None` into the answer, which
             would read to a marker as a claim that the value is null.
    Inputs:  each question, with every optional column of its row emptied.
    Output:  assertions.
    """
    rows = [dict.fromkeys(request.getfixturevalue(fixture)[0], None) for _ in range(1)]
    # Keep only the identifiers, so every descriptive property is absent.
    for row, original in zip(rows, request.getfixturevalue(fixture)):
        for key in ("alertId", "techniqueId", "username", "impactedService"):
            if key in original:
                row[key] = original[key]

    runner, _calls = runner_for(rows)
    answer = generate(retrieve(question, runner))
    assert "None" not in answer.text


def test_an_unanswerable_question_says_so_and_claims_nothing(runner_for):
    """
    Purpose: the honest-refusal path - no invented answer, and the refusal is
             not counted as grounded.
    Inputs:  the recording runner, returning nothing.
    Output:  assertions.
    """
    runner, _calls = runner_for([])
    answer = generate(retrieve("What is the weather in Potchefstroom?", runner))

    assert not answer.is_grounded
    assert "does not hold an answer" in answer.text
    assert not _claims(answer.text)


def test_an_empty_graph_result_does_not_produce_a_confident_answer(runner_for):
    """
    Purpose: a supported question whose query returned nothing must not be
             answered from the question's own words.
    Inputs:  the recording runner, returning no rows.
    Output:  assertions.
    """
    runner, _calls = runner_for([])
    answer = generate(retrieve(f"Why was alert {ALERT_ID} created?", runner))

    assert not answer.is_grounded
    assert "does not hold an answer" in answer.text
