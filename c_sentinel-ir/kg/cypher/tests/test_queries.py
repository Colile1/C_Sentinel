"""
test_queries.py - the five queries are well-formed and completely catalogued.

No Neo4j: these check the query definitions themselves - all five present, each
with a plain-English question in its file, each parameter the catalogue
declares actually referenced in the Cypher, and nothing but the five.

Author: Colile
"""

from __future__ import annotations

import re

from kg.cypher.queries import BY_KEY, QUERIES, get_query

_EXPECTED_KEYS = {
    "alerts_for_service",
    "users_high_severity",
    "threats_for_service",
    "controls_for_alert",
    "dependency_impact",
}


def test_exactly_the_five_demonstrated_queries_are_defined():
    """The specification requires at least five; the catalogue holds these five."""
    assert {q.key for q in QUERIES} == _EXPECTED_KEYS
    assert len(QUERIES) == 5
    assert set(BY_KEY) == _EXPECTED_KEYS


def test_every_query_file_opens_with_its_question():
    """The demo narration is "read the file", so each opens with a `// Question:`
    line."""
    for query in QUERIES:
        text = query.text()
        assert "// Question:" in text.splitlines()[1] or "// Question:" in text[:200]


def test_every_declared_parameter_is_referenced_in_the_cypher():
    """A parameter the catalogue names but the query never uses is a mistake in
    one of the two."""
    for query in QUERIES:
        text = query.text()
        for name in query.parameters:
            assert re.search(rf"\${name}\b", text), (query.key, name)


def test_parameterless_queries_declare_no_parameters():
    """q2 takes nothing; the catalogue must say so."""
    assert get_query("users_high_severity").parameters == ()


def test_get_query_rejects_an_unknown_key():
    """A typo'd key is a `KeyError`, not a silent wrong query."""
    import pytest

    with pytest.raises(KeyError):
        get_query("no_such_query")
