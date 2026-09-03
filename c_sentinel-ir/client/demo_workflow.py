"""
demo_workflow.py - the complete marked business workflow, from the client.

Twenty-five percent of Deliverable 1 is that the system performs its business
functionality *from a client*. This script is that client run end to end:

    log in -> list assets -> raise an incident against one -> read it back
    -> escalate its severity

Every request goes to `http://localhost:8000`, the gateway, and each step
prints the full URL it called and the correlation id returned, so the output
is itself the evidence the submission sheet asks for. One correlation id is
used for the whole run and can be grepped out of all three services' logs.

Run it against a freshly started stack:
    python client/demo_workflow.py

Author: Colile
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import ApiClient  # noqa: E402

# The bootstrap admin auth-service seeds at startup. The password must match
# BOOTSTRAP_ADMIN_PASSWORD in deploy/.env; it is read from the environment here
# so the real value never lives in source, with a demo default for a throwaway
# `.env` that kept the placeholder.
ADMIN_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "CHANGE_ME_admin_password")


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line, the house output style.
    Inputs: the label and its value. Output: None."""
    print(f"{description}: {value}")


def _fail(step: str, response: object) -> None:
    """Purpose: report a step that did not return what the workflow needs and
    stop with a non-zero exit.
    Inputs: the step name and the offending response. Output: never returns."""
    status = getattr(response, "status_code", "?")
    body = getattr(response, "text", str(response))
    _line("Workflow failed at", step)
    _line("Status", status)
    _line("Body", body)
    raise SystemExit(1)


def main() -> int:
    """
    Purpose: run the whole workflow and print each step as evidence.
    Inputs:  none; the gateway URL comes from `GATEWAY_URL` or the default.
    Output:  process exit code - 0 when every step returned its expected
             status, 1 at the first step that did not.
    """
    client = ApiClient()
    _line("Gateway base URL", client.base_url)
    _line("Correlation ID for this run", client.correlation_id)
    print()

    # 1. Log in.
    response = client.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    _line("Step 1 - login URL", client.url("/auth/login"))
    if response.status_code != 200:
        _fail("login", response)
    _line("Step 1 - status", response.status_code)
    _line("Step 1 - role", response.json()["role"])
    _line("Step 1 - correlation ID echoed", response.headers.get("X-Correlation-ID"))
    print()

    # 2. List assets and pick one to raise an incident against.
    response = client.list_assets()
    _line("Step 2 - list assets URL", client.url("/assets"))
    if response.status_code != 200:
        _fail("list assets", response)
    assets = response.json()
    if not assets:
        _fail("list assets (register is empty; run scripts/seed_data.py first)", response)
    target = assets[0]
    _line("Step 2 - status", response.status_code)
    _line("Step 2 - assets returned", len(assets))
    _line("Step 2 - target asset", f"{target['id']} {target['name']} ({target['criticality']})")
    print()

    # 3. Raise an incident against that asset.
    response = client.create_incident(
        title="Suspicious outbound traffic",
        description="Beaconing to an unfamiliar host observed from the asset.",
        severity="MEDIUM",
        reported_by=ADMIN_USERNAME,
        asset_id=target["id"],
    )
    _line("Step 3 - create incident URL", client.url("/incidents"))
    if response.status_code != 201:
        _fail("create incident", response)
    incident = response.json()
    _line("Step 3 - status", response.status_code)
    _line("Step 3 - incident ID", incident["id"])
    _line("Step 3 - asset name snapshot", incident["asset_name_snapshot"])
    _line("Step 3 - correlation ID echoed", response.headers.get("X-Correlation-ID"))
    print()

    # 4. Read the incident back.
    response = client.get_incident(incident["id"])
    _line("Step 4 - read incident URL", client.url(f"/incidents/{incident['id']}"))
    if response.status_code != 200:
        _fail("read incident", response)
    _line("Step 4 - status", response.status_code)
    _line("Step 4 - severity now", response.json()["severity"])
    print()

    # 5. Escalate its severity - this emits INCIDENT_ESCALATED.
    response = client.change_severity(incident["id"], "HIGH")
    _line("Step 5 - escalate URL", client.url(f"/incidents/{incident['id']}/severity"))
    if response.status_code != 200:
        _fail("escalate severity", response)
    _line("Step 5 - status", response.status_code)
    _line("Step 5 - severity now", response.json()["severity"])
    print()

    _line("Workflow complete", "all five steps returned their expected status")
    _line("Grep this correlation ID in every service log", client.correlation_id)
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
