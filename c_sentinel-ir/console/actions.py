"""
actions.py - run the project's own scripts from the Operations screen.

Each action is one command a person would otherwise type in a terminal from
c_sentinel-ir/. The catalogue below is the complete list: the browser picks an
action by id and can pass no arguments of its own, so the console never runs
anything that is not written here. The console binds to 127.0.0.1 only
(`console/README.md`), which is what makes a script-running endpoint acceptable.

Author: Colile
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass

from fastapi import APIRouter

from common.errors import NotFoundError

from console.settings import PROJECT_ROOT, PYTHON

router = APIRouter(prefix="/console/api/actions", tags=["actions"])

#: Long enough for the slowest script (the circuit-breaker drill waits for a
#: container restart); a hung script is reported, not waited on forever.
_TIMEOUT_SECONDS = 300


@dataclass(frozen=True)
class Action:
    """
    Purpose: one runnable script - its id, how it is shown, what it needs.
    Inputs:  set in `ACTIONS` at module load.
    Output:  `commands()` is the argv list run, in order, from PROJECT_ROOT.
    """

    id: str
    title: str
    description: str
    group: str
    needs: str
    args: tuple[str, ...]
    #: Extra argv tuples run after `args`, for an action that is several
    #: commands - the unit tests run suite by suite (D-13).
    more: tuple[tuple[str, ...], ...] = ()

    def commands(self) -> list[list[str]]:
        """Purpose: every argv to run. Inputs: none. Output: list of lists."""
        return [[PYTHON, *args] for args in (self.args, *self.more)]

    def display(self) -> str:
        """Purpose: the commands as typed. Inputs: none. Output: str."""
        return " && ".join("python " + " ".join(args) for args in (self.args, *self.more))


ACTIONS: tuple[Action, ...] = (
    Action("verify", "Verify the stack",
           "Preflight check: containers healthy, services registered in Consul, "
           "Prometheus targets up, gateway answering.",
           "Stack", "Docker stack", ("scripts/verify_stack.py",)),
    Action("seed", "Seed demo data",
           "Create the demo users and assets through the gateway as the bootstrap "
           "admin. Idempotent.",
           "Stack", "Docker stack", ("scripts/seed_data.py",)),
    Action("workflow", "Run the business workflow",
           "Log in, list assets, raise an incident, read it back and escalate it, "
           "all under one correlation id.",
           "Phase 1 demos", "Docker stack", ("client/demo_workflow.py",)),
    Action("failed-logins", "Stage a brute-force attempt",
           "Five failed logins then a good one. Produces the AUTH_FAILED burst "
           "that fires the Multiple Failed Logins rule.",
           "Phase 1 demos", "Docker stack", ("client/failed_login_demo.py",)),
    Action("break-asset", "Circuit-breaker drill",
           "Stop asset-service, create incidents until the breaker opens, show the "
           "degraded response, then restart it.",
           "Phase 1 demos", "Docker stack", ("scripts/break_asset_service.py",)),
    Action("breaker-evidence", "Circuit-breaker evidence (offline)",
           "The breaker drill against a mock transport. No Docker needed.",
           "Evidence", "Nothing", ("scripts/capture_breaker_evidence.py",)),
    Action("attack-evidence", "Regenerate the attack capture (offline)",
           "Rewrite docs/evidence/step15-attack-events.jsonl, the event stream the "
           "SOC screens read by default.",
           "Evidence", "Nothing", ("scripts/capture_attack_evidence.py",)),
    Action("security-workflow", "Run the Phase 2 security workflow",
           "Events, detection, graph load and the RAG answer in one pass, using the "
           "committed attack capture.",
           "Phase 2 demos", "Neo4j", ("scripts/run_security_workflow.py", "--skip-capture")),
    Action("unit-tests", "Run the unit tests",
           "Every test that needs no containers, one suite at a time as decision "
           "D-13 requires: libs and contracts, soc, kg, rag, console, then each "
           "service.",
           "Quality", "Nothing", ("-m", "pytest", "libs", "tests/contract"),
           more=tuple(("-m", "pytest", suite) for suite in (
               "soc", "kg", "rag", "console", "services/auth-service",
               "services/incident-service", "services/asset-service"))),
)

_BY_ID = {action.id: action for action in ACTIONS}


@router.get("", summary="The runnable actions")
def list_actions() -> list[dict[str, str]]:
    """
    Purpose: the catalogue for the Operations screen.
    Inputs:  none.
    Output:  a JSON array of {id, title, description, group, needs, command}.
    """
    return [
        {
            "id": action.id,
            "title": action.title,
            "description": action.description,
            "group": action.group,
            "needs": action.needs,
            "command": action.display(),
        }
        for action in ACTIONS
    ]


@router.post("/{action_id}", summary="Run one action and return its output")
def run_action(action_id: str) -> dict[str, object]:
    """
    Purpose: run one catalogued script to completion and hand back what it
             printed - the same text the terminal would have shown.
    Inputs:  action_id - an id from `ACTIONS`.
    Output:  {id, exitCode, seconds, output}. 404 for an unknown id.
    """
    action = _BY_ID.get(action_id)
    if action is None:
        raise NotFoundError(f"no action named {action_id!r}", {"action": action_id})
    started = time.monotonic()
    exit_code, outputs = 0, []
    for command in action.commands():
        code, output = _run(command)
        outputs.append(output)
        exit_code = exit_code or code
        if code == -1:
            break
    return {
        "id": action.id,
        "exitCode": exit_code,
        "seconds": round(time.monotonic() - started, 1),
        "output": "\n".join(outputs),
    }


def _run(command: list[str]) -> tuple[int, str]:
    """
    Purpose: run one command to completion, never longer than the timeout.
    Inputs:  command - the argv.
    Output:  (exit code, everything it printed); exit code -1 on a timeout.
    """
    banner = f"$ python {' '.join(command[1:])}\n"
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        partial = exc.stdout or ""
        if isinstance(partial, bytes):
            partial = partial.decode("utf-8", errors="replace")
        return -1, f"{banner}{partial}\nStopped after {_TIMEOUT_SECONDS}s without finishing."
    return completed.returncode, banner + completed.stdout + completed.stderr
