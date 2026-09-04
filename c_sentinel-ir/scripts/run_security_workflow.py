"""
run_security_workflow.py - the Phase 2 demonstration scenario, end to end, in
one pass.

The Phase 2 specification section 7 asks for one complete security workflow
demonstrated from the original event through to the RAG answer. Each stage of
that workflow already has its own CLI; this script runs them in order, prints a
banner before each, and stops at the first failure - so the workflow can be run
on camera without switching between four commands and losing the thread.

    python scripts/run_security_workflow.py                 # all five stages
    python scripts/run_security_workflow.py --skip-capture  # keep the committed
                                                            # attack events
    python scripts/run_security_workflow.py --dry-run       # print the commands

The stages, in the specification's own order:

    1. events        the attacker's activity, as collected security events
    2. detection     the rules read those events and raise alerts
    3. graph         the events and alerts are loaded into Neo4j and linked
    4. question      the RAG interface is asked why the alert was created

The five demonstrated Cypher queries are not a stage: they are a separate shot
in the demo, served by `kg.cypher.graph_service` and shown in the Neo4j Browser,
because the specification's workflow ends at the generated answer.

Stages 3 and 4 need a reachable Neo4j (`NEO4J_*`); stages 1 and 2 do not.
Like every other script here this one is an outside caller: it imports no
service package, it shells out to the module CLIs exactly as the demo script
tells the presenter to.

Author: Colile
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass

#: The committed attack capture every stage after the first reads.
ATTACK_EVENTS = "docs/evidence/step15-attack-events.jsonl"

# `soc.rules.main` is deliberately given no `--now` below. Reading from a file it
# defaults the evaluation moment to the newest event's timestamp, which is what
# keeps every rule's window over the attack however long after the capture the
# demo is recorded. Pinning a moment here instead costs alerts silently: at
# 12:05:00Z, five minutes past the capture, Rule 3's one-minute window has
# already slid past the flood and the run raises four alerts rather than five.


@dataclass(frozen=True)
class Stage:
    """
    Purpose: one stage of the demonstrated workflow - what to say it is, and the
             command that performs it.
    Inputs:  set in `build_stages`.
    Output:  `command` is passed to `subprocess.run` as an argument list.
    """

    key: str
    title: str
    command: list[str]
    needs_neo4j: bool = False


def build_stages(*, skip_capture: bool) -> list[Stage]:
    """
    Purpose: the four stages in specification order, as commands.
    Inputs:  skip_capture - leave the committed attack capture untouched rather
             than regenerating it.
    Output:  the stages to run, in order.
    """
    python = sys.executable
    stages = [
        Stage(
            "events",
            "The attack, as security events collected from the services",
            [python, "scripts/capture_attack_evidence.py"],
        ),
        Stage(
            "detection",
            "The detection rules read the events and raise alerts",
            [python, "-m", "soc.rules.main", "--file", ATTACK_EVENTS],
        ),
        Stage(
            "graph",
            "The events and alerts are loaded into Neo4j and linked",
            [python, "-m", "kg.loader.main", "--file", ATTACK_EVENTS],
            needs_neo4j=True,
        ),
        Stage(
            "question",
            "The RAG interface is asked why the alert was created",
            [python, "-m", "rag.generation.main", "--demo"],
            needs_neo4j=True,
        ),
    ]
    if skip_capture:
        stages = [stage for stage in stages if stage.key != "events"]
    return stages


def announce(index: int, total: int, stage: Stage) -> None:
    """
    Purpose: print the banner that separates one stage from the next on screen.
    Inputs:  index - this stage's 1-based position; total - how many there are;
             stage - the stage about to run.
    Output:  none; writes to stdout.
    """
    print()
    print("=" * 70)
    print(f"Stage {index}/{total}: {stage.title}")
    print(f"Command: {' '.join(stage.command)}")
    print("=" * 70)
    sys.stdout.flush()


def run_stage(stage: Stage) -> int:
    """
    Purpose: run one stage, letting its output reach the terminal unbuffered so
             the demo shows it arriving rather than in one block at the end.
    Inputs:  stage - the stage to run.
    Output:  the child process's exit code.
    """
    completed = subprocess.run(stage.command)
    return completed.returncode


def main(argv: list[str] | None = None) -> int:
    """
    Purpose: run the demonstration workflow, stopping at the first stage that
             fails so a broken step is never hidden by the ones after it.
    Inputs:  argv - the arguments, defaulting to `sys.argv[1:]`.
    Output:  0 when every stage succeeded, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        description="Run the Phase 2 security workflow end to end."
    )
    parser.add_argument(
        "--skip-capture",
        action="store_true",
        help="do not regenerate the attack events; use the committed capture",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands each stage would run, and exit",
    )
    arguments = parser.parse_args(argv)

    stages = build_stages(skip_capture=arguments.skip_capture)

    if arguments.dry_run:
        print("Description: the workflow stages, in order")
        for index, stage in enumerate(stages, start=1):
            neo4j = " (needs Neo4j)" if stage.needs_neo4j else ""
            print(f"  {index}. {stage.title}{neo4j}")
            print(f"     {' '.join(stage.command)}")
        return 0

    total = len(stages)
    for index, stage in enumerate(stages, start=1):
        announce(index, total, stage)
        code = run_stage(stage)
        if code != 0:
            print()
            print(
                f"Description: stage {index} ({stage.key}) failed with exit "
                f"code {code}; the workflow stops here",
                file=sys.stderr,
            )
            if stage.needs_neo4j:
                print(
                    "Description: this stage needs Neo4j - check it is up "
                    "(docker compose -f deploy/docker-compose.yml up -d neo4j) "
                    "and that NEO4J_PASSWORD is set",
                    file=sys.stderr,
                )
            return 1

    print()
    print("=" * 70)
    print(f"Description: the security workflow completed all {total} stages")
    print("=" * 70)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
