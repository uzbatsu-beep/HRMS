# ADR-0022 — Persisted login failure limits and mutation origin checks

- **Status:** proposed for PR #28 (not automatically approved or merged)
- **Date:** 2026-11-19
- **Baseline:** main after PR #27 (`5697519`)

## Context

The existing local identity module already uses Argon2id, revocable cookie sessions, CSRF token checks and an Origin allowlist on login. It did not bound brute-force login failures and did not check Origin for *all* CSRF-protected mutations. A single in-memory Python dictionary would not enforce a budget across workers/restarts; trusting an arbitrary `X-Forwarded-For` would allow trivially bypassing a remote-source limit.

## Decision

1. Add `login_failure_buckets` (Alembic 0018), storing only keyed-HMAC identifiers and failure count/window expiry. No password, username, raw IP, cookie or token is persisted here.
2. Apply two additive, 10-minute failure budgets: **6** failures per `(source, username)` and **60** per source. The seventh/sixty-first attempt returns **429** with `Retry-After` until window expiry. Counters are saved even when login fails with 401.
3. The source is `request.client.host` as provided by the trusted ASGI transport; **never** parse request-controlled `X-Forwarded-For` in the app. A production reverse proxy must have server-side trusted-proxy allowlisting configured; otherwise all users behind one reverse proxy can share a source bucket.
4. Atomic PostgreSQL `INSERT ... ON CONFLICT DO UPDATE` handles concurrent increments. SQLite supports isolated API unit tests. Expired keys are pruned opportunistically on failure.
5. Successful authentication clears only the pair budget, not the remote-source abuse history. Failed logins return identical public 401 bodies for unknown username, inactive user and bad password, spending dummy Argon2 work for unavailable accounts. This reduces, but does not prove elimination of, all timing side channels.
6. In non-dev/test environments `TWM_AUTH_THROTTLE_HMAC_KEY` must be independently generated and at least 32 characters, configured consistently across workers. Rotating the key invalidates previous hashed buckets. **Do not commit the secret.**
7. Every CSRF-protected mutation additionally checks the supplied `Origin` against configured allowed origins and rejects `Sec-Fetch-Site: cross-site`. Requests without Origin remain possible for CLI/automated clients **only with a valid session and CSRF**; no browser origin bypass is claimed.
8. No change to enterprise/unit RBAC, WorkOrder safety gates, permit rules, physical process control or uploaded evidence storage.

## Verification

- Unit/API tests cover unknown-vs-known public errors, six failures and `Retry-After`, success reset, source budget across varying usernames, spoofed forwarded IP, cross-origin mutation denial and unchanged data, production secret guard.
- Existing organization/competence/credential/work regression tests must remain green.
- PostgreSQL migration, Ruff, pytest, frontend check/build, and Playwright E2E are CI gates. After PR: cite actual CI result, do not infer green before completion.

## Residual risks / deferred work

- The source address can represent a shared NAT/reverse proxy; brute-force controls are a trade-off with possible denial-of-service. Add documented trusted proxy configuration, login telemetry and review limits before external access.
- Global distributed throttling by autonomous source networks, breached-password checks, MFA, OIDC/SSO, account recovery, alerting, secure production deployment, per-field PII permissions and large-scale concurrency tests are **not implemented** by this PR.
- Rate limiting is one layer, not a complete production authentication solution. The test environment remains synthetic-data-only.
