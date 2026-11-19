# ADR-0023 — Exact-unit Work Management operation grants and job-function templates

**Status:** Proposed in PR #30; not merged/approved  
**Date:** 2026-11-19 · **Environment:** synthetic development data only.

## Problem

Historically `admin` or an organization-scoped `manager` could perform all
work-order mutations. An ordinary technician or dispatcher could not perform a
specific job function without receiving the broad manager role.

## Decision

Migration 0019 extends the existing `UserUnitPermission` constraint with
the following independent operations:

| Operation | Allowed action |
|---|---|
| `work.order.create` | Create a WorkOrder in that unit |
| `work.order.assign` | Assign the lead and reserve their interval |
| `work.crew.manage` | Add/remove crew and replace lead |
| `work.order.priority` | Change the priority before start |
| `work.order.start` | Start after mandatory revalidation |
| `work.order.complete` | Complete after mandatory team revalidation |
| `work.order.cancel` | Cancel and release reservations |
| `work.order.revalidate` | Record a manual recheck; move to hold on failure |
| `work.order.hold` | Manually suspend WorkOrder in software |
| `work.order.resume` | Resume only after mandatory team revalidation |

Non-manager users must satisfy **both** current ordinary scope **and** an
**exact-unit** operation grant. Inherited descendant visibility does not imply
inherited operational rights. Revocation is evaluated on the next request;
critical writes recheck permissions after the enterprise transaction lock.

Backward compatibility: `admin` retains installation-wide operations;
`manager` retains historical WorkOrder privileges inside current unit scope.
Manager broad rights are transitional, not full least-privilege RBAC.

### Fixed templates, not new login roles

| Code | Granted operations |
|---|---|
| `work.planner` | create, priority |
| `work.dispatcher` | assign, crew.manage, priority |
| `work.supervisor` | start, complete, cancel, revalidate, hold, resume |
| `work.coordinator` | all ten `work.*` operations |

Administrators manage templates using
`GET /api/v1/org/permission-templates` and
`POST /api/v1/org/permission-templates/apply` with `user_id`, `unit_id`,
`template`. Application adds only missing grants under an enterprise lock,
in one transaction. Each grant and template application is auditable.
It never silently issues an organizational scope or changes `UserAccount.role`.
Individual permissions can still be removed through the existing
`DELETE /api/v1/org/permissions/{grant_id}` endpoint.
Invalid template IDs and unauthorized administrative actions fail closed.

### Server-derived capabilities

`GET /api/v1/work/enterprises/{enterprise_id}/units/{unit_id}/capabilities`
and `GET /api/v1/work/orders/{order_id}/capabilities` return only the current
caller's per-operation booleans for ordinarily visible scopes.
The UI conditionally displays actions based on these responses. Any browser
state may be stale; the server never trusts a client capability boolean.

**Excluded:** asset policy proposals, equipment permit approval, competency
review, credential verification and user management. No Work grant overrides
required skills, credentials, shift windows, reservations, approved equipment
permits, safety revalidation or PostgreSQL locking.

### Safety and pilot boundaries

A WorkOrder `on_hold` flag is application state, not an industrial safety
system, physical machine stop, certified LOTO/PTW or legal work permit.
No real employee data may be introduced without completing the production
security/pilot gate in `docs/SECURITY_HARDENING_PLAN.md`.

### Verification requirements

Tenant and unit isolation, inherited scope versus exact grant, CSRF, template
idempotency and audit, grant revocation without logout, legacy manager behavior,
no privilege to modify ungranted operations, hard checks on candidate matching
even for a delegated dispatcher, migration and no-data-loss downgrade guard.
Ruff, Alembic PostgreSQL, pytest, TypeScript, Vite and Playwright all mandatory.
