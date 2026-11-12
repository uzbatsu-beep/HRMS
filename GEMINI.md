# GEMINI.md — TWM project instructions

You are the engineering agent for **TWM (Technical Workforce Management)** in this repository.

## Read before changing code
- `docs/DEVELOPMENT_PLAN.md` — current product scope, architecture baseline, phased roadmap and acceptance gates.
- `TWM_Configurable_Prototype_v0.1.html` — preserved UI/interaction reference; do not treat it as production code.
- Any ADRs and domain specifications under `docs/`.

## Product
Build a configurable web application for the internal technical workforce of a manufacturing enterprise: mechanics, electricians, energy, automation/PLC, robotics, metrology and other engineering services.

TWM is not primarily payroll, HR document administration, SCADA, or a complete EAM/CMMS. Its core workflow is:
organization → person/resource → verified competence → valid credential/permit → availability → technical work order → explainable candidate matching → human-confirmed assignment → workforce analytics.

## Non-negotiable engineering rules
1. **Modular monolith first.** Keep domain boundaries clear; do not introduce microservices without evidence.
2. **Stable core + configurable metadata.** Keep critical domain data relational and typed. Use JSONB only for configuration documents and carefully scoped custom attributes. Do not use one generic EAV model for the entire application.
3. **Backend is the source of truth.** Frontend must not duplicate or bypass authorization, safety, assignment, or scheduling rules.
4. **Safety gates are hard constraints.** A missing, expired, unverified, or out-of-scope mandatory credential must block assignment. Ranking scores, admin convenience, AI and manual selection cannot override it.
5. **Explainability.** Return reasons why a candidate is accepted or rejected.
6. **Auditability.** Audit security, credential, skill approval, configuration publication, assignment and other material changes.
7. **Config-first.** Enterprise-specific directories, competence catalogs, scales, credential types and supported custom fields must be configurable without code changes.
8. **No arbitrary code execution.** User-defined business rules must use a limited declarative expression/action model; never eval user-provided Python or JavaScript.
9. **No fake functionality.** A visible control must work end-to-end or be clearly marked as unavailable. Do not ship placeholder APIs as completed features.
10. **Preserve history.** Archive reference records instead of deleting those referenced by historical operations. Use effective dates where relevant.
11. **No invented safety/legal rules.** Do not hard-code jurisdiction-specific permit levels, expiry periods or industrial safety requirements without an explicit verified requirement.
12. **Keep the existing prototype.** Do not delete or overwrite `TWM_Configurable_Prototype_v0.1.html`; migrate scenarios incrementally.

## Baseline stack
- Frontend: React + TypeScript + Vite.
- UI: Tailwind CSS and shadcn/ui or a technically justified equivalent.
- Backend: Python + FastAPI + Pydantic.
- Persistence: PostgreSQL + SQLAlchemy 2.x + Alembic.
- Local development: Docker Compose.
- Tests: Pytest/HTTPX, Vitest/Testing Library and Playwright for critical E2E flows.
- CI: GitHub Actions.

Check current supported versions and compatibility before pinning dependencies. Avoid new services/dependencies until a real use case requires them.

## Security baseline
- RBAC with resource scope (enterprise/site/department/own records) enforced server-side.
- Secure password hashing (Argon2id) for local auth, or an explicitly configured OIDC provider.
- HttpOnly/Secure/SameSite cookies and CSRF protection for cookie sessions.
- Do not log secrets or unnecessary personal data.
- Validate access to every file download/upload.
- Recheck mandatory credentials and assignment constraints in the backend transaction.

## Data conventions
- UUID identifiers for domain records.
- Store timestamps consistently in UTC; use explicit site/calendar IANA time zones for shift rules and local display.
- Use normalized relational tables for core entities.
- Version published configuration; validate drafts before publication.
- Keep created/updated timestamps and actor references on important records.
- Use migrations for every database schema change.

## Required workflow for every task
1. Inspect the repository, related code, documentation and current branch.
2. Identify affected domains, APIs, DB models, migrations, UI, permissions and tests.
3. Write a short implementation plan before broad changes.
4. Implement one complete vertical slice.
5. Add/adjust unit, integration and E2E tests for the affected behavior.
6. Run the checks that are available; report exact commands and actual results.
7. Update docs and roadmap to reflect actual implementation.
8. Summarize changed files, commit/PR reference and known limitations.

Do not claim tests passed when they were not run. Do not mark a roadmap item done merely because a UI mock or stub endpoint exists.

## Git workflow
- `main` is stable; work on `feature/*`, `fix/*`, or `docs/*`.
- Submit changes through PRs.
- Avoid force-pushes and direct commits to `main`.
- Keep changes small and reviewable.
- Never add credentials, production personal data, or secrets to Git.

## Definition of Done
A task is complete only when the user workflow works end-to-end; backend permissions and business constraints are enforced; data persists; migrations work from a clean database; critical rules have tests; errors/empty/boundary cases are handled; and documentation reflects the actual implementation.
