# ADR-0002: Local identity, opaque sessions and basic roles

- Status: Accepted for Phase 2 identity foundation
- Date: 2026-11-12

## Context

The first TWM foundation has no authentication or authorization. Employee, credential and assignment records will contain sensitive business information; all future domain endpoints must require server-side identity and authorization.

## Decision

- Create a local `UserAccount` table for bootstrap identity (separate from the later `Person` and `WorkforceResource` domain objects).
- Store password hashes with **Argon2id**, never raw passwords.
- A console bootstrap command creates the first administrator; there is **no built-in default password** or public registration.
- Login creates an opaque 256-bit+ session token. Only the SHA-256 digest is stored in PostgreSQL. The raw token is sent to the browser in a `HttpOnly`, `SameSite=Strict` cookie; `Secure` is set for non-development/test deployments.
- Sessions expire after eight hours and may be revoked server-side.
- Mutating authenticated endpoints require an `X-CSRF-Token` header, obtained from login or an authenticated `GET /auth/me` call.
- The API initially supports three roles: `admin`, `manager`, `viewer`. Only admin may create/list users; role checks are enforced by FastAPI dependencies.
- The login endpoint checks `Origin` against configured allowed origins when the browser supplies it. API clients without an `Origin` header may use the endpoint.
- `GET /api/v1/health/*` stays public for container orchestration.

## Deferred decisions and explicit limitations

- This is **not** a full role/permission matrix and has no enterprise/site/department scopes yet. Do not use the `manager` role to authorize domain data until scope checks exist.
- No public self-service user registration, password reset or password rotation yet.
- Login rate limiting, account lockout, credential-guessing telemetry and central SSO/OIDC must be designed before deploying beyond a controlled development environment.
- CSRF token is returned in response JSON to the authenticated same-origin client; production deployments must carefully constrain CORS origins and HTTPS.
- A real audit log for administration and privilege changes is required in a subsequent PR, before use with production personal data.
- Logout revokes an individual session; 'logout all sessions' and session inventory are future capabilities.

## Consequences

- Identity is separate from organizational personnel, allowing service accounts or administrators who are not employees.
- Future domain APIs use shared server-side authentication and policy dependencies.
- Database migrations are required for accounts and login sessions; no implicit runtime schema creation.
