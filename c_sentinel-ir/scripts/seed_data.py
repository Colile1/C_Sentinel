"""
seed_data.py - load the demo users and assets through the public API.

Reads `data/seed/users.json` and `data/seed/assets.json` and creates each row
by calling the gateway as the bootstrap admin - never by writing to a database.
If a direct database write were needed here, an endpoint would be missing.

Idempotent: a row the API rejects as a 409 conflict is treated as already
present, so the script can be re-run mid-demo without a duplicate-key error.

Run it against a freshly started stack:
    python scripts/seed_data.py

Author: Colile
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "client"))

from api_client import ApiClient  # noqa: E402

SEED_DIR = Path(__file__).resolve().parents[1] / "data" / "seed"
# Matches BOOTSTRAP_ADMIN_* in deploy/.env; read from the environment so the
# real password never lives in source.
ADMIN_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("BOOTSTRAP_ADMIN_PASSWORD", "CHANGE_ME_admin_password")


def _line(description: str, value: object) -> None:
    """Purpose: print one `Description: value` line.
    Inputs: the label and value. Output: None."""
    print(f"{description}: {value}")


def _load(name: str) -> dict:
    """Purpose: read one seed file.
    Inputs: the file name under data/seed/. Output: its parsed JSON object."""
    return json.loads((SEED_DIR / name).read_text(encoding="utf-8"))


def _seed_users(client: ApiClient) -> tuple[int, int]:
    """
    Purpose: create every user in users.json, tolerating ones already present.
    Inputs:  a logged-in admin client.
    Output:  (created, already_present) counts.
    """
    created = present = 0
    for user in _load("users.json")["users"]:
        response = client.create_user(
            username=user["username"],
            email=user["email"],
            password=user["password"],
            role=user["role"],
        )
        if response.status_code == 201:
            created += 1
            _line("Created user", user["username"])
        elif response.status_code == 409:
            present += 1
            _line("User already present", user["username"])
        else:
            _line("Unexpected response creating user", f"{user['username']} -> {response.status_code} {response.text}")
            raise SystemExit(1)
    return created, present


def _seed_assets(client: ApiClient) -> tuple[int, int]:
    """
    Purpose: create every asset in assets.json, tolerating ones already present.
    Inputs:  a logged-in admin client.
    Output:  (created, already_present) counts.
    """
    created = present = 0
    for asset in _load("assets.json")["assets"]:
        response = client.create_asset(
            name=asset["name"],
            asset_type=asset["asset_type"],
            criticality=asset["criticality"],
            owner=asset["owner"],
            location=asset["location"],
        )
        if response.status_code == 201:
            created += 1
            _line("Created asset", asset["name"])
        elif response.status_code == 409:
            present += 1
            _line("Asset already present", asset["name"])
        else:
            _line("Unexpected response creating asset", f"{asset['name']} -> {response.status_code} {response.text}")
            raise SystemExit(1)
    return created, present


def main() -> int:
    """
    Purpose: log in as the bootstrap admin and seed users then assets.
    Inputs:  none; the gateway URL comes from `GATEWAY_URL` or the default.
    Output:  0 on success; 1 if login fails or the API returns an unexpected
             status. Safe to run repeatedly.
    """
    client = ApiClient()
    _line("Gateway base URL", client.base_url)

    response = client.login(ADMIN_USERNAME, ADMIN_PASSWORD)
    if response.status_code != 200:
        _line("Could not log in as the bootstrap admin", f"{response.status_code} {response.text}")
        _line("Hint", "is BOOTSTRAP_ADMIN_* set in deploy/.env and the stack freshly started?")
        return 1
    _line("Logged in as", ADMIN_USERNAME)

    users_created, users_present = _seed_users(client)
    assets_created, assets_present = _seed_assets(client)

    print()
    _line("Users created", users_created)
    _line("Users already present", users_present)
    _line("Assets created", assets_created)
    _line("Assets already present", assets_present)
    _line("Seed complete", "re-running now would report everything already present")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
