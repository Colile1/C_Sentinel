"""
graph_model.py - the knowledge-graph schema as importable data.

`graph_model.md` is the human deliverable; this is the same model as Python so a
test can assert the loaders create every label and relationship the model names
and nothing it does not. `NODE_LABELS` and `RELATIONSHIPS` are the single source
both the loaders and `kg/cypher/graph_service.py` check themselves against.

Author: Colile
"""

from __future__ import annotations

#: Every node label the graph holds, mapped to its natural key - the property a
#: loader MERGEs on, and the property `schema.cypher` puts a uniqueness
#: constraint on.
NODE_KEYS: dict[str, str] = {
    "User": "username",
    "Service": "name",
    "Endpoint": "path",
    "Asset": "name",
    "Event": "eventId",
    "Alert": "alertId",
    "Incident": "incidentId",
    "Threat": "techniqueId",
    "Control": "controlId",
    "Vulnerability": "vulnId",
    "Role": "name",
    "Document": "docId",
}

NODE_LABELS: frozenset[str] = frozenset(NODE_KEYS)

#: Every relationship type, as (start label, type, end label). The loaders build
#: exactly these; `graph_model.md` documents exactly these.
RELATIONSHIPS: tuple[tuple[str, str, str], ...] = (
    ("User", "TRIGGERED", "Event"),
    ("Event", "GENERATED_BY", "Service"),
    ("Event", "TARGETED", "Endpoint"),
    ("Event", "CREATED_ALERT", "Alert"),
    ("Alert", "INDICATES", "Threat"),
    ("Threat", "TARGETS", "Service"),
    ("Threat", "EXPLOITS", "Vulnerability"),
    ("Threat", "SUBTECHNIQUE_OF", "Threat"),
    ("Control", "MITIGATES", "Threat"),
    ("Incident", "CONTAINS", "Alert"),
    ("Service", "DEPENDS_ON", "Service"),
    ("Service", "EXPOSES", "Endpoint"),
    ("User", "HAS_ROLE", "Role"),
    ("Document", "DESCRIBES", "Control"),
    ("Document", "SUPPORTS_RESPONSE_TO", "Threat"),
)

RELATIONSHIP_TYPES: frozenset[str] = frozenset(rel[1] for rel in RELATIONSHIPS)
