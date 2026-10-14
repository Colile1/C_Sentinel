"""
main.py - the operator console entry point.

Thin by design: it installs the shared JSON logging and typed-error handlers,
mounts one router per screen group, mounts the alert service's own router so
the console and `/api/v1/alerts` share one in-process `AlertStore`, and serves
the single-page UI from `console/static/`. No business logic lives here.

The console is an operator tool, like the alert and graph services: it is not on
the request path and does not register with Consul (D-30). It binds to
127.0.0.1 only, because the Operations screen runs the project's scripts.

Run from c_sentinel-ir/ with:
    python -m console.main                 # http://127.0.0.1:8010
or  console.bat

Author: Colile
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from common.error_handlers import install_error_handlers
from common.health import build_health_router
from common.logging import configure_logging

from soc.alert_service.router import router as alert_router

from console import actions, gateway_proxy, graph_api, soc_api, stack_status

_SERVICE_NAME = "console"
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_HOST = "127.0.0.1"
_PORT = 8010

configure_logging(_SERVICE_NAME)

app = FastAPI(title="Sentinel-IR console", version="0.1.0")
install_error_handlers(app)
app.include_router(build_health_router(_SERVICE_NAME))
app.include_router(stack_status.router)
app.include_router(gateway_proxy.router)
app.include_router(alert_router)
app.include_router(soc_api.router)
app.include_router(graph_api.router)
app.include_router(actions.router)
# Last, so every API route above wins over a same-named static file.
app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="ui")


if __name__ == "__main__":
    print(f"Sentinel-IR console: http://{_HOST}:{_PORT}")
    uvicorn.run(app, host=_HOST, port=_PORT, log_level="warning")
