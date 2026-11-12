# GEMINI.md — TWM project instructions

You are the engineering agent for **TWM (Technical Workforce Management)** in this repository.

## Read before changing code
- `docs/DEVELOPMENT_PLAN.md` — product scope, architecture baseline, phased roadmap and acceptance gates.
- `TWM_Configurable_Prototype_v0.1.html` — preserved UI/interaction reference; not production code.
- Any ADRs and domain specifications under `docs/`.

## Product
Build a configurable web application for the internal technical workforce of a manufacturing enterprise: mechanics, electricians, energy, automation/PLC, robotics, metrology and other engineering services.

TWM is not primarily payroll, HR document administration, SCADA, or a complete EAM/CMMS. Its core workflow is:
organization → person/resource → verified competence → valid credential/permit → availability → technical work order → explainable candidate matching → human-confirmed assignment → workforce analytics.

## Non-negotiable engineering rules
1. **Modular monolith first.** Keep domain boundaries clear; do not introduce microservices without evidence.
2. **Stable core + configurable metadata.** Keep critical domain data relational and typed. Use JSONB only for configuration documents and carefully scoped custom attributes. Do not use one generic EAV model for the entire application.
3. **Backend is the source of truth.** Frontend must not duplicate or bypass authorization, safety, assignment, or scheduling rules.
4. **Safety gates are hard constraints.** A missing, expired, unverified, or out-of-scope mandatory credential blocks assignment. Ranking, AI and manual selection cannot override it.
5. **Explainability.** Return reasons why a candidate is accepted or rejected.
6. **Auditability.** Audit security, credential, skill approval, configuration publication, assignment and other material changes.
7. **Config-first.** Enterprise directories, competence catalogs, scales, credential types and supported custom fields must be configurable without code changes.
8. **No arbitrary code execution.** User-defined business rules use a limited declarative model; never eval user-provided Python or JavaScript.
9. **No fake functionality.** A visible control must work end-to-end or be clearly marked unavailable.
10. **Preserve history.** Archive reference records instead of deleting those referenced by historical operations.
11. **No invented safety/legal rules.** Do not hard-code jurisdiction-specific permit levels, expiry periods or safety requirements without an explicit verified requirement.
12. **Preserve the existing prototype.** Do not delete or overwrite `TWM_Configurable_Prototype_v0.1.html`; migrate scenarios incrementally.

## Baseline stack
- Frontend: React + TypeScript + Vite.
- UI: Tailwind CSS and shadcn/ui or a justified equivalent.
- Backend: Python + FastAPI + Pydantic.
- Persistence: PostgreSQL + SQLAlchemy 2.x + Alembic.
- Local development: Docker Compose.
- Tests: Pytest/HTTPX, Vitest/Testing Library and Playwright for critical E2E flows.
- CI: GitHub Actions.

Check supported versions and compatibility before pinning dependencies. Avoid new services until a real use case requires them.

## Security baseline
- RBAC with resource scope (enterprise/site/department/own records) enforced server-side.
- Argon2id for local password hashes, or an explicitly configured OIDC provider.
- HttpOnly/Secure/SameSite cookies and CSRF protection for cookie sessions.
- Do not log secrets or unnecessary personal data.
- Validate authorization for every file upload/download.
- Recheck mandatory credentials and assignment constraints in the backend transaction.

## Data conventions
- UUID identifiers for domain records.
- Store timestamps in UTC; use explicit IANA time zones for site calendars and local display.
- Normalize core relational data.
- Version published configuration; validate drafts before publication.
- Use migrations for every schema change.
- Keep audit metadata on important records.

## Required workflow for every task
1. Inspect repository, related code, docs and current branch.
2. Identify affected domains, APIs, DB models, migrations, UI, permissions and tests.
3. Write a short implementation plan before broad changes.
4. Implement one complete vertical slice.
5. Add/adjust unit, integration and E2E tests.
6. Run available checks; report exact commands and actual results.
7. Update docs and roadmap to reflect actual implementation.
8. Summarize changed files, commit/PR reference and known limitations.

Never claim tests passed if they were not run. Never mark a roadmap item done merely because a UI mock or stub endpoint exists.

## Git workflow
- `main` is stable; work on `feature/*`, `fix/*`, or `docs/*`.
- Submit changes through PRs.
- Avoid force-pushes and direct commits to `main`.
- Keep changes small and reviewable.
- Never commit credentials, production personal data or secrets.

## Definition of Done
A task is complete only when the user workflow works end-to-end; backend permissions and business constraints are enforced; data persists; migrations work from a clean database; critical rules have tests; edge cases are handled; and documentation reflects the actual implementation.
