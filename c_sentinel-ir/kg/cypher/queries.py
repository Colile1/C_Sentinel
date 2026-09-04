"""
queries.py - the five demonstrated queries, loaded from their .cypher files.

Each `.cypher` file is the source of truth for its query text and opens with the
plain-English question it answers. This module names them, records which
parameters each takes, and reads the file - so `graph_service.py` and the tests
share one definition and the demo narration is "open the file".

Author: Colile
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

_CYPHER_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Query:
    """
    Purpose: one demonstrated query - its id, the question it answers, the
             `.cypher` file holding it, and the parameters it requires.
    Inputs:  set at module load.
    Output:  `text()` reads the file; `parameters` lists the required names.
    """

    key: str
    question: str
    filename: str
    parameters: tuple[str, ...] = ()

    def text(self) -> str:
        """
        Purpose: the query's Cypher, read from its file.
        Inputs:  none beyond the instance.
        Output:  the file contents.
        """
        return (_CYPHER_DIR / self.filename).read_text(encoding="utf-8")


QUERIES: tuple[Query, ...] = (
    Query(
        "alerts_for_service",
        "Which alerts affect a given service?",
        "q1_alerts_for_service.cypher",
        ("service",),
    ),
    Query(
        "users_high_severity",
        "Which users are linked to HIGH or CRITICAL alerts?",
        "q2_users_high_severity.cypher",
    ),
    Query(
        "threats_for_service",
        "Which ATT&CK techniques target a given service?",
        "q3_threats_for_service.cypher",
        ("service",),
    ),
    Query(
        "controls_for_alert",
        "For a given alert, which controls and runbooks address it?",
        "q4_controls_for_alert.cypher",
        ("alertId",),
    ),
    Query(
        "dependency_impact",
        "If a service fails, which services are affected?",
        "q5_dependency_impact.cypher",
        ("service",),
    ),
)

BY_KEY: dict[str, Query] = {query.key: query for query in QUERIES}


def get_query(key: str) -> Query:
    """
    Purpose: one query by its key.
    Inputs:  key - e.g. "alerts_for_service".
    Output:  the `Query`.
    Raises:  `KeyError` when the key is not one of the five.
    """
    return BY_KEY[key]
