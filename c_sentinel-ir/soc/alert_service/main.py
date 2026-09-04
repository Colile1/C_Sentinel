"""
main.py - the alert service entry point.

Thin by design: it configures the shared JSON logging, installs the shared
typed-error handlers so a `NotFoundError` from the store becomes a 404 in one
place, mounts the alert router and a liveness `/health`, and holds no business
logic of its own.

Unlike a Phase 1 service it opens no database and does not self-register with
Consul: the SOC layer is an operator tool over the collected event stream, not
a member of the request path (D-25, D-30). The store it serves is the
process-wide `AlertStore` in `dependencies.py`, populated by `soc.rules.main`.

Run locally with:
    uvicorn soc.alert_service.main:app --port 8007
from c_sentinel-ir/.

Author: Colile
"""

from __future__ import annotations

from fastapi import FastAPI

from common.error_handlers import install_error_handlers
from common.health import build_health_router
from common.logging import configure_logging

from soc.alert_service.router import router as alert_router

_SERVICE_NAME = "alert-service"

configure_logging(_SERVICE_NAME)

app = FastAPI(title="Sentinel-IR alert-service", version="0.1.0")
install_error_handlers(app)
app.include_router(build_health_router(_SERVICE_NAME))
app.include_router(alert_router)
