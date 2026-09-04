"""
main.py - the question-answering entry point and the demo CLI.

Thin, like every other entry point in this project: it parses arguments, calls
`answer_question`, and prints. All the logic lives in `rag/retrieval` and
`rag/generation/templates.py`.

    python -m rag.generation.main "Why was alert alt-abc123456789 created and
                                   what should be done?"
    python -m rag.generation.main --questions       # the six supported shapes
    python -m rag.generation.main --demo            # the step-19 question, run
                                                    # against the live graph

Needs a reachable Neo4j (`NEO4J_*`), because an answer that does not come from
the graph is not an answer this project is willing to print.

Author: Colile
"""

from __future__ import annotations

import argparse
import sys

from rag.generation.answer import Answer
from rag.generation.templates import generate
from rag.retrieval.intent import INTENTS
from rag.retrieval.retriever import retrieve

#: The question the build order names as the step-19 verification. `--demo`
#: resolves a real alert id from the graph and substitutes it here.
DEMO_QUESTION = "Why was alert {alert_id} created and what should be done?"


def answer_question(question: str) -> Answer:
    """
    Purpose: the one public entry point - a question in, a grounded answer with
             its evidence out.
    Inputs:  question - the user's natural-language question.
    Output:  an `Answer` carrying its `Evidence`.
    """
    return generate(retrieve(question))


def supported_questions() -> list[str]:
    """
    Purpose: the question shapes the retrieval layer understands, built from
             the intent table itself so this listing cannot drift from it.
    Inputs:  none.
    Output:  one `Description: value` line per intent.
    """
    return [
        f"{rule.name.value}: e.g. a question containing {rule.phrases[0]!r}"
        for rule in INTENTS
    ]


#: The rule whose alerts the Phase 2 specification's demonstration scenario
#: narrates - repeated failed logins through to a credential-attack answer.
#: `--demo` prefers one of these so the demonstrated answer tells that story.
DEMO_RULE_NAME = "Multiple Failed Logins"


def _first_alert_id() -> str | None:
    """
    Purpose: an alert id from the live graph, so `--demo` asks about a real
             alert rather than a hardcoded one that may not be loaded. A
             *Multiple Failed Logins* alert is preferred, because that is the
             story the specification's demonstration scenario tells; without the
             preference the choice falls to id order, which is a content hash
             and so effectively arbitrary once every alert is HIGH.
    Inputs:  none; reads Neo4j.
    Output:  an `alt-` id, or None when the graph holds no alert.
    """
    from kg.loader.connection import run_query

    rows = run_query(
        """
        MATCH (a:Alert)
        RETURN a.alertId AS id
        ORDER BY a.ruleName = $preferred DESC, a.severity, id
        LIMIT 1
        """,
        preferred=DEMO_RULE_NAME,
    )
    return rows[0]["id"] if rows else None


def main(argv: list[str] | None = None) -> int:
    """
    Purpose: the CLI - answer a question, list the supported shapes, or run the
             step-19 demo question against the live graph.
    Inputs:  argv - the arguments, defaulting to `sys.argv[1:]`.
    Output:  0 on success, 1 when the graph is unreachable or holds no alert.
    """
    parser = argparse.ArgumentParser(
        description="Answer a security question from the knowledge graph."
    )
    parser.add_argument("question", nargs="?", help="the question to answer")
    parser.add_argument(
        "--questions",
        action="store_true",
        help="list the supported question types and exit",
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="answer the step-19 question about an alert found in the graph",
    )
    arguments = parser.parse_args(argv)

    if arguments.questions:
        print("Description: supported question types")
        for line in supported_questions():
            print(f"  {line}")
        return 0

    question = arguments.question
    if arguments.demo:
        try:
            alert_id = _first_alert_id()
        except Exception as error:  # noqa: BLE001 - report, do not traceback
            print(f"Description: the graph is unreachable: {error}", file=sys.stderr)
            return 1
        if not alert_id:
            print(
                "Description: the graph holds no alert; run the kg loader first",
                file=sys.stderr,
            )
            return 1
        question = DEMO_QUESTION.format(alert_id=alert_id)

    if not question:
        parser.error("give a question, or --demo, or --questions")

    try:
        answer = answer_question(question)
    except Exception as error:  # noqa: BLE001 - report, do not traceback
        print(f"Description: the graph is unreachable: {error}", file=sys.stderr)
        return 1

    print(answer.render())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
