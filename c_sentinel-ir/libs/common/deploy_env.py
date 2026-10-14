"""
deploy_env.py - make deploy/.env visible to the host-side scripts.

The containers get their configuration from Compose, which reads deploy/.env.
The scripts run on the host - the seed, the demo client, the integration tests,
the graph loader - read the same values from the environment, and a fresh
terminal has none of them, so every login fell back to the placeholder
password and failed with 401. Loading deploy/.env here closes that gap.

Values already in the environment win, so an exported variable still
overrides the file. Inside a container the file is absent and this is a no-op.

Author: Colile
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / "deploy" / ".env"


def parse_env_lines(lines: list[str]) -> dict[str, str]:
    """
    Purpose: read KEY=VALUE pairs the way Compose's env-file does.
    Inputs:  lines - the file's lines; comments and blanks are skipped, and
             one pair of surrounding quotes is stripped from a value.
    Output:  the pairs, in file order.
    """
    pairs: dict[str, str] = {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        pairs[key.strip()] = value
    return pairs


def load_deploy_env(path: Path | None = None) -> int:
    """
    Purpose: copy deploy/.env into os.environ without overriding what is set.
    Inputs:  path - the env file; deploy/.env in this repository by default.
    Output:  the number of variables added; 0 when the file does not exist.
    """
    env_file = path or DEFAULT_ENV_FILE
    if not env_file.is_file():
        return 0
    added = 0
    for key, value in parse_env_lines(env_file.read_text(encoding="utf-8").splitlines()).items():
        if key not in os.environ:
            os.environ[key] = value
            added += 1
    return added
