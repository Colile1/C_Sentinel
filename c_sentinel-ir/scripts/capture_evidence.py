"""
capture_evidence.py - run the demo workflow and write reproducible evidence.

Runs `client/demo_workflow.py`'s workflow against the live stack, then pulls
the log lines carrying that run's correlation id out of all three services'
container logs. Everything is written under `docs/evidence/step12-*` so the
report's screenshots can be regenerated rather than hand-cropped.

    python scripts/capture_evidence.py

Produces:
  docs/evidence/step12-workflow.txt        - each request, its URL and response
  docs/evidence/step12-correlated-logs.jsonl - the log lines for that one id,
                                               across the three services

Author: Colile
"""

from __future__ import annotations

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = REPO_ROOT / "docs" / "evidence"
COMPOSE_FILE = "deploy/docker-compose.yml"
SERVICES = ("auth-service", "incident-service", "asset-service")

sys.path.insert(0, str(REPO_ROOT / "client"))

import demo_workflow  # noqa: E402
from api_client import new_correlation_id  # noqa: E402


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line.
    Inputs: label and value. Output: None."""
    print(f"{description}: {value}")


def _run_workflow(correlation_id: str) -> tuple[int, str]:
    """
    Purpose: run the demo workflow with a known correlation id, capturing its
             printed output.
    Inputs:  correlation_id - the id every request in the run should carry.
    Output:  (exit_code, captured_stdout).
    """
    # demo_workflow builds its own ApiClient; steer it by the env var ApiClient
    # already honours, so the id is fixed and greppable.
    import os

    os.environ["GATEWAY_CORRELATION_ID"] = correlation_id
    buffer = io.StringIO()
    original = demo_workflow.ApiClient

    def _fixed_client(*args, **kwargs):
        """Purpose: force the run's correlation id onto the client.
        Inputs: as ApiClient. Output: an ApiClient using our id."""
        kwargs["correlation_id"] = correlation_id
        return original(*args, **kwargs)

    demo_workflow.ApiClient = _fixed_client
    try:
        with redirect_stdout(buffer):
            code = demo_workflow.main()
    finally:
        demo_workflow.ApiClient = original
    return code, buffer.getvalue()


def _collect_logs(correlation_id: str) -> list[dict]:
    """
    Purpose: the JSON log lines carrying this correlation id, from all three
             services, in the order Docker returns them.
    Inputs:  correlation_id.
    Output:  a list of parsed log objects. Non-JSON lines are skipped.
    """
    result = subprocess.run(
        ["docker", "compose", "-f", COMPOSE_FILE, "logs", "--no-log-prefix", *SERVICES],
        capture_output=True, text=True, cwd=REPO_ROOT,
    )
    lines: list[dict] = []
    for raw in result.stdout.splitlines():
        if correlation_id not in raw:
            continue
        try:
            lines.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    return lines


def main() -> int:
    """
    Purpose: run the workflow and write the two evidence files.
    Inputs:  none.
    Output:  0 when the workflow succeeded and every service logged the id,
             1 otherwise.
    """
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    correlation_id = new_correlation_id()
    _line("Correlation ID for this capture", correlation_id)

    code, output = _run_workflow(correlation_id)
    workflow_file = EVIDENCE_DIR / "step12-workflow.txt"
    workflow_file.write_text(
        f"Correlation ID: {correlation_id}\n\n{output}", encoding="utf-8"
    )
    _line("Wrote", workflow_file.relative_to(REPO_ROOT))
    if code != 0:
        _line("Workflow", "FAILED - see the file above")
        return 1

    logs = _collect_logs(correlation_id)
    logs_file = EVIDENCE_DIR / "step12-correlated-logs.jsonl"
    logs_file.write_text(
        "\n".join(json.dumps(entry) for entry in logs) + "\n", encoding="utf-8"
    )
    _line("Wrote", logs_file.relative_to(REPO_ROOT))

    # `serviceName`, not `service` - that is the key the JSON log formatter in
    # libs/common/logging.py writes. Reading `service` makes every line look
    # unattributed and reports all three services as missing.
    services_seen = {entry.get("serviceName") for entry in logs}
    _line("Services that logged this id", ", ".join(sorted(s for s in services_seen if s)))
    missing = [s for s in SERVICES if s not in services_seen]
    if missing:
        _line("Missing from the correlated logs", ", ".join(missing))
        return 1
    _line("Evidence captured", "workflow output and correlated logs for all three services")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
