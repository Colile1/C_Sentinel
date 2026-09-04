"""
connection.py - the Neo4j driver, and the one place its connection details live.

The KG layer does not use `common.config.Settings`: that object is shaped for a
Phase 1 service and requires a `DATABASE_URL` and a `JWT_SECRET` the graph
loader has no use for. Instead this module reads four `NEO4J_*` variables
directly, with defaults that match the Compose service Phase 2 adds on 7687.

`get_driver()` returns a singleton - the driver is a connection pool and is
meant to be created once per process and shared. `run_query` is a thin helper
for the read side (`kg/cypher`); the loaders open their own sessions so they
can batch writes in one transaction.

Author: Colile
"""

from __future__ import annotations

import os
from typing import Any

from neo4j import Driver, GraphDatabase

_DEFAULTS = {
    "NEO4J_URI": "bolt://localhost:7687",
    "NEO4J_USER": "neo4j",
    "NEO4J_PASSWORD": "sentinel-graph",
    "NEO4J_DATABASE": "neo4j",
}

_driver: Driver | None = None


def _setting(name: str) -> str:
    """
    Purpose: read one `NEO4J_*` variable, falling back to the Compose default.
    Inputs:  name - the environment variable name.
    Output:  the configured value or its default.
    """
    return os.environ.get(name, _DEFAULTS[name])


def database_name() -> str:
    """
    Purpose: the target database name, for callers opening their own sessions.
    Inputs:  none.
    Output:  the `NEO4J_DATABASE` value, `neo4j` by default.
    """
    return _setting("NEO4J_DATABASE")


def get_driver() -> Driver:
    """
    Purpose: the process-wide Neo4j driver - a pooled connection created once.
    Inputs:  none; reads `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`.
    Output:  a connected `neo4j.Driver`.
    Raises:  `neo4j.exceptions.ServiceUnavailable` if no server answers.
    """
    global _driver
    if _driver is None:
        _driver = GraphDatabase.driver(
            _setting("NEO4J_URI"),
            auth=(_setting("NEO4J_USER"), _setting("NEO4J_PASSWORD")),
        )
    return _driver


def close_driver() -> None:
    """
    Purpose: close the driver at process end, so a script exits cleanly.
    Inputs:  none.
    Output:  None.
    """
    global _driver
    if _driver is not None:
        _driver.close()
        _driver = None


def run_query(cypher: str, **parameters: Any) -> list[dict[str, Any]]:
    """
    Purpose: run one read query and return its rows as plain dicts - the shape
             `kg/cypher/graph_service.py` serves and the RAG layer consumes.
    Inputs:  cypher - the query text; parameters - its named parameters.
    Output:  a list of row dicts, one per record.
    """
    driver = get_driver()
    with driver.session(database=database_name()) as session:
        result = session.run(cypher, **parameters)
        return [record.data() for record in result]
