"""
main.py - incident-service entry point.

Thin by design: it builds the shared application shell (logging, correlation,
the security-event stream, typed-error handling, /metrics, /health and Consul
self-registration all come from `create_service_app`) and mounts the incident
router onto it. No business logic lives here.

Run locally with:
    uvicorn app.main:app --port 8002
from services/incident-service/, with this service's environment set.

Author: Colile
"""

from __future__ import annotations

from common.service import create_service_app

from app.database import database_reachable, init_database
from app.routers.incident_router import router as incident_router

app = create_service_app(
    "incident-service",
    check_database=database_reachable,
    on_startup=init_database,
)
app.include_router(incident_router)
