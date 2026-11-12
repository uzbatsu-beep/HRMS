
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
