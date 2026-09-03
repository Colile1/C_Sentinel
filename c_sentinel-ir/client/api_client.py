"""
api_client.py - a thin HTTP wrapper over the Sentinel-IR gateway.

`ApiClient` holds the base URL and, once logged in, the bearer token, and
offers one method per endpoint. It has no business logic and no retry:
resilience between services is a server concern and lives in
`libs/common/http_client.py`. This client is an outside caller by design - it
imports nothing from this repository and talks to `http://localhost:8000` only,
so every URL it prints is real evidence of gateway routing.

Author: Colile
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import httpx

DEFAULT_BASE_URL = "http://localhost:8000/api/v1"


def new_correlation_id() -> str:
    """
    Purpose: mint a client-side correlation id so the same value can be grepped
             out of every service's logs for one workflow.
    Inputs:  none.
    Output:  a short, log-greppable string, e.g. `corr-1a2b3c4d5e6f7g8h`.
    """
    return "corr-" + uuid.uuid4().hex[:16]


class ApiClient:
    """
    Purpose: make the gateway calls the demo and the integration tests need.
    Inputs:  base_url - the gateway root, defaulting to the env var
             `GATEWAY_URL` or `http://localhost:8000/api/v1`.
             correlation_id - the value sent as `X-Correlation-ID` on every
             request; one is minted when not supplied.
             timeout - per-request timeout in seconds.
    Output:  an object whose methods return `httpx.Response`. It raises only
             `httpx` transport errors; HTTP status is left for the caller to
             read, because a 401 or 429 is often the thing being asserted.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        correlation_id: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.base_url = (
            base_url or os.environ.get("GATEWAY_URL") or DEFAULT_BASE_URL
        ).rstrip("/")
        self.correlation_id = correlation_id or new_correlation_id()
        self._token: str | None = None
        self._http = httpx.Client(timeout=timeout)

    # -- lifecycle -------------------------------------------------------------

    def close(self) -> None:
        """Purpose: release the underlying connection pool.
        Inputs: none. Output: None."""
        self._http.close()

    def __enter__(self) -> "ApiClient":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- internals ----------------------------------------------------------

    def _headers(self, *, auth: bool) -> dict[str, str]:
        """
        Purpose: assemble the headers for one request.
        Inputs:  auth - whether to attach the bearer token.
        Output:  a headers dict always carrying the correlation id.
        """
        headers = {"X-Correlation-ID": self.correlation_id}
        if auth:
            if self._token is None:
                raise RuntimeError("login() must be called before an authenticated request")
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def url(self, path: str) -> str:
        """
        Purpose: the full URL a call will hit, for printing as evidence.
        Inputs:  path - the endpoint path below `/api/v1`, e.g. `/incidents`.
        Output:  the absolute URL on the gateway.
        """
        return f"{self.base_url}{path}"

    def _request(
        self, method: str, path: str, *, auth: bool, json: Any | None = None
    ) -> httpx.Response:
        """Purpose: issue one request with the standard headers.
        Inputs: the method, path, whether to authenticate, and an optional body.
        Output: the httpx Response, whatever its status."""
        return self._http.request(
            method, self.url(path), headers=self._headers(auth=auth), json=json
        )

    # -- auth-service -----------------------------------------------------------

    def login(self, username: str, password: str) -> httpx.Response:
        """
        Purpose: exchange credentials for a JWT and store it for later calls.
        Inputs:  username and password.
        Output:  the login response. On 200 the token is kept on this client.
        """
        response = self._request(
            "POST", "/auth/login", auth=False,
            json={"username": username, "password": password},
        )
        if response.status_code == 200:
            self._token = response.json()["access_token"]
        return response

    def verify(self) -> httpx.Response:
        """Purpose: validate the stored token at the gateway and read its claims.
        Inputs: none. Output: the verify response."""
        return self._request("GET", "/auth/verify", auth=True)

    def create_user(
        self, *, username: str, email: str, password: str, role: str
    ) -> httpx.Response:
        """Purpose: create an account (admin only).
        Inputs: the new account's fields. Output: the response."""
        return self._request(
            "POST", "/auth/users", auth=True,
            json={"username": username, "email": email, "password": password, "role": role},
        )

    def list_users(self) -> httpx.Response:
        """Purpose: the admin user listing.
        Inputs: none. Output: the response."""
        return self._request("GET", "/auth/users", auth=True)

    # -- asset-service -------------------------------------------------------

    def list_assets(self) -> httpx.Response:
        """Purpose: list the asset register.
        Inputs: none. Output: the response."""
        return self._request("GET", "/assets", auth=True)

    def get_asset(self, asset_id: int) -> httpx.Response:
        """Purpose: read one asset.
        Inputs: asset_id. Output: the response."""
        return self._request("GET", f"/assets/{asset_id}", auth=True)

    def create_asset(
        self,
        *,
        name: str,
        asset_type: str,
        criticality: str,
        owner: str,
        location: str,
    ) -> httpx.Response:
        """Purpose: register an asset (admin only).
        Inputs: the asset's fields. Output: the response."""
        return self._request(
            "POST", "/assets", auth=True,
            json={
                "name": name,
                "asset_type": asset_type,
                "criticality": criticality,
                "owner": owner,
                "location": location,
            },
        )

    # -- incident-service -----------------------------------------------------

    def list_incidents(self) -> httpx.Response:
        """Purpose: list incidents.
        Inputs: none. Output: the response."""
        return self._request("GET", "/incidents", auth=True)

    def get_incident(self, incident_id: int) -> httpx.Response:
        """Purpose: read one incident.
        Inputs: incident_id. Output: the response."""
        return self._request("GET", f"/incidents/{incident_id}", auth=True)

    def create_incident(
        self,
        *,
        title: str,
        description: str,
        severity: str,
        reported_by: str,
        asset_id: int,
    ) -> httpx.Response:
        """Purpose: raise an incident against an asset.
        Inputs: the incident's fields. Output: the response."""
        return self._request(
            "POST", "/incidents", auth=True,
            json={
                "title": title,
                "description": description,
                "severity": severity,
                "reported_by": reported_by,
                "asset_id": asset_id,
            },
        )

    def change_severity(self, incident_id: int, severity: str) -> httpx.Response:
        """Purpose: change an incident's severity, which emits an escalation event.
        Inputs: incident_id and the new severity. Output: the response."""
        return self._request(
            "PATCH", f"/incidents/{incident_id}/severity", auth=True,
            json={"severity": severity},
        )
