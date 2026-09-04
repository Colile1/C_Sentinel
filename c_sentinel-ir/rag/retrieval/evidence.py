"""
evidence.py - the structured retrieval result, and how it is displayed.

The specification requires four things to be shown alongside every answer: the
retrieved nodes, the retrieved relationships, the source documents, and an
explanation of the retrieval method. `Evidence` holds exactly those four, and
`render()` prints them under those four headings - so a marker checking whether
a claim is grounded has one block to read.

An `EvidenceNode` carries its label, its key and the properties the query
returned. That is what makes the grounding checkable rather than asserted:
`rag/generation/templates.py` fills every slot from one of these nodes, and
`rag/generation/tests/test_grounding.py` asserts that each fact in an answer
appears here.

An empty `Evidence` is a first-class result, not an error. When the graph knows
nothing, `reason` says so and the generator says so too - `rag/README.md` is
explicit that "the graph does not know" is the honest answer.

Author: Colile
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceNode:
    """
    Purpose: one retrieved graph node - what it is, which one it is, and the
             properties the query returned for it.
    Inputs:  label - a `graph_model.NODE_KEYS` label; key - its natural key
             value; properties - the returned properties.
    Output:  `describe()` renders it as one display line.
    """

    label: str
    key: str
    properties: dict[str, Any] = field(default_factory=dict)
    key_property: str | None = None

    def describe(self) -> str:
        """
        Purpose: one line naming the node and its properties.
        Inputs:  none beyond the instance.
        Output:  e.g. `(:Alert {alertId: 'alt-...'}) severity=HIGH`.
        """
        shown = " ".join(
            f"{name}={value!r}"
            for name, value in sorted(self.properties.items())
            if value not in (None, "", [], ())
        )
        head = f"(:{self.label} {{{self.identified_by()}: {self.key!r}}})"
        return f"{head} {shown}".rstrip()

    def identified_by(self) -> str:
        """
        Purpose: the property name this node's `key` actually holds. Usually
                 the graph model's natural key, but a query is free to return
                 a different identifying property - q4 returns `c.name` for a
                 Control, not its `controlId` - and the evidence block must
                 name the property it is really showing rather than assert a
                 key it does not hold.
        Inputs:  none beyond the instance.
        Output:  the property name.
        """
        return self.key_property or _key_name(self.label)


@dataclass(frozen=True)
class EvidenceRelationship:
    """
    Purpose: one retrieved relationship, as the path that justified a claim.
    Inputs:  start / type / end - the two node keys and the relationship type.
    Output:  `describe()` renders it in Cypher's own arrow notation.
    """

    start: str
    type: str
    end: str

    def describe(self) -> str:
        """
        Purpose: one line in the notation the Cypher files use.
        Inputs:  none beyond the instance.
        Output:  e.g. `(alt-abc) -[:INDICATES]-> (T1110)`.
        """
        return f"({self.start}) -[:{self.type}]-> ({self.end})"


@dataclass(frozen=True)
class Evidence:
    """
    Purpose: everything retrieval found, and how it found it - the object the
             generator may draw on and may not go beyond.
    Inputs:  the question, the intent and query that served it, the nodes,
             relationships and documents found, plus a reason when empty.
    Output:  `is_empty` for the nothing-found case; `render()` for display.
    """

    question: str
    intent: str
    query_key: str = ""
    query_text: str = ""
    parameters: dict[str, str] = field(default_factory=dict)
    nodes: tuple[EvidenceNode, ...] = ()
    relationships: tuple[EvidenceRelationship, ...] = ()
    documents: tuple[str, ...] = ()
    rows: tuple[dict[str, Any], ...] = ()
    reason: str = ""

    @property
    def is_empty(self) -> bool:
        """
        Purpose: whether retrieval found anything to ground an answer on.
        Inputs:  none beyond the instance.
        Output:  True when no node was retrieved.
        """
        return not self.nodes

    def nodes_of(self, label: str) -> tuple[EvidenceNode, ...]:
        """
        Purpose: the retrieved nodes carrying one label - how a template asks
                 for the Control nodes without knowing the row shape.
        Inputs:  label - e.g. "Control".
        Output:  the matching nodes, in retrieval order.
        """
        return tuple(node for node in self.nodes if node.label == label)

    def render(self) -> str:
        """
        Purpose: the evidence block, under the four headings the specification
                 names - retrieved nodes, retrieved relationships, source
                 documents, and the retrieval method.
        Inputs:  none beyond the instance.
        Output:  the block as text, every line `Description: value` shaped.
        """
        lines = ["Evidence:"]

        lines.append(f"  Retrieved nodes: {len(self.nodes)}")
        for node in self.nodes:
            lines.append(f"    - {node.describe()}")

        lines.append(f"  Retrieved relationships: {len(self.relationships)}")
        for relationship in self.relationships:
            lines.append(f"    - {relationship.describe()}")

        lines.append(f"  Source documents: {len(self.documents)}")
        for document in self.documents:
            lines.append(f"    - {document}")

        lines.append("  Retrieval method: Cypher query over the Neo4j knowledge graph")
        lines.append(f"    Intent: {self.intent}")
        lines.append(f"    Query: {self.query_key or 'none'}")
        lines.append(f"    Parameters: {self.parameters or '{}'}")
        if self.reason:
            lines.append(f"    Note: {self.reason}")
        return "\n".join(lines)


def _key_name(label: str) -> str:
    """
    Purpose: the natural-key property name for a label, so a rendered node
             names its key the way the graph model does.
    Inputs:  label - a node label.
    Output:  the key property name, or "id" for a label the model omits.
    """
    from kg.model.graph_model import NODE_KEYS

    return NODE_KEYS.get(label, "id")
