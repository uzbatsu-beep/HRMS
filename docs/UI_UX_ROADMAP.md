# HRMS UI / UX implementation plan

Date: 2026-11-13. Status: active development guidance.

## Motivation

A deployed desktop screenshot shows the former narrow, single-column
foundation landing page despite functional domain modules being present.
Managers should navigate between modules rather than scroll through all
forms on a single page. Wide monitors should show relevant context next to
the active domain workspace.

## PR #12 — Operational workspace shell

- Full-width responsive layout: navigation (left) + current workspace (center)
  + contextual organization/personnel rail (right).
- Single selected module renders in the central workspace; modules remain
  unchanged in their business logic.
- URL hash reflects selected module. Legacy `#home` is understood as dashboard.
- Right rail displays **real** scoped enterprises, hierarchical organizational
  units and searchable personnel from existing authenticated endpoints.
- Selecting a unit filters the visible employee list; selecting a Person
  opens their PersonnelPanel profile.
- Sidebar state and sign-in refresh update without a full page reload.
- Small displays get a menu toggle; on medium widths the right rail moves
  beneath the central module.
- Dashboard is now a navigation overview rather than a false "planned" list
  of already deployed modules.
- Scope/security: no local fallback to fake employee data. Existing backend
  permissions remain authoritative; all reads use current user's session.

### PR #12 acceptance checklist (local Docker browser)

- [ ] Admin can load the app and view all permitted enterprises in the right rail.
- [ ] Existing real organizational units appear with correct indentation.
- [ ] Selecting a unit shows only personnel in that unit (direct membership).
- [ ] Search filters by employee code/name using the backend list endpoint.
- [ ] Clicking an employee opens the Personnel module and their selected card.
- [ ] Left navigation switches each existing module, without scrolling over
      other modules, and updates `#dashboard`, `#personnel`, etc.
- [ ] Refreshing the browser with `#work` opens Work Management.
- [ ] Authorized manager sees only permitted enterprise/unit/employee data.
- [ ] Viewer cannot access administrative mutations.
- [ ] Sign-in/logout updates the rail and user info without page reload.
- [ ] Desktop, tablet and mobile widths remain navigable.
- [ ] No changes to PostgreSQL schema or existing Work Management safety gates.

CI TypeScript and Vite checks are not a browser acceptance substitute.
Run this checklist with synthetic data before deciding to merge.

## Recommended subsequent PRs

### PR #13 — Browser E2E + demonstration fixture

Introduce Playwright and a deterministic, synthetic demonstration fixture.
Test login, organization/personnel, skills, credentials, shifts,
explainable work matching, crew assignment, late permit revocation, hold,
and cancellation. Publish screenshots, trace files and CI artifacts on failure.
Test low-width navigation and right rail access scopes.

### PR #14 — Unified app state and navigation

Replace separate enterprise selection states in each panel with a shared,
scoped app context (enterprise ID, unit ID, selected Person, date window).
Add breadcrumb trails, global search, complete person details via right rail,
saved filters and meaningful empty/loading/error states. Introduce robust
route semantics (potentially React Router) only when necessary.

### PR #15 — Operational dashboard & analytics

Provide a first workbench with current workforce availability, active work
orders, credentials due for renewal, resource workload, unresolved safety
holds and trends. Every metric must have backend-authoritative definitions.
No invented utilization percentages or made-up availability calculations.

### PR #16 — Configurator and governed workflow

Support enterprise-configurable dictionaries, additional fields, rules and
workflow transitions with draft/validate/publish, effective dates, versioned
history and explicit approval. Prevent configuration from bypassing mandatory
credentials, personnel scopes or audit invariants.

### PR #17 — Equipment, work permits and safety workflow

Link WorkOrders to machines/assets, skills and credentials applicable to
specific equipment, human approvals, documentary evidence, controlled
site checks, and permit-to-work workflows. Formal compliance and equipment
interlocks require specialist review and separate engineering governance.

### Parallel hardening

Harden authentication and audit/retention, publish role-permission matrix,
validate concurrent PostgreSQL assignment behavior, secure uploaded
attachments and protect personal data. Browser E2E should become a merge gate.

## Running the development UI

```powershell
git switch main
git pull --ff-only
docker compose up --build -d
```

If PR #12 has not been merged and you want a preview:

```powershell
git fetch origin feature/workspace-shell-navigation
git switch --track origin/feature/workspace-shell-navigation
docker compose up --build -d
```

Open `http://localhost:5173/#dashboard`.
The backend is unchanged in PR #12. Use only synthetic personnel/credentials
while validating. The production-like operational workflow does not itself
authorize hazardous work.
