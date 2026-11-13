
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


## PR #6 — Personnel Management (Phase 3 first vertical slice)

- Created separate `Person` and assignable `WorkforceResource` entities with stable UUIDs.
- Introduced dated primary `EmploymentAssignment` and additional `TeamMembership` history.
- Implemented personnel roster/list/search, individual cards, updates, archive,
  assignment creation, atomic department transfers, team joins and team closure.
- Connected to PR #5 server-side scopes: nonadmins read only workers currently
  assigned to a granted primary organizational unit; additional team affiliations
  do not independently grant profile access.
- Added personnel audit and migration `0004_personnel`, temporal validation and
  cross-enterprise relational consistency.
- React panel supports roster, filtering, profile creation/edit, transfer, team membership
  and archive. Existing standalone HTML prototype is unchanged.
- Pytest integration scenarios cover default-deny, tenant isolation, dated transfers,
  team non-disclosure, history, archive, duplicate codes and time interval conflicts.

Limitations: no position catalogue, fine-grained field PII permissions, production
authentication safeguards, import/export or qualification/competence integration yet.
Do not use synthetic-stage build for real HR records.


## PR #7 — Competence Management (Phase 4 first vertical slice)

Implemented:
- Configurable enterprise-scoped hierarchical skill categories and unique
  technical skill codes.
- Published immutable SkillScale versions with 2–10 scale levels.
- Multi-enterprise data boundaries and PostgreSQL composite foreign keys for
  categories, scale versions, skill references and levels in assessments.
- Explicit admin-created UserPersonLink so linked staff can self-assess without
  impersonating another employee.
- Pending self/expert assessments and 0–8 evidence metadata records per proposal.
- Independent manager/admin approve/reject with justification; no self-approval
  or review of a proposal submitted by the reviewer.
- Verified competence matrix based solely on last approved, active Skill ratings.
- Application-level current-unit RBAC scope filtering, evidence/review audit.
- React configuration, submission, review and matrix UI.
- Alembic `0005_competence`, API tests and ADR-0005.

Still incomplete: secured evidence attachments, lifecycle/expiry of assessments,
skill-scale migrations, advanced configurable field forms, delegated admin,
personnel privacy controls and a genuine industrial safety permit subsystem.
Development/test-only. Do not load real personnel or certificate data.


## PR #8 — Credentials Management (Phase 5 first vertical slice)

- Per-enterprise CredentialType dictionary with mandatory expiry for
  safety-critical credential types.
- Persistent PersonCredential records with issue/start/expiry dates and
  independent pending → verified/rejected → revoked lifecycle.
- Immutable additive CredentialRequirement records for `activity_code`.
- Server-side reusable fail-closed `evaluate_activity()` policy: deny with
  `NO_POLICY` when no rules exist; AND across all required types; reject
  missing, unverified, expired, revoked and future-effective records.
- Non-admin person-level scope enforcement and owner linked-identity reads.
- Write CSRF, independent reviewer, admin revocation, PostgreSQL composite
  tenant constraints and audit events.
- React panel for type/rule creation, document records, review, revocation
  and date-specific activity eligibility diagnostics.
- Alembic `0006_credentials`, regression tests and ADR-0006.

**Not yet implemented:** cryptographically/physically verified documents,
work order transaction enforcement, effective-dated policy publication,
machine-specific credential applicability, notifications and production identity.
Do not load real HR or high-risk safety permit data.


## PR #9 — Availability & Scheduling (Phase 6)

Implemented:
- Per-resource weekly ShiftRule with IANA timezone, effective date range,
  overnight shift support and non-destructive disable.
- Enterprise CalendarClosure for explicit local holidays or shutdown days.
- UTC-aware half-open AbsencePeriod and WorkReservation with cancellations.
- Fail-closed availability policy requiring one shift, active resource,
  full primary assignment, no closure, no absence and no conflicting booking.
