"""
dependencies.py - the FastAPI wiring the alert routes depend on.

The alert store is in-process (see `store.py`), so unlike a Phase 1 service
there is no per-request session: one `AlertStore` lives for the process and
every request shares it. `get_alert_store` hands that instance to the router,
and tests override it to inject a store they have seeded.

Author: Colile
"""

from __future__ import annotations

from soc.alert_service.store import AlertStore

# The process-wide store. Populated by `soc.rules.main` when it runs against a
# live stream, or by a test's dependency override.
_STORE = AlertStore()


def get_alert_store() -> AlertStore:
    """
    Purpose: the single `AlertStore` the alert API serves from.
    Inputs:  none.
    Output:  the process-wide store instance.
    """
    return _STORE
