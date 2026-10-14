"""
gateway_proxy.py - forward the browser's Phase 1 calls to the Kong gateway.

The console never talks to auth-, incident- or asset-service directly: every
business call goes through Kong exactly as `client/api_client.py` does, so JWT
checks, rate limiting and correlation-id stamping all still apply and every
click in the UI lands on the security event stream. The proxy exists only
because a browser page served from :8010 cannot call :8000 without CORS.

The response is returned unchanged - status, body and the traceability headers
(`X-Correlation-ID`, `RateLimit-*`) - so the UI can show the same correlation id
that the services logged.

Author: Colile
"""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Request, Response

from console.settings import GATEWAY_URL

router = APIRouter(tags=["gateway"])

#: Request headers passed through to Kong. Anything else (cookies, the
#: browser's own host) stays behind.
_FORWARDED_REQUEST_HEADERS = ("authorization", "content-type", "x-correlation-id")

#: Response headers the UI reads to show traceability and rate-limit state.
_FORWARDED_RESPONSE_HEADERS = (
    "content-type",
    "x-correlation-id",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "x-ratelimit-remaining-minute",
)


@router.api_route(
    "/gateway/api/v1/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    summary="Forward a call to the Kong gateway",
)
async def forward(path: str, request: Request) -> Response:
    """
    Purpose: relay one request to `GATEWAY_URL/api/v1/<path>` and hand back
             Kong's answer untouched.
    Inputs:  path - everything after /api/v1/; request - the browser request,
             whose query string, body and allowed headers are forwarded.
    Output:  Kong's status and body, or a 502 in the services' error shape
             when the gateway cannot be reached at all.
    """
    headers = {
        name: value
        for name, value in request.headers.items()
        if name.lower() in _FORWARDED_REQUEST_HEADERS
    }
    url = f"{GATEWAY_URL}/api/v1/{path}"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            upstream = await client.request(
                request.method,
                url,
                params=request.query_params,
                content=await request.body(),
                headers=headers,
            )
    except httpx.HTTPError as exc:
        return Response(
            content=(
                '{"error": "GATEWAY_UNREACHABLE", "message": '
                f'"The gateway at {GATEWAY_URL} did not answer ({type(exc).__name__}). '
                'Is the stack running? See the Overview screen.", "details": {}}'
            ),
            status_code=502,
            media_type="application/json",
        )
    passed = {
        name: value
        for name, value in upstream.headers.items()
        if name.lower() in _FORWARDED_RESPONSE_HEADERS
    }
    return Response(
        content=upstream.content, status_code=upstream.status_code, headers=passed
    )
