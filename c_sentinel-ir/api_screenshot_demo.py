"""One-off script for Deliverable 1, criterion B2d (documentation): a real, live
screenshot of one microservice exchange -- incident-service, through the gateway --
showing the token, the correlation ID, request/response headers and bodies.

Not part of the submitted codebase. Run once, screenshot the terminal, delete.
"""
import json
import pathlib
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent
ENV_PATH = ROOT / "deploy" / ".env"

env = {}
for line in ENV_PATH.read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    env[k.strip()] = v.strip()

BASE = "http://localhost:8000/api/v1"
USERNAME = env.get("BOOTSTRAP_ADMIN_USERNAME", "admin")
PASSWORD = env.get("BOOTSTRAP_ADMIN_PASSWORD")
CORR_ID = "corr-doc-screenshot-0001"


def call(method, path, extra_headers=None, body=None):
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Correlation-ID", CORR_ID)
    for k, v in (extra_headers or {}).items():
        req.add_header(k, v)

    print(f">>> {method} {url}")
    print("    request headers:")
    for k, v in req.header_items():
        shown = v if k.lower() != "authorization" else v[:20] + "...(truncated)"
        print(f"      {k}: {shown}")
    if body is not None:
        shown_body = dict(body)
        if "password" in shown_body:
            shown_body["password"] = "*" * 10
        print("    request body:")
        print("      " + json.dumps(shown_body))
    print()

    try:
        with urllib.request.urlopen(req) as resp:
            status, resp_headers, raw = resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        status, resp_headers, raw = e.code, e.headers, e.read()

    print(f"<<< HTTP {status}")
    print("    response headers:")
    for k, v in resp_headers.items():
        print(f"      {k}: {v}")
    try:
        parsed = json.loads(raw)
        shown = dict(parsed) if isinstance(parsed, dict) else parsed
        if isinstance(shown, dict) and "access_token" in shown:
            shown["access_token"] = shown["access_token"][:24] + "...(truncated)"
        print("    response body:")
        print("\n".join("      " + l for l in json.dumps(shown, indent=2).splitlines()))
    except Exception:
        print("    response body (raw):", raw[:500])
    print("-" * 78)
    print()
    return status, (json.loads(raw) if raw else None)


print("=" * 78)
print(" SENTINEL-IR -- live exchange against incident-service, through Kong")
print(" gateway + bearer token + correlation ID + cross-service call, in one go")
print("=" * 78)
print()

if not PASSWORD or PASSWORD.startswith("CHANGE_ME"):
    print("[!] deploy/.env has no real BOOTSTRAP_ADMIN_PASSWORD set -- aborting.")
    input("\nPress Enter to close...")
    raise SystemExit(1)

# Step A: authenticate through the gateway.
status, login = call("POST", "/auth/login", body={"username": USERNAME, "password": PASSWORD})
token = login["access_token"]

# Step B: create an incident against the seeded critical asset (id 1, core-auth-db).
# incident-service fetches asset_name_snapshot from asset-service through the
# retry + circuit-breaker client -- that field is the cross-service call.
status, incident = call(
    "POST",
    "/incidents",
    extra_headers={"Authorization": f"Bearer {token}"},
    body={
        "title": "Suspicious login pattern on core-auth-db",
        "description": "Documentation screenshot run for Deliverable 1.",
        "severity": "MEDIUM",
        "reported_by": USERNAME,
        "asset_id": 1,
    },
)

print("Done. Correlation ID used for this exchange:", CORR_ID)
input("\nPress Enter to close this window...")
