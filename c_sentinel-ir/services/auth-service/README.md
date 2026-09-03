# services/auth-service/

Owns identity: analysts and administrators, their credentials, their roles, and the JWTs that every
other protected call depends on. It is the source of the authentication events that Phase 2's first
detection rule consumes, so a failed login here is not an error to swallow — it is a product.

Direct port 8001. Its database is `auth_db`, which nothing else may read.

## Planned files

| File | Responsibility |
|------|----------------|
| `app/main.py` | `create_app() -> FastAPI` — wiring only: settings, logging, correlation-ID middleware, error handlers, routers, metrics, Consul register on startup and deregister on shutdown |
| `app/models.py` | `User` — id, username, email, `password_hash`, role, `is_active`, `created_at` |
| `app/schemas.py` | `LoginRequest`, `TokenResponse`, `UserCreate`, `UserRead`, `VerifyResponse` |
| `app/repositories/user_repository.py` | `get_by_username(username) -> User \| None`, `create(user) -> User`, `list_users() -> list[User]`. SQLAlchemy lives here and nowhere else in the service |
| `app/services/password_service.py` | `hash_password(plain) -> str`, `verify_password(plain, hashed) -> bool`. Bcrypt via passlib. Pure; no database, no HTTP |
| `app/services/token_service.py` | `issue_token(user) -> str`, `decode_token(token) -> TokenClaims`. HS256, claims `sub`, `role`, `iat`, `exp`. Expiry comes from settings, never hardcoded. Pure and unit-testable with a frozen clock |
| `app/services/auth_service.py` | `authenticate(username, password, source_ip, correlation_id) -> str` — the business logic: look up, verify, emit `AUTH_SUCCESS` or `AUTH_FAILED`, return a token or raise `AuthenticationError`. The event is emitted on *both* paths |
| `app/routers/auth_router.py` | `POST /api/v1/auth/login`, `GET /api/v1/auth/verify`, `POST /api/v1/auth/users` (admin role only), `GET /api/v1/auth/users` |
| `tests/test_password_service.py` | Hash and verify round-trip; a wrong password fails |
| `tests/test_token_service.py` | Claims are present and correct; an expired token is rejected; a tampered signature is rejected |
| `tests/test_auth_service.py` | A failed login raises `AuthenticationError` **and** emits exactly one `AUTH_FAILED` event carrying the username, source IP and correlation ID |

## Integration

Called by the client through the gateway. Called by no other service — the gateway validates JWTs
itself against the shared secret, so `incident-service` and `asset-service` never make a round trip
here to check a token. Depends on `libs/common` and its own `auth_db`.

The failed-login event is the input to Phase 2's Rule 1 (multiple failed logins). Its `userId`,
`sourceIp` and `timestamp` fields must always be populated or that rule cannot be written.

Done when: a valid login returns a decodable token; a wrong password returns 401 and leaves exactly
one `AUTH_FAILED` event in the log; an expired token is rejected by `verify`.
