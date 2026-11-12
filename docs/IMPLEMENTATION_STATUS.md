
# TWM implementation status

Last updated: 2026-11-12

## Baseline

- Existing HTML prototype v0.1 is preserved as a visual and interaction reference.
- Product scope and phased plan are documented in docs/DEVELOPMENT_PLAN.md.
- Persistent AI engineering instructions are in GEMINI.md.
- Architecture decision ADR-0001 records the modular-monolith baseline.

## PR #3 scope

The project foundation branch adds:
- React + TypeScript + Vite frontend shell;
- FastAPI backend application;
- PostgreSQL connection and SQLAlchemy session;
- initial Alembic migration for installation-level platform settings;
- liveness and database-readiness endpoints;
- Docker Compose development environment;
- backend tests and GitHub Actions CI workflow.

This is a foundation scaffold, not a completed production application. Authentication, server-side RBAC, personnel and competence domains, audit, document storage and assignment logic remain future work.

## Local validation performed before opening the PR

- Python compile check completed.
- Backend tests completed with SQLite used only as a local dependency override: 4 passed.
- Alembic SQL generation completed in PostgreSQL offline mode.
- Docker and npm registry access were unavailable in the execution environment; Docker Compose startup and frontend dependency installation/build must be verified by CI or a developer environment.

## Next work after PR #3

1. Review CI results and fix any environment-specific failures.
2. Protect main and require pull requests plus green CI checks.
3. Implement identity, access control and organization structure.
4. Add domain schemas and migrations incrementally; do not implement all business domains in the foundation PR.

## PR #4 — Local Identity & Access (Phase 2 first vertical slice)

- Added `UserAccount` and revocable `LoginSession` domain tables with Alembic migration 0002.
- Implemented password hashing/verification with Argon2id.
- Added cookie-backed login, `GET /auth/me`, logout and administrator-only user creation/listing.
- Mutating authenticated endpoints validate an anti-CSRF header.
- Created a server-side admin bootstrap command without default credentials.
- Added a minimal frontend login and user-creation panel.
- Added integration tests for login, role restrictions, CSRF, revocation and expiry.

**Incomplete:** organizational scopes, detailed RBAC policy matrix, audit log, account lockout/rate limits, password reset and OIDC/SSO. Keep this stage limited to development/test environments and do not load real personal data.

Next: implement organization scope and role policies, then a real organizational hierarchy API and UI.


## PR #5 — Organization Management and RBAC Scope (Phase 2)

- Organization domains: Enterprise, customizable UnitType, arbitrary-depth
  OrganizationUnit tree, UserUnitScope grants, append-only organization audit.
- API: enterprise and unit-type creation, hierarchy creation/read/move/edit,
  scope grant/list/revoke and audit read.
- Viewer and manager roles are **default-deny** for organizations without
  explicit grants. A grant may include descendants; unrelated subtrees remain hidden.
- Admin creates/edits structure and permissions; all mutations require session CSRF.
- Database migration 0003 adds relational constraints including composite foreign
  keys to prevent cross-enterprise parent/type assignment.
- React organization panel supports tree display, enterprise/type/unit creation,
  changing parent or type, user scope grants and revocation.
- API integration tests cover authorization, scope isolation, hierarchy cycles,
  cross-enterprise references, duplicate codes and audit.

Remaining work: full permission matrix, organizational membership/history for
Person and WorkforceResource, enterprise-scoped domain APIs, retention policies,
inactive/archive lifecycle and advanced configuration. Not production-ready.
