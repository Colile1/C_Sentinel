# services/auth-service/

Owns identity: analysts and administrators, their credentials, their roles, and the JWTs that every
other protected call depends on. It is the source of the authentication events that Phase 2's first
detection rule consumes, so a failed login here is not an error to swallow — it is a product.

Direct port 8001. Its database is `auth_db`, which nothing else may read.

## Files

Built at build step 5.

| File | Responsibility |
|------|----------------|
| `app/main.py` | Calls `create_service_app` from `libs/common` (D-08) for all shared wiring, mounts the auth router, and passes `init_database` as its startup hook. Six lines of substance |
| `app/database.py` | The one engine and session factory for `auth_db`, the `/health` reachability probe, and `init_database` which creates the tables at startup |
| `app/models.py` | `User` — id, username, email, `password_hash`, role, `is_active`, `created_at` |
| `app/schemas.py` | `LoginRequest`, `TokenResponse`, `UserCreate`, `UserRead`, `VerifyResponse` |
| `app/repositories/user_repository.py` | `get_by_username(username) -> User \| None`, `create(user) -> User`, `list_users() -> list[User]`. SQLAlchemy lives here and nowhere else in the service |
| `app/services/password_service.py` | `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`. Bcrypt directly, not passlib (D-05). Enforces the 8-character minimum and refuses — rather than silently truncating — anything past bcrypt's 72-byte limit. Pure; no database, no HTTP |
| `app/services/token_service.py` | `issue_token(...) -> str`, `decode_token(token) -> TokenClaims`. HS256, claims `sub`, `role`, `iss`, `iat`, `exp`. `iss` is fixed at `sentinel-ir-auth` because Kong looks its signing credential up by that claim (D-10), and `decode_token` verifies it. Expiry comes from settings, never hardcoded. Pure, with an injectable clock so expiry is tested without waiting |
| `app/services/auth_service.py` | `authenticate(...) -> (token, role, expires_in)` and `verify(token)` — the security-critical path: look up, verify, emit `AUTH_SUCCESS` or `AUTH_FAILED`, return a token or raise `AuthenticationError`. The event is emitted on *both* paths. Imports no FastAPI, so it is tested against a fake repository with no database |
| `app/services/user_admin_service.py` | `create_user(...)` and `list_users()`. Split from `auth_service.py`: proving who someone is and administering who exists are two jobs, and the file was over the size limit doing both |
| `app/routers/auth_router.py` | `POST /api/v1/auth/login`, `GET /api/v1/auth/verify`, `POST /api/v1/auth/users` (admin only), `GET /api/v1/auth/users` (admin only) |
| `app/routers/dependencies.py` | The FastAPI wiring the router depends on: the session, the `AuthService`, the bearer token off the header, the decoded claims, and `require_admin`. Keeps the router free of everything but HTTP |
| `tests/test_password_service.py` | Hash and verify round-trip; a wrong password fails |
| `tests/test_token_service.py` | Claims are present and correct; an expired token is rejected; a tampered signature is rejected |
| `tests/test_auth_service.py` | A failed login raises `AuthenticationError` **and** emits exactly one `AUTH_FAILED` event carrying the username, source IP and correlation ID; all three failure causes are indistinguishable to the client (D-11) |
| `tests/test_user_repository.py` | Lookup, ordering, and the `ConflictError` a duplicate username raises, against real SQL on SQLite |
| `tests/test_auth_router.py` | The HTTP contract: 401 shape, the 403 admin guard, and no response ever carrying a password hash |

## Integration

Called by the client through the gateway. Called by no other service — the gateway validates JWTs
itself against the shared secret, so `incident-service` and `asset-service` never make a round trip
here to check a token. Depends on `libs/common` and its own `auth_db`.

The failed-login event is the input to Phase 2's Rule 1 (multiple failed logins). Its `userId`,
`sourceIp` and `timestamp` fields must always be populated or that rule cannot be written.

## Roles

Two, and only two: `admin` and `analyst`. The role is a column on `users`, is copied verbatim into
the token's `role` claim, and is what `require_admin` and the gateway both read. `POST` and `GET`
on `/api/v1/auth/users` are admin-only; a non-admin holding a valid token gets 403, not 401 — the
caller's identity was never in doubt, only their permission.

Done when: a valid login returns a decodable token; a wrong password returns 401 and leaves exactly
one `AUTH_FAILED` event in the log; an expired token is rejected by `verify`. **All three verified
at build step 5**, in unit tests and against a running instance; the event evidence is in
`docs/evidence/step5-auth-events.jsonl`.
