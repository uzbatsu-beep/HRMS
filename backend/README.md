
# TWM Backend

FastAPI backend for Technical Workforce Management.

Install from the repository root with:

    python -m pip install -e "./backend[dev]"

Set TWM_DATABASE_URL to a reachable PostgreSQL connection string. From this directory run:

    alembic upgrade head
    uvicorn app.main:app --reload

The API exposes liveness and readiness probes under /api/v1/health.

## Login security (PR #28)

Failed login requests are counted in the database using HMAC-obfuscated
`(client source, account)` and source-only buckets. The budget is **6** failures
per account+source and **60** failures per source within **10 minutes**.
After the limit, a login attempt receives HTTP 429 with `Retry-After`.
Successful login resets only the account+source bucket. Unknown usernames
produce the same 401 payload as an incorrect password; credentials and
source addresses are not stored in the throttle table.

For any environment other than `development`/`test`, provide a **random,
independent, minimum 32-character** `TWM_AUTH_THROTTLE_HMAC_KEY` through protected
deployment configuration (not Git). All workers must use the same secret.
Changing the secret resets effective failure counters.

The application uses the ASGI client's address and never trusts request
`X-Forwarded-For` itself. If deploying behind a reverse proxy, explicitly
configure trusted proxy IPs on the ASGI server or reverse proxy; otherwise
all clients behind the proxy share a source bucket. This development Compose
is **not** a production-ready deployment.

All authenticated mutations still require `X-CSRF-Token` and additionally
reject disallowed `Origin` and cross-site Fetch Metadata. These checks do
not replace tenant/organizational authorization.

See [ADR-0022](../docs/adr/0022-login-throttling-csrf.md) and the
[security hardening plan](../docs/SECURITY_HARDENING_PLAN.md).

