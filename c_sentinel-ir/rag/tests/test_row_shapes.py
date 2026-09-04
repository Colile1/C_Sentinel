"""
test_row_shapes.py - the fixtures still match the queries they stand in for.

Everything else in this package runs against fixture rows rather than a
database, which is fast and needs no Neo4j - but it buys that speed with a
risk: if a `.cypher` file renames a returned column, the fixtures keep the old
name and every test keeps passing while the live system breaks. This file
closes that gap by parsing the `AS <column>` aliases out of each query file and
asserting the fixture carries exactly those keys.

It is the same trick `tests/contract/test_event_schema.py` plays on
`docs/soc-events.md`: test the two representations against each other, so
neither can drift alone.

Author: Colile
"""

from __future__ import annotations

import re

import pytest

from kg.cypher.queries import get_query
from rag.retrieval.retriever import SHAPERS

#: `RETURN a.alertId AS alertId` - the alias is the row's key.
_ALIAS = re.compile(r"\bAS\s+(\w+)", re.IGNORECASE)


def _returned_columns(query_key: str) -> set[str]:
    """
    Purpose: the column names a `.cypher` file returns, read from the file.
    Inputs:  query_key - one of the five.
    Output:  the set of `AS` aliases in it.
    """
    return set(_ALIAS.findall(get_query(query_key).text()))


@pytest.mark.parametrize(
    "query_key, fixture",
    [
        ("controls_for_alert", "q4_rows"),
        ("alerts_for_service", "q1_rows"),
        ("threats_for_service", "q3_rows"),
        ("users_high_severity", "q2_rows"),
        ("dependency_impact", "q5_rows"),
    ],
)
def test_each_fixture_matches_its_querys_returned_columns(
    query_key, fixture, request
):
    """
    Purpose: a renamed column in a `.cypher` file fails here rather than
             silently invalidating every fixture-based test in this package.
    Inputs:  a query key and the fixture standing in for its rows.
    Output:  assertions.
    """
    rows = request.getfixturevalue(fixture)
    for row in rows:
        assert set(row) == _returned_columns(query_key), (
            f"{fixture} no longer matches {query_key}'s RETURN clause"
        )


def test_every_demonstrated_query_has_a_shaper():
    """
    Purpose: a sixth query added to `kg/cypher` without a shaper here would
             retrieve rows the RAG layer cannot turn into evidence.
    Inputs:  none.
    Output:  assertions.
    """
    from kg.cypher.queries import BY_KEY

    assert set(SHAPERS) == set(BY_KEY)


@pytest.mark.parametrize("query_key", sorted(SHAPERS))
def test_each_shaper_reads_only_columns_its_query_returns(query_key, request):
    """
    Purpose: a shaper reading `row.get("alertID")` when the query returns
             `alertId` silently produces empty evidence. Running each shaper
             over a row built from the query's own aliases catches it: the
             shaper must find at least one non-empty node key.
    Inputs:  each registered query key.
    Output:  assertions.
    """
    columns = _returned_columns(query_key)
    row = {column: f"value-{column}" for column in columns}
    nodes, _relationships = SHAPERS[query_key](row)
    assert nodes and all(node.key for node in nodes)
