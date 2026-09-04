"""
test_model_and_main.py - the loaders match the model, and the orchestrator wires.

Two properties across the whole loader package: every node label and
relationship type the three loaders emit is one `kg/model/graph_model.py` names
(no drift between the schema doc and the code that builds the graph), and
`kg.loader.main` assembles the three sources in apply order from one event
stream without contacting Neo4j.

Runs without Neo4j.

Author: Colile
"""

from __future__ import annotations

import re
from pathlib import Path

from soc.collector.store import EventStore
from kg.loader.load_events import events
from kg.loader.load_security_knowledge import knowledge
from kg.loader.load_topology import topology
from kg.loader.main import collect_writes, schema_statements
from kg.model.graph_model import NODE_LABELS, RELATIONSHIP_TYPES

_LABEL_RE = re.compile(r"\((?:\w+)?:(\w+)\s*[){]")
_REL_RE = re.compile(r"\[:(\w+)\]")


def _all_writes(event_store: EventStore, alert_store) -> list:
    """Purpose: every `Write` all three loaders emit. Inputs: the two stores.
    Output: a combined list."""
    return [*topology(), *events(event_store, alert_store), *knowledge()]


def test_every_label_the_loaders_use_is_in_the_model(event_store, alert_store):
    """No loader invents a node label the model does not document."""
    used: set[str] = set()
    for write in _all_writes(event_store, alert_store):
        used.update(_LABEL_RE.findall(write.cypher))
    assert used <= NODE_LABELS, used - NODE_LABELS


def test_every_relationship_the_loaders_use_is_in_the_model(event_store, alert_store):
    """No loader invents a relationship type the model does not document."""
    used: set[str] = set()
    for write in _all_writes(event_store, alert_store):
        used.update(_REL_RE.findall(write.cypher))
    assert used <= RELATIONSHIP_TYPES, used - RELATIONSHIP_TYPES


def test_the_model_covers_every_required_label():
    """The specification's twelve required labels are all in the model."""
    required = {
        "User", "Service", "Endpoint", "Asset", "Event", "Alert",
        "Incident", "Threat", "Control", "Vulnerability", "Role", "Document",
    }
    assert required <= NODE_LABELS


def test_schema_statements_parse_and_are_all_constraints_or_indexes():
    """`schema.cypher` splits into runnable statements, nothing but DDL."""
    statements = schema_statements()
    assert statements
    for statement in statements:
        assert statement.upper().startswith(("CREATE CONSTRAINT", "CREATE INDEX"))


def test_collect_writes_orders_the_three_sources(event_store, alert_store):
    """The orchestrator hands back topology, then events, then knowledge."""
    # `collect_writes` re-runs the rules and fills the shared alert store; the
    # fixture stores are only used to prove the ordering and non-emptiness.
    sources = collect_writes(event_store)
    assert [name for name, _ in sources] == ["topology", "events", "security-knowledge"]
    for _, writes in sources:
        assert writes
