"""
templates.py - one answer template per intent, every slot from a retrieved node.

Template generation is the project's chosen path (D-34). It is explicitly
acceptable to the specification and fully marked, and it has the property an
LLM cannot offer: it is incapable of hallucinating, because there is no slot in
any sentence below that is not read out of an `EvidenceNode`. Nothing here
consults outside knowledge, and nothing here is written from a model's memory of
what MITRE T1110 is - the technique's name arrives from the graph or it is not
said.

Every function takes an `Evidence` and returns prose. When the evidence is
empty the caller never reaches them; `generate` returns the honest
"the graph does not hold" sentence instead.

Author: Colile
"""

from __future__ import annotations

from rag.generation.answer import Answer
from rag.retrieval.evidence import Evidence
from rag.retrieval.intent import IntentName

METHOD = "template"


def _sentence_list(items: tuple[str, ...]) -> str:
    """
    Purpose: join retrieved names into readable prose - "a, b and c".
    Inputs:  items - the names, already taken from evidence nodes.
    Output:  the joined string; "" when there are none.
    """
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])} and {items[-1]}"


def _unpunctuated(text: str) -> str:
    """
    Purpose: drop a trailing full stop from a retrieved value before it is
             embedded mid-sentence - a rule's `recommendedAction` is written as
             a complete sentence, and joining it produces "...if it is.." if it
             keeps its own. Trims punctuation only; the wording is the graph's.
    Inputs:  text - a retrieved property value.
    Output:  the value without a trailing full stop.
    """
    return text.rstrip().rstrip(".")


def _stated(node, name: str) -> str:
    """
    Purpose: read one property for display, or "" when the graph does not hold
             it. Not every optional property is populated - a User loaded from
             an event stream carries no `role` - and printing Python's `None`
             into an answer reads as a claim that the value is null, which is a
             claim no retrieved node made.
    Inputs:  node - an `EvidenceNode`; name - the property name.
    Output:  the value as a string, or "" when absent.
    """
    value = node.properties.get(name)
    return "" if value is None else str(value)


def _qualifier(text: str) -> str:
    """
    Purpose: render an optional value as a parenthetical, or nothing at all.
    Inputs:  text - the value, possibly "".
    Output:  " (value)" or "".
    """
    return f" ({text})" if text else ""


def _alert_explanation(evidence: Evidence) -> str:
    """
    Purpose: answer "why was this alert created?" from the q4 evidence - the
             alert, the rule that raised it, and the technique it indicates.
    Inputs:  evidence - the retrieved q4 subgraph.
    Output:  the answer text.
    """
    alert = evidence.nodes_of("Alert")[0]
    rule = _stated(alert, "ruleName")
    threats = evidence.nodes_of("Threat")

    text = (
        f"Alert {alert.key} was created by the detection rule {rule!r}."
        if rule
        else f"Alert {alert.key} was created by a detection rule."
    )
    if threats:
        threat = threats[0]
        text += (
            f" The alert indicates ATT&CK technique {threat.key}"
            f"{_qualifier(_stated(threat, 'name'))}."
        )
    return text


def _response_procedure(evidence: Evidence) -> str:
    """
    Purpose: answer "what should be done?" from the q4 evidence - the rule's
             own recommended action, the controls that mitigate the technique,
             and the runbooks that cover the response.
    Inputs:  evidence - the retrieved q4 subgraph.
    Output:  the answer text.
    """
    alert = evidence.nodes_of("Alert")[0]
    controls = tuple(node.key for node in evidence.nodes_of("Control"))
    runbooks = tuple(node.key for node in evidence.nodes_of("Document"))

    parts = []
    action = _stated(alert, "recommendedAction")
    if action:
        parts.append(f"The rule's recommended action is: {_unpunctuated(action)}")
    if controls:
        parts.append(
            f"The controls that mitigate this threat are {_sentence_list(controls)}"
        )
    if runbooks:
        parts.append(f"The response procedure is documented in {_sentence_list(runbooks)}")
    return ". ".join(parts) + "." if parts else _nothing_known(evidence)


def _alert_and_response(evidence: Evidence) -> str:
    """
    Purpose: the build order's step-19 question - "why was this alert created
             and what should be done?" - answered as one paragraph, since both
             halves come from the same retrieved subgraph.
    Inputs:  evidence - the retrieved q4 subgraph.
    Output:  the answer text.
    """
    return f"{_alert_explanation(evidence)} {_response_procedure(evidence)}"


