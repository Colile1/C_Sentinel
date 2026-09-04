"""
cypher_builder.py - an intent becomes a parameterised query.

Every intent maps onto one of the five queries already demonstrated in
`kg/cypher`. That reuse is deliberate: the queries the marker sees run at step
18 are the same queries the RAG layer runs at step 19, so there is one set of
Cypher to explain, not two, and a query cannot drift away from the one that was
verified.

The parameters are always bound, never interpolated. An entity id arrives from a
user's question, so building `... {alertId: '<text>'}` by string formatting
would put user input into the query text - the graph equivalent of SQL
injection. `build_query` returns the text and a parameter dict, and every caller
passes them separately to the driver.

Author: Colile
"""

from __future__ import annotations

from kg.cypher.queries import get_query
from rag.retrieval.intent import Intent, IntentName

#: Which of the five demonstrated queries answers each intent, and the name the
#: intent's extracted entity binds to. `USER_LINKAGE` takes no parameter.
INTENT_QUERIES: dict[IntentName, tuple[str, str | None]] = {
    IntentName.ALERT_EXPLANATION: ("controls_for_alert", "alertId"),
    IntentName.RESPONSE_PROCEDURE: ("controls_for_alert", "alertId"),
    IntentName.SERVICE_ALERTS: ("alerts_for_service", "service"),
    IntentName.THREAT_MITIGATION: ("threats_for_service", "service"),
    IntentName.USER_LINKAGE: ("users_high_severity", None),
    IntentName.DEPENDENCY_IMPACT: ("dependency_impact", "service"),
}


class UnsupportedQuestionError(Exception):
    """
    Purpose: the question cannot be turned into a graph query - either no
             intent matched, or the intent matched but the question never named
             the entity its query needs.
    Inputs:  a message stating which of the two it is.
    Output:  raised by `build_query`, caught by `retriever.retrieve`, which
             turns it into an empty `Evidence` carrying the reason.
    """


def query_key_for(intent: Intent) -> str:
    """
    Purpose: the `kg/cypher` query key an intent runs.
    Inputs:  intent - a supported `Intent`.
    Output:  the key, e.g. "controls_for_alert".
    Raises:  `UnsupportedQuestionError` when the intent is UNSUPPORTED.
    """
    if intent.name not in INTENT_QUERIES:
        raise UnsupportedQuestionError(intent.reason or "unsupported question")
    return INTENT_QUERIES[intent.name][0]


def build_query(intent: Intent) -> tuple[str, dict[str, str]]:
    """
    Purpose: the Cypher and bound parameters that answer this intent.
    Inputs:  intent - a classified `Intent` carrying its entity id.
    Output:  (query text, parameter dict). The dict is empty for the one
             intent whose query takes no parameter.
    Raises:  `UnsupportedQuestionError` when the intent is unsupported, or when
             a query needing an entity was asked without one.
    """
    key = query_key_for(intent)
    _key, parameter_name = INTENT_QUERIES[intent.name]
    query = get_query(key)

    if parameter_name is None:
        return query.text(), {}

    if not intent.entity_id:
        raise UnsupportedQuestionError(
            f"the question asks {intent.name.value} but names no "
            f"{parameter_name!r} - include the alert id or service name"
        )
    return query.text(), {parameter_name: intent.entity_id}
