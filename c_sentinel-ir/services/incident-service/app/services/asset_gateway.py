"""
asset_gateway.py - the only place incident-service calls asset-service.

The call goes through `libs/common/http_client.ResilientClient` and nowhere
else, which is what makes the Circuit Breaker with Retry pattern claim in
`docs/patterns.md` true rather than aspirational. A direct `httpx` call
anywhere else in this service is a defect: it bypasses the breaker.

The client is cached per asset-service URL and lives for the life of the
process. That is not an optimisation - a breaker rebuilt on each call counts
one failure, never reaches its threshold and never opens, which is precisely
the silent failure `CLAUDE.md` section 7 flags for this step.

Author: Colile
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import BaseModel

from common.config import Settings
from common.http_client import ResilientClient

SERVICE_NAME = "incident-service"
DEPENDENCY_NAME = "asset-service"


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


@lru_cache(maxsize=None)
def _client_for(base_url: str, settings: Settings) -> ResilientClient:
    """
    Purpose: hold ONE long-lived client, and therefore one long-lived circuit
             breaker, per asset-service URL. Cached because the breaker's
             failure count is the state the pattern depends on: a fresh client
             per call would reset it every time and the breaker would never
             open.
    Inputs:  base_url - asset-service's root URL, the cache key.
             settings - supplies the timeout and the retry and breaker
             thresholds. Hashable because `Settings` is frozen.
    Output:  the shared `ResilientClient` guarding asset-service.
    """
    return ResilientClient(
        service_name=SERVICE_NAME,
        base_url=base_url,
        dependency=DEPENDENCY_NAME,
        settings=settings,
    )


def fetch_asset(
    asset_id: int, *, correlation_id: str, settings: Settings
) -> AssetSummary:
    """
    Purpose: look up the asset an incident names, through the circuit breaker.
    Inputs:  asset_id - the asset's primary key.
             correlation_id - propagated so the two services' logs join.
             settings - supplies `asset_service_url` and the resilience
             thresholds.
    Output:  the `AssetSummary` on success, or the documented fallback summary
             marked unavailable when asset-service cannot be reached or the
             breaker is open - an incident is still creatable, just without a
             fresh name.
    Raises:  `httpx.HTTPStatusError` when asset-service answers 404: the asset
             genuinely does not exist, which is a real answer and not an
             outage, so it is never masked as a fallback.
    """
    client = _client_for(settings.asset_service_url, settings)
    result = client.get(
        f"/api/v1/assets/{asset_id}",
        correlation_id=correlation_id,
        fallback=lambda: _fallback(asset_id),
    )
    # `get` returns whichever came first: asset-service's decoded JSON body, or
    # the fallback's already-built summary when the call degraded. The two are
    # told apart by type rather than by re-checking the breaker, so the answer
    # cannot disagree with the call that produced it.
    if isinstance(result, AssetSummary):
        return result
    return AssetSummary(asset_id=asset_id, name=result["name"])


def _fallback(asset_id: int) -> AssetSummary:
    """
    Purpose: the documented degraded response when asset-service cannot be
             reached, so incident creation is not blocked by it.
    Inputs:  asset_id - the asset that could not be looked up.
    Output:  an `AssetSummary` with no known name, marked unavailable.
    """
    return AssetSummary(asset_id=asset_id, name="unknown", available=False)