- Ambiguous/nonexistent DST boundaries rejected; no guessed local offset.
- Transactional enterprise lock plus availability recheck for planned bookings.
- Organization-scoped read permissions; linked self-read; admin-only
  CSRF-protected writes and audit trail.
- Planned booked minutes, absence minutes and reservation count (not FTE
  utilization or payroll).
- React scheduling control panel with checks, shifts, closures, absences
  and reservations; PostgreSQL migration `0007_availability`; tests,
  ADR-0007 and README guidance.

Known gaps: no legal labor-law calendar, no actual WorkOrder assignment,
no machine authorization, no automatic conflict escalation after changed
leave/holiday/schedules, no manager leave approvals and no production privacy
or authentication hardening. Development/test and synthetic records only.


## PR #10 — Work Management (Phase 7)

Implemented:
- WorkOrder entities for enterprise, organizational unit, activity code,
  offset-aware planned window, unique code, creator and lifecycle;
  1–20 immutable per-order minimum approved skill thresholds.
- Composite PostgreSQL FKs tie WorkOrder, Skill, scale/level and assignee to
  same enterprise; unique WorkOrderAssignment limits this slice to one
  accountable assignee per work order.
- Explainable candidate matching: current primary unit, latest approved
  competence at or above each threshold, mandatory independently verified
  credential policy on relevant dates, and absence-free shift/closure/calendar.
- Fail closed on missing activity permit policy, missing skill assessment,
  wrong skill scale, archived skill, expired/revoked credentials, no shift,
  absence, holiday, existing reservation, inactive Person or wrong unit.
- Scoped admin/manager dispatch; viewer read-only; CSRF; tenant isolation.
- Atomic assignment plus WorkReservation inside PostgreSQL enterprise lock.
  A stale prior UI eligibility result cannot bypass the fresh server decision.
- At planned start, re-evaluate all gates and ensure same active WorkReservation;
  exclude only its own booking from overlap checks.
- Lifecycle: open → assigned → in_progress → completed, cancellation from
  nonterminal stages, preserving immutable audit and releasing reservation.
- React Work Management module with creation, candidate explanations, dispatch,
  start/complete/cancel, status board; migration 0008, tests and ADR-0008.

Not production-safe: no regulator-issued electronic permit, LOTO, site
hazard checks, machine-specific authorization, crew staffing, continuously
enforced stop triggers after work begins, dual-control policy edits,
automatic repair of out-of-band reservation cancellation, load-balanced
candidate pagination or parallel Postgres race tests. Synthetic records only.


## PR #11 — Multi-person Work Crews & Manual Safety Holds (Phase 8)

- Optional WorkOrder priority with four fixed levels and audited amendments
  only before work starts (no safety override).
- One existing lead plus up to eight supporting participants with one
  WorkCrewMember and WorkReservation each, same-tenant composite constraints.
- Specialist, assistant and observer roles; **identical hard eligibility
  gates** for every person regardless of role.
- Crew add/remove and lead replacement under an enterprise-wide transaction
  lock. Cancel old time reservations without deleting audit history.
- Whole-roster pre-start check; any invalid/absent/withdrawn participant or
  canceled/mismatched reservation blocks start.
- Explicit GET safety diagnostic and POST revalidation. In-progress failures
  change work status to `on_hold` with an auditable reason.
- Manual hold/resume workflow: documented reason and fresh passing checks,
  no outside-window resume. Completion also rechecks and holds on failure.
- Cancellation releases all active participant reservations.
- React WorkExecutionPanel with roles, personnel changes, priority and
  explicit safety review/hold state.
- PostgreSQL revision `0009_work_execution`, regression coverage and
  ADR-0009.

**Safety disclaimer:** No background or event-driven watch of revoked
credentials or absences. `on_hold` does not interact with PLCs, drives,
robots or process safety hardware. No formal permit-to-work, lockout/tagout,
site hazard review, equipment-specific credential levels, team composition
policy or approved production data-protection controls. Synthetic data only.
