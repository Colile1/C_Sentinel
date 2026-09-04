"""
intent.py - which question is this, and what is it about?

`classify(question)` maps a plain-English question onto one of six intents and
extracts the entity the question names. It is deliberately rule- and
keyword-based rather than model-based: the specification asks the student to
explain the retrieval process, and a scoring table that can be read out loud in
the demo is explainable in a way an embedding is not. It is also deterministic,
so every test asserts an exact intent rather than a probability.

The scoring is the whole mechanism: each intent owns a set of keyword phrases,
a question scores one point per phrase present, and the highest score wins.
Ties break by the declaration order in `INTENTS`, which puts the two
alert-shaped intents first because they are the demo's questions. A question
matching nothing scores zero and is classified `UNSUPPORTED` - the honest
answer, and the one `rag/retrieval/README.md` requires instead of a guess.

Author: Colile
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

# An alert id as the alert schema mints it: `alt-` plus 12 hex characters.
_ALERT_ID = re.compile(r"\balt-[0-9a-f]{12}\b")

# A service name as the topology loader creates it: the three Phase 1 services
# plus the two Phase 2 ones, matched whole so "asset" alone is not a service.
_SERVICE_NAME = re.compile(
    r"\b(auth-service|incident-service|asset-service|alert-service|graph-service)\b"
)


class IntentName(str, Enum):
    """The six question types the retrieval layer supports, plus the refusal."""

    ALERT_EXPLANATION = "ALERT_EXPLANATION"
    RESPONSE_PROCEDURE = "RESPONSE_PROCEDURE"
    SERVICE_ALERTS = "SERVICE_ALERTS"
    THREAT_MITIGATION = "THREAT_MITIGATION"
    USER_LINKAGE = "USER_LINKAGE"
    DEPENDENCY_IMPACT = "DEPENDENCY_IMPACT"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True)
class IntentRule:
    """
    Purpose: one classifiable question type - the phrases that indicate it, and
             the entity kind its query needs.
    Inputs:  set in `INTENTS` at module load.
    Output:  `score(question)` counts the phrases present in a question.
    """

    name: IntentName
    phrases: tuple[str, ...]
    entity_kind: str | None = None

    def score(self, question: str) -> int:
        """
        Purpose: how strongly a lower-cased question indicates this intent.
        Inputs:  question - the question, already lower-cased.
        Output:  the number of this intent's phrases present in it.
        """
        return sum(1 for phrase in self.phrases if phrase in question)


#: Declaration order is the tie-break order. The two alert-shaped intents lead
#: because "why was this alert created and what should be done?" - the question
#: the build order names as the step-19 verification - is one of them.
INTENTS: tuple[IntentRule, ...] = (
    IntentRule(
        IntentName.ALERT_EXPLANATION,
        ("why was", "why did", "what caused", "cause of", "explain", "raised"),
        entity_kind="alert",
    ),
    IntentRule(
        IntentName.RESPONSE_PROCEDURE,
        (
            "what should be done",
            "what should i do",
            "how do i respond",
            "response procedure",
            "runbook",
            "remediate",
            "respond to",
        ),
        entity_kind="alert",
    ),
    IntentRule(
        IntentName.SERVICE_ALERTS,
        ("which alerts", "what alerts", "alerts for", "alerts affecting", "wrong with"),
        entity_kind="service",
    ),
    IntentRule(
        IntentName.THREAT_MITIGATION,
        (
            "which threats",
            "what threats",
            "which techniques",
            "attack techniques",
            "exposed to",
            "which controls",
            "what controls",
            "mitigate",
        ),
        entity_kind="service",
    ),
    IntentRule(
        IntentName.USER_LINKAGE,
        (
            "which users",
            "what users",
            "which accounts",
            "whose account",
            "failed logins",
            "under attack",
        ),
    ),
    IntentRule(
        IntentName.DEPENDENCY_IMPACT,
        (
            "impact if",
            "if this service fails",
            "which services are affected",
            "what is affected",
            "blast radius",
            "depends on",
            "goes down",
            "fails",
        ),
        entity_kind="service",
    ),
)


@dataclass(frozen=True)
class Intent:
    """
    Purpose: the classification result - which intent, the entity id the query
             needs, and the reason, which the evidence block displays as its
             explanation of how retrieval chose this path.
    Inputs:  produced by `classify`.
    Output:  `is_supported` is False for `UNSUPPORTED`.
    """

    name: IntentName
    entity_id: str | None = None
    reason: str = ""
    matched_phrases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_supported(self) -> bool:
        """
        Purpose: whether a query can be built for this intent.
        Inputs:  none beyond the instance.
        Output:  True unless the intent is `UNSUPPORTED`.
        """
        return self.name is not IntentName.UNSUPPORTED


def extract_alert_id(question: str) -> str | None:
    """
    Purpose: the alert id a question names, if it names one.
    Inputs:  question - the raw question text.
    Output:  the `alt-` id, or None.
    """
    match = _ALERT_ID.search(question.lower())
    return match.group(0) if match else None


def extract_service(question: str) -> str | None:
    """
    Purpose: the service name a question names, if it names one.
    Inputs:  question - the raw question text.
    Output:  the service name, or None.
    """
    match = _SERVICE_NAME.search(question.lower())
    return match.group(0) if match else None


def _extract(kind: str | None, question: str) -> str | None:
    """
    Purpose: pull the entity of the kind an intent needs out of the question.
    Inputs:  kind - "alert", "service" or None; question - the raw text.
    Output:  the extracted id, or None when the kind is None or absent.
    """
    if kind == "alert":
        return extract_alert_id(question)
    if kind == "service":
        return extract_service(question)
    return None


def classify(question: str) -> Intent:
    """
    Purpose: map a natural-language question to a supported intent and the
             entity it names - the first step of retrieval, and the step the
             demo explains.
    Inputs:  question - the user's question, any case.
    Output:  an `Intent`. `UNSUPPORTED` when no intent's phrases appear, with a
             reason naming what was not understood rather than guessing.
    """
    if not question or not question.strip():
        return Intent(IntentName.UNSUPPORTED, reason="the question was empty")

    lowered = question.lower()
    scored = [(rule.score(lowered), index, rule) for index, rule in enumerate(INTENTS)]
    best_score, _index, best = max(scored, key=lambda row: (row[0], -row[1]))

    if best_score == 0:
        return Intent(
            IntentName.UNSUPPORTED,
            reason=(
                "no supported question type matched; ask about an alert, a "
                "service's alerts or threats, users linked to failed logins, "
                "or the impact of a service failing"
            ),
        )

    matched = tuple(phrase for phrase in best.phrases if phrase in lowered)
    entity_id = _extract(best.entity_kind, question)
    return Intent(
        best.name,
        entity_id=entity_id,
        reason=(
            f"matched {best.name.value} on {', '.join(repr(p) for p in matched)}"
        ),
        matched_phrases=matched,
    )