def _service_alerts(evidence: Evidence) -> str:
    """
    Purpose: answer "which alerts affect this service?" from the q1 evidence.
    Inputs:  evidence - the retrieved q1 alerts.
    Output:  the answer text.
    """
    service = evidence.parameters.get("service", "the service")
    alerts = evidence.nodes_of("Alert")
    lines = [f"{len(alerts)} alert(s) affect {service}:"]
    for alert in alerts:
        state = ", ".join(
            value
            for value in (_stated(alert, "severity"), _stated(alert, "status"))
            if value
        )
        detail = _stated(alert, "description")
        lines.append(
            f"  - {alert.key}: {_stated(alert, 'ruleName')}"
            f"{_qualifier(state)}"
            f"{f' - {detail}' if detail else ''}".rstrip()
        )
    return "\n".join(lines)


def _threat_mitigation(evidence: Evidence) -> str:
    """
    Purpose: answer "what threats target this service and what mitigates
             them?" from the q3 evidence.
    Inputs:  evidence - the retrieved q3 subgraph.
    Output:  the answer text.
    """
    service = evidence.parameters.get("service", "the service")
    threats = evidence.nodes_of("Threat")
    controls = tuple(node.key for node in evidence.nodes_of("Control"))

    named = _sentence_list(
        tuple(f"{t.key}{_qualifier(_stated(t, 'name'))}" for t in threats)
    )
    text = f"{service} is targeted by {named}."
    if controls:
        text += f" The controls that mitigate these techniques are {_sentence_list(controls)}."
    return text


def _user_linkage(evidence: Evidence) -> str:
    """
    Purpose: answer "which users are linked to HIGH or CRITICAL alerts?" from
             the q2 evidence, citing the events that are the linkage.
    Inputs:  evidence - the retrieved q2 subgraph.
    Output:  the answer text.
    """
    users = evidence.nodes_of("User")
    lines = [f"{len(users)} user account(s) are linked to HIGH or CRITICAL alerts:"]
    for user in users:
        triggered = tuple(
            edge.end for edge in evidence.relationships
            if edge.type == "TRIGGERED" and edge.start == user.key
        )
        rule = _stated(user, "ruleName")
        severity = _stated(user, "severity")
        lines.append(
            f"  - {user.key}{_qualifier(_stated(user, 'role'))}"
            f"{f' on {rule}' if rule else ''}"
            f"{f' [{severity}]' if severity else ''}, "
            f"{len(triggered)} event(s) of evidence"
        )
    return "\n".join(lines)


def _dependency_impact(evidence: Evidence) -> str:
    """
    Purpose: answer "what is affected if this service fails?" from the q5
             evidence - the blast radius, with the hop count that justifies it.
    Inputs:  evidence - the retrieved q5 services.
    Output:  the answer text.
    """
    failing = evidence.parameters.get("service", "the service")
    impacted = evidence.nodes_of("Service")
    described = []
    for node in impacted:
        hops = _stated(node, "hops")
        described.append(f"{node.key}{_qualifier(f'{hops} hop(s)' if hops else '')}")
    named = _sentence_list(tuple(described))
    return (
        f"If {failing} fails, {len(impacted)} service(s) are affected: {named}."
    )


def _nothing_known(evidence: Evidence) -> str:
    """
    Purpose: the honest answer when retrieval found nothing - `rag/README.md`
             requires this rather than a guess.
    Inputs:  evidence - the empty result, carrying its reason.
    Output:  a sentence naming what the graph does not hold.
    """
    reason = evidence.reason or "no supported question type matched"
    return f"The knowledge graph does not hold an answer to this question: {reason}."


#: One template function per intent. `ALERT_EXPLANATION` answers both halves of
#: the demo question because a single q4 retrieval grounds both.
TEMPLATES = {
    IntentName.ALERT_EXPLANATION.value: _alert_and_response,
    IntentName.RESPONSE_PROCEDURE.value: _response_procedure,
    IntentName.SERVICE_ALERTS.value: _service_alerts,
    IntentName.THREAT_MITIGATION.value: _threat_mitigation,
    IntentName.USER_LINKAGE.value: _user_linkage,
    IntentName.DEPENDENCY_IMPACT.value: _dependency_impact,
}


def generate(evidence: Evidence) -> Answer:
    """
    Purpose: fill this evidence's intent template and bind the result to the
             evidence that grounds it.
    Inputs:  evidence - the retrieval result.
    Output:  an `Answer`. When the evidence is empty, or its intent has no
             template, the answer states that the graph does not know - it
             never invents one.
    """
    template = TEMPLATES.get(evidence.intent)
    if evidence.is_empty or template is None:
        return Answer(evidence.question, _nothing_known(evidence), evidence, METHOD)
    return Answer(evidence.question, template(evidence), evidence, METHOD)
