"""
writes.py - the write-operation type every loader speaks, and the executor.

A loader is split in two so its logic is testable without a database: a pure
function turns its source into a list of `Write` (a Cypher string plus its
parameters), and `apply` runs that list inside one transaction. A test asserts
the `Write` list; only `main` and a live-Neo4j test call `apply`.

Every statement a loader emits is a `MERGE`, so applying the same list twice
leaves the graph unchanged - the idempotence `kg/loader/README.md` requires.

Author: Colile
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Write:
    """
    Purpose: one idempotent write against the graph.
    Inputs:  cypher - a statement, `MERGE`-based; parameters - its named
             parameters.
    Output:  an immutable record. `loader` names the source that produced it,
             for the orchestrator's per-source summary.
    """

    cypher: str
    parameters: dict[str, Any] = field(default_factory=dict)
    loader: str = ""


def apply(session: Any, writes: list[Write]) -> int:
    """
    Purpose: run every `Write` in one transaction, so a loader either fully
             lands or not at all.
    Inputs:  session - an open `neo4j.Session`; writes - the operations.
    Output:  the number of statements executed.
    """
    def _unit(tx: Any) -> int:
        for write in writes:
            tx.run(write.cypher, **write.parameters)
        return len(writes)

    return session.execute_write(_unit)
