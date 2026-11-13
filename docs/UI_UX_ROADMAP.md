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

### PR #14 — Unified app state and navigation (implemented)

A React WorkspaceProvider now shares the scoped enterprise, selected
department and Person across the right rail and major business modules.
Topbar personnel search uses the authenticated current-enterprise endpoint.
Breadcrumbs show the current navigation and workplace context. Logout,
account changes and enterprise changes invalidate stale selections.
Browser E2E covers cross-department lookup and account isolation.
See `docs/adr/0010-shared-workspace-context.md`.

Deferred to dedicated follow-up UX iterations: shared date range, saved
filters, full Person summary cards, cursor-based searches/pagination beyond
current endpoint limits, subtree (vs. direct department) filters and advanced
keyboard navigation. The hash-based routes continue to be sufficient.

### PR #15 — Operational dashboard & analytics (implementation in review)

Operational dashboard for all authenticated roles with organizational RBAC.
The first version uses a fixed 30-calendar-day UTC trend window and 30-day
credential renewal horizon. Availability means reservable for the next 15
minutes (shift, closures, absences, active reservations); it is not a physical
presence or a legal/safety authorization claim. Reservations are reported as
hours, not a guessed utilization percentage. Metrics, limits and API semantics:
`docs/adr/0011-operational-analytics.md`.

Acceptance: scoped cross-enterprise/unit reads, empty/zero cases, inactive
resources, expiry boundaries, cancelled bookings, dashboard navigation, account
switching and CI checks. Do not mark complete before test evidence.

### PR #16 — Configurator and governed workflow (in review)

First governed vertical slice: enterprise-specific custom metadata for Person
profiles (text, integer, boolean, controlled-choice dictionary). Draft versions
have strict declarative validation, independent administrator approval,
effective-date publication and immutable published history. Person field updates
store immutable revisions and apply only the effective published schema.
Backend RBAC remains authoritative; new fields are informational and are never
used for safety qualification, credentials, authorization or work-order gates.
See `docs/adr/0012-governed-configuration.md`.

Remaining PR #16/Phase 8 backlog: domain workflow transition configurability,
general custom attributes for additional entities, a catalog governance UI for
existing domain dictionaries, per-field reporting, multi-enterprise delegation
and revision comparison. These are *not* implemented in this slice.

### PR #17 — Equipment, work permits and safety workflow (in review)

Equipment assets and append-only equipment-specific credential policies, an
immutable asset-to-WorkOrder link (before staffing), and a versioned human
permit-to-work record (draft → submitted → independent approval → revocation).
Three explicit site-condition attestations and an evidence reference are
required for submission; these are *assertions*, not verified physical checks.
Each equipment-linked order must have its most recent permit approved and
equipment active before work start, resume or successful safety revalidation.
In-progress work is put on an HRMS hold if its permit is revoked, equipment is
marked out of service, or stricter equipment credential policy is added.

Remaining engineering work: certified PTW compliance, equipment-specific
skills, tamper-resistant evidence uploads, periodic mandatory rechecks, PLC/
robot/machine interlock integration, LOTO verification and operator training.
No legally effective PTW or physical machine protection is claimed.
See `docs/adr/0013-equipment-permit-workflow.md`.

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

### PR #18 — Equipment Skill Gates & Software Readiness (in review)

Append-only machine-specific skill thresholds are enforced in addition to each
work order's existing approved skill requirements and safety credentials. The
latest approved assessment governs, and late policy additions move affected
running work to an audited HRMS hold.

An RBAC-filtered equipment-linked work overview shows permit/asset **software**
blockers and hold counts in the Equipment module. This is explicitly NOT an
examination of crew eligibility, a certified safety assessment, physical
interlock or a legal work authorization. See ADR-0014.

Remaining: scheduled rechecks, qualified independent policy approval,
operational asset inspection evidence, immutable site PTW certificates and
system-level safety integration with certified external processes.
