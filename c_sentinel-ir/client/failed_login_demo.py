"""
failed_login_demo.py - five failed logins, then a good one.

In Phase 1 this shows the security event stream capturing authentication
failures: each bad attempt emits one `AUTH_FAILED` event carrying the
correlation id, and the final good attempt emits `AUTH_SUCCESS`. In Phase 2
this same sequence is the brute-force attack that fires detection Rule 1, so
the script is written once and reused.

Every request goes through the gateway on `http://localhost:8000`.

Run it against a running stack:
    python client/failed_login_demo.py

Author: Colile
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from api_client import ApiClient  # noqa: E402

TARGET_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
WRONG_PASSWORD = "not-the-password"
RIGHT_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "CHANGE_ME_admin_password")
FAILED_ATTEMPTS = 5


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line.
    Inputs: the label and value. Output: None."""
    print(f"{description}: {value}")


def main() -> int:
    """
    Purpose: drive five failed logins then one success, printing each outcome.
    Inputs:  none.
    Output:  0 when the five attempts returned 401 and the sixth returned 200,
             1 otherwise.
    """
    client = ApiClient()
    _line("Gateway base URL", client.base_url)
    _line("Correlation ID for this run", client.correlation_id)
    _line("Target username", TARGET_USERNAME)
    print()

    ok = True
    for attempt in range(1, FAILED_ATTEMPTS + 1):
        response = client.login(TARGET_USERNAME, WRONG_PASSWORD)
        _line(f"Attempt {attempt} - status", response.status_code)
        if response.status_code != 401:
            ok = False
            _line(f"Attempt {attempt} - unexpected body", response.text)

    print()
    response = client.login(TARGET_USERNAME, RIGHT_PASSWORD)
    _line("Final attempt (correct password) - status", response.status_code)
    if response.status_code != 200:
        ok = False
        _line("Final attempt - unexpected body", response.text)

    print()
    _line("Expected", "five 401s then one 200; one AUTH_FAILED per failure on the event stream")
    _line("Result", "as expected" if ok else "NOT as expected")
    _line("Grep this correlation ID in the auth-service log", client.correlation_id)
    client.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
