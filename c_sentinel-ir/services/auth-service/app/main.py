"""
main.py - auth-service entry point.

Thin by design: it builds the shared application shell (logging, correlation,
the security-event stream, typed-error handling, /metrics, /health and Consul
self-registration all come from `create_service_app`) and mounts the auth
router onto it. No business logic lives here.

Run locally with:
    uvicorn app.main:app --port 8001
from services/auth-service/, with this service's environment set.

Author: Colile
"""

from __future__ import annotations

from common.service import create_service_app

from app.database import database_reachable, init_database
from app.routers.auth_router import router as auth_router
from app.services.bootstrap import ensure_bootstrap_admin


def _on_startup() -> None:
    """Purpose: prepare the schema, then seed the one bootstrap admin.
    Inputs: none. Output: None."""
    init_database()
    ensure_bootstrap_admin()


app = create_service_app(
    "auth-service",
    check_database=database_reachable,
    on_startup=_on_startup,
)
app.include_router(auth_router)
