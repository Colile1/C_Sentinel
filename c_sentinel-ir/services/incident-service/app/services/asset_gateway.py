"""
asset_gateway.py - the only place incident-service calls asset-service.

Build step 7 scope only: a plain, timed-out HTTP call with a documented
fallback, so an incident can still be raised while asset-service is down.
Build step 8 wraps this exact call in `libs/common/http_client.ResilientClient`
for retry-with-backoff and the circuit breaker - this module is the one and
only importer of that client from that step onward, which is what keeps the
pattern claim true. Nothing else in this service may reach asset-service
directly.

Author: Colile
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel

from common.config import Settings

_logger = logging.getLogger(__name__)

# Long enough for a healthy asset-service under load, short enough that a dead
# one does not stall an incident creation for the client's default timeout.
_REQUEST_TIMEOUT_SECONDS = 3.0


class AssetSummary(BaseModel):
    """
    Purpose: the subset of an asset that incident-service needs, decoupled
             from asset-service's own response shape.
    Inputs:  the fields below.
    Output:  a validated summary. `available=False` marks the fallback used
             when asset-service could not be reached.
    """

    asset_id: int
    name: str
    available: bool = True


def fetch_asset(
    asset_id: int, *, correlation_id: str, settings: Settings
) -> AssetSummary:
    """
    Purpose: look up the asset an incident names.
    Inputs:  asset_id - the asset's primary key.
             correlation_id - propagated so the two services' logs join.
             settings - supplies `asset_service_url`.
    Output:  the `AssetSummary` on success, or a fallback summary marked
             unavailable when asset-service cannot be reached in time -
             an incident is still creatable, just without a fresh name.
    """
    url = f"{settings.asset_service_url}/api/v1/assets/{asset_id}"
    headers = {"X-Correlation-ID": correlation_id}
    try:
        response = httpx.get(url, headers=headers, timeout=_REQUEST_TIMEOUT_SECONDS)
        response.raise_for_status()
        body = response.json()
        return AssetSummary(asset_id=asset_id, name=body["name"])
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise
        _logger.warning("asset-service returned an error for asset %s: %s", asset_id, exc)
        return _fallback(asset_id)
    except httpx.HTTPError as exc:
        _logger.warning("asset-service is unreachable for asset %s: %s", asset_id, exc)
        return _fallback(asset_id)


def _fallback(asset_id: int) -> AssetSummary:
    """
    Purpose: the documented degraded response when asset-service cannot be
             reached, so incident creation is not blocked by it.
    Inputs:  asset_id - the asset that could not be looked up.
    Output:  an `AssetSummary` with no known name, marked unavailable.
    """
    return AssetSummary(asset_id=asset_id, name="unknown", available=False)
