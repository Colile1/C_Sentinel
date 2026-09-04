"""
test_intent.py - the classifier maps questions to intents, and refuses the rest.

The refusal half matters as much as the matching half: `rag/retrieval/README.md`
requires an unsupported question to come back with a clear reason rather than a
guess, so the "does not guess" cases are tested explicitly.

Author: Colile
"""

from __future__ import annotations

import pytest

from rag.retrieval.intent import (
    IntentName,
    classify,
    extract_alert_id,
    extract_service,
)


@pytest.mark.parametrize(
    "question, expected",
    [
        (
            "Why was alert alt-0123456789ab created and what should be done?",
            IntentName.ALERT_EXPLANATION,
        ),
        ("What caused alt-0123456789ab?", IntentName.ALERT_EXPLANATION),
        (
            "What should I do about alert alt-0123456789ab?",
            IntentName.RESPONSE_PROCEDURE,
        ),
        ("Which alerts affect auth-service?", IntentName.SERVICE_ALERTS),
        ("What is auth-service exposed to?", IntentName.THREAT_MITIGATION),
        ("Which users are linked to repeated failed logins?", IntentName.USER_LINKAGE),
        (
            "What is the likely impact if asset-service fails?",
            IntentName.DEPENDENCY_IMPACT,
        ),
    ],
)
def test_supported_questions_classify(question, expected):
    """
    Purpose: each question shape the READMEs name maps to its intent.
    Inputs:  a question and the intent it should produce.
    Output:  assertions.
    """
    assert classify(question).name is expected


@pytest.mark.parametrize(
    "question",
    [
        "What is the weather in Potchefstroom?",
        "Tell me a joke",
        "SELECT * FROM users",
        "",
        "   ",
    ],
)
def test_unsupported_questions_are_refused_not_guessed(question):
    """
    Purpose: a question outside the six shapes is UNSUPPORTED and says why.
    Inputs:  an off-topic or empty question.
    Output:  assertions.
    """
    intent = classify(question)
    assert intent.name is IntentName.UNSUPPORTED
    assert not intent.is_supported
    assert intent.reason


def test_the_demo_question_extracts_its_alert_id():
    """
    Purpose: the step-19 question yields the alert id its query needs.
    Inputs:  none.
    Output:  assertions.
    """
    intent = classify("Why was alert alt-0123456789ab created and what should be done?")
    assert intent.entity_id == "alt-0123456789ab"
    assert intent.matched_phrases


def test_a_service_question_extracts_its_service():
    """
    Purpose: a service-shaped question yields the service name.
    Inputs:  none.
    Output:  assertions.
    """
    assert classify("Which alerts affect incident-service?").entity_id == (
        "incident-service"
    )


def test_a_supported_question_without_an_entity_extracts_none():
    """
    Purpose: the intent still classifies; the missing entity is the query
             builder's problem to report, not the classifier's to invent.
    Inputs:  none.
    Output:  assertions.
    """
    intent = classify("Why was this alert created?")
    assert intent.name is IntentName.ALERT_EXPLANATION
    assert intent.entity_id is None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("about alt-0123456789ab today", "alt-0123456789ab"),
        ("ALT-0123456789AB", "alt-0123456789ab"),
        ("alt-notahexvalue", None),
        ("alt-0123456789", None),
        ("no id here", None),
    ],
)
def test_alert_id_extraction_matches_the_schema_format(text, expected):
    """
    Purpose: only a well-formed `alt-` + 12 hex id is extracted, so a
             malformed id never reaches the query as a parameter.
    Inputs:  candidate text and the expected extraction.
    Output:  assertions.
    """
    assert extract_alert_id(text) == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("auth-service is down", "auth-service"),
        ("what about the asset register", None),
        ("ASSET-SERVICE", "asset-service"),
    ],
)
def test_service_extraction_matches_whole_names(text, expected):
    """
    Purpose: a bare word like "asset" is not a service name.
    Inputs:  candidate text and the expected extraction.
    Output:  assertions.
    """
    assert extract_service(text) == expected


def test_classification_is_deterministic():
    """
    Purpose: the same question always classifies the same way - the property
             that lets the demo be rehearsed.
    Inputs:  none.
    Output:  assertions.
    """
    question = "Which alerts affect auth-service?"
    assert {classify(question).name for _ in range(10)} == {
        IntentName.SERVICE_ALERTS
    }
