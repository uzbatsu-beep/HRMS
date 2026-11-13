# ADR-0016 — Explicit, redacted crew readiness snapshots for equipment-linked work

Status: PR #20, development/synthetic-only.

## Motivation

PR #18's equipment readiness overview intentionally checks only the asset
and the latest permit. A green equipment/permit overview **cannot** demonstrate
that assigned people have a valid skill, mandatory credential, shift, reservation
or equipment-specific competence. Those conditions may have changed after
staffing. PR #20 adds an **explicit user-initiated** read-only crew snapshot
rather than pretending that summary counts establish work authorization.

## API and authorization

\`GET /api/v1/equipment/orders/{order_id}/crew-readiness\`

- Authenticated *admin* or *manager* only (dispatcher role).
- A non-admin must have explicit unit grants for **both** the WorkOrder's
  organizational unit and its linked EquipmentAsset's unit. Unlinked, unknown,
  hidden or cross-tenant linked work yields a generic 404.
- Reuses the centralized \`work.execution.team_safety_check\` to evaluate every
  currently assigned participant's latest approved skills, activity permits,
  equipment-specific qualifications, reservation and calendar and asset/permit
  maintenance gates.
- Returns only status, check timestamp, whether the leader exists, total
  participants and failing participant count, sorted/de-duplicated **blocker
  codes** and an explicit redacted read-only marker. No names, identifiers,
  personnel records, document references, credential values or per-person
  diagnoses are included. Zero crew is represented by LEADER_NOT_ASSIGNED.
- Preserves \`work_orders.last_safety_check_at\`, order status and all audit
  rows: the GET does not acquire a write lock or issue a state transition.
  Calling it does **not** trigger a work hold, confirm actual machine state
  or satisfy a required manual work revalidation.

## UI semantics

Existing multi-job equipment overview remains lightweight, role-scoped and
**asset/permit-only**. Each authorized Admin/Manager may explicitly click
"Проверить бригаду" on a visible equipment-linked job to request a point-in-time
snapshot. The result shows timestamp, counts and localized blocker codes.
The result is reset before a repeated check, and is not cached as an
authorization. Viewers do not get the control or access to the new API.

The server-side work-order start/resume/revalidate/complete endpoints remain the
only authoritative workflow gate. For a persisted revalidation, dispatchers
use the existing WorkOrder controls; no background job or automatic recheck
loop is introduced here. No PLC, robot or hardware interlock is performed.

## Safety boundary

This is a **software planning diagnostic**. It does not establish actual
workplace conditions, physically isolate energy, certify a safety inspection,
issue a legal permit-to-work or command a machine. Codes are informational
snapshots and may become stale immediately after reading. Real machinery
requires independent site/LOTO rules and certified safety systems.

## Acceptance criteria

- Backend: unstaffed, staffed/qualified, revoked permit, redacted codes,
  no work-status/audit mutations, unit and role authorization, unlinked and
  unknown job rejection.
- Frontend: scoped row action, explicit timestamp and blocker mapping,
  no automatic crew checks during bulk overview fetch.
- CI: Ruff, PostgreSQL migrations, full Pytest, TypeScript/Vite and Chromium
  Playwright synthetic E2E, with no regression of existing hard gates.
