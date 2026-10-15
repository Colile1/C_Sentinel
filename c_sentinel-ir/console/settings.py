"""
settings.py - every address the console talks to, in one place.

All values come from the environment with the stack's published host ports as
defaults (deploy/docker-compose.yml binds each one to 127.0.0.1), so the
console needs no configuration of its own on a machine running `start.bat`.
`load_deploy_env()` runs first so deploy/.env supplies NEO4J_* and the
bootstrap admin name exactly as it does for the other host-side scripts.

Author: Colile
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from common.deploy_env import load_deploy_env

load_deploy_env()

# Docker Desktop does not always put its CLI on PATH; start.bat prepends the
# same folder for the same reason. Without it the live event source and the
# stack scripts the Operations screen runs cannot find `docker`.
_DOCKER_DESKTOP_BIN = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin"
if shutil.which("docker") is None and (_DOCKER_DESKTOP_BIN / "docker.exe").is_file():
    os.environ["PATH"] = f"{_DOCKER_DESKTOP_BIN}{os.pathsep}{os.environ.get('PATH', '')}"

#: c_sentinel-ir/ - every script and evidence path is resolved from here.
PROJECT_ROOT = Path(__file__).resolve().parents[1]

#: The interpreter the console itself runs under, reused for the scripts it
#: launches so they see the same installed packages.
PYTHON = sys.executable

#: The committed attack capture - the offline event source that lets the SOC,
#: graph and RAG screens be demonstrated without Docker.
CAPTURED_EVENTS = PROJECT_ROOT / "docs" / "evidence" / "step15-attack-events.jsonl"

#: A committed capture of an ordinary business workflow - the rules should
#: raise nothing on it.
NORMAL_EVENTS = PROJECT_ROOT / "docs" / "evidence" / "step12-correlated-logs.jsonl"

GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://localhost:8000")
CONSUL_URL = os.environ.get("CONSUL_URL", "http://localhost:8500")
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")
GRAFANA_URL = os.environ.get("GRAFANA_URL", "http://localhost:3901")
NEO4J_BROWSER_URL = os.environ.get("NEO4J_BROWSER_URL", "http://localhost:7474")
KONG_STATUS_URL = os.environ.get("KONG_STATUS_URL", "http://localhost:8081")

#: Direct service ports, used only for /health and the per-service /docs links.
SERVICE_URLS = {
    "auth-service": os.environ.get("AUTH_SERVICE_URL_HOST", "http://localhost:8001"),
    "incident-service": os.environ.get("INCIDENT_SERVICE_URL_HOST", "http://localhost:8002"),
    "asset-service": os.environ.get("ASSET_SERVICE_URL_HOST", "http://localhost:8003"),
}

#: The admin account the seed data uses. Only the name is shown in the UI as a
#: sign-in hint; the password is never sent to the browser.
BOOTSTRAP_ADMIN_USERNAME = os.environ.get("BOOTSTRAP_ADMIN_USERNAME", "admin")

#: Seconds a status probe may take before its target is reported down.
PROBE_TIMEOUT_SECONDS = 1.5
