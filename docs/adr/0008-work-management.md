# ADR-0008 — Work Management with three independent hard staffing gates

**Status:** Accepted for PR #10 (first integration slice)  
**Date:** 2026-11-13  
**Depends on:** ADR-0003 organization scopes, ADR-0004 personnel,
ADR-0005 approved competence, ADR-0006 mandatory credentials,
ADR-0007 calendar and reservations

## Architectural decision

Work Management is the first business process that *uses* the preceding
subsystems to allocate a technical employee to a real planned task.

A successful assignment must satisfy **all** of the following independently:

1. **Organization:** active Person/WorkforceResource, primary department matching
   the WorkOrder target organization unit across the requested calendar dates.
2. **Competence:** every required Skill has a current latest-approved assessment
   whose scale matches the Skill's immutable scale version, and whose level
   ordinal is at least the required minimum. Pending and rejected records are
   never used. A new lower approved rating supersedes an older higher one.
   An archived Skill blocks assignment.
3. **Credentials:** every mandatory CredentialRequirement configured for the
   WorkOrder activity code is satisfied by an independent verified record on
   **all relevant work dates**, including work spanning midnight. An activity
   without a configured credential policy **fails closed**. Missing, expired,
   revoked, unverified and future-effective credentials block.
4. **Availability:** the entire planned interval fits a single valid ShiftRule,
   the employee has an assignment, and no enterprise closure, absence or active
   booking intersects the interval.

An attempt with any blocker must not create an assignment or reservation.
The API exposes explainable per-gate results, not a single opaque score.
It is possible for an employee to be technically competent but to remain
**ineligible** because of a legal credential or a calendar conflict.

## Entities and immutable requirements

- `WorkOrder`: enterprise, target unit, unique code, title, optional description,
  activity code, UTC planned start/end and lifecycle status.
- `WorkSkillRequirement`: snapshot of a Skill and minimum level in the
  Skill's immutable scale version. 1–20 unique required skills must be supplied
  when creating each WorkOrder. Cross-tenant, unknown and mismatched scale levels
  are rejected and constrained by composite PostgreSQL foreign keys.
- `WorkOrderAssignment`: one responsible Person/WorkforceResource and one
  reserved `WorkReservation`, with enterprise, creator and timestamp.
  Database UNIQUE on work_order_id prevents multiple assignees in PR #10.
- `WorkAuditEvent`: append-only creation, assignment, start, completion and
  cancellation records written together with their state changes.

Requirements, planned dates and unit are fixed after creation: **no update or
edit endpoint** can reduce skill thresholds or change activity classification.
If the work must change, cancel and create a new WorkOrder. A unique work code
is enterprise-scoped. This first slice supports *one* responsible assignee,
not crews, multiple resources or substitution.

## State machine

```text
open --> assigned --> in_progress --> completed
  |         |             |
  +---------+-------------+--> cancelled
```

Only the displayed transitions are available. Terminal statuses cannot be
reopened. An open WorkOrder remains unstaffed until a separate explicit
assignment action passes all checks.

- `create`: scoped admin/manager supplies work metadata and skill thresholds.
  A WorkOrder may be created before any matching candidates or permit
  configuration exists; it cannot be assigned unless all checks pass.
- `assign`: re-evaluates all gates **under an enterprise PostgreSQL row lock**;
  creates the WorkReservation and WorkOrderAssignment in the **same transaction**;
  then transitions open to assigned. Repeated assignment returns 409.
- `start`: only within the scheduled interval according to **server UTC clock**;
  verifies that the original WorkReservation is still active and matches the
  WorkOrder interval and resource. Re-evaluates the same gates, excluding only
  the **own** reserved slot to avoid self-conflict; detects revoked permits,
  lower verified competence, late absences, closure or canceled reservations
  before work begins.
- `complete`: only in_progress → completed. Records timestamp/audit.
- `cancel`: open/assigned/in_progress → cancelled. Marks associated reservation
  cancelled within the same transaction; preserves order and audit history.

Reservation operations serialize on the same Enterprise row lock used by
Availability (PR #9) and Personnel/credential mutations. The scope of this
guarantee is **writers using these application APIs**. Independent database
writers must be restricted; PostgreSQL concurrency tests are needed.

## Matching semantics

- `GET /orders/{id}/candidates` returns up to 100 active resource-bearing
  Persons in the task's department, sorted with eligible first.
- Each CandidateView contains per-gate blockers with stable source/code/message,
  verified skill IDs and credential record IDs. This is a diagnostic shortlist:
  **never trust a previously returned eligible flag to assign**.
- `GET /orders/{id}/candidates/{person_id}` evaluates a specific accessible
  staff member to explain their eligibility, including wrong department.
- WorkOrder evidence and credential IDs are metadata, not independently
  authenticated records from authoritative issuers. Skill ratings themselves
  are submitted and approved by existing users (ADR-0005/6).

## Authorization and privacy

- `admin`: all WorkOrders and staff for the installation (initial admin role).
- `manager`: can create, inspect, dispatch, start, complete and cancel WorkOrders
  in explicitly granted organization unit scopes; assignments are checked
  against both WorkOrder scope and Person visibility **again after locking**.
- `viewer`: read-only WorkOrders and scoped candidate lists; mutations denied.
- All writes require CSRF validation and an authenticated user.
- A Person in another enterprise is never a candidate. A manager cannot
  enumerate another department using a guessed Person or WorkOrder UUID.
- No email/phone, absence explanation or personal credential document metadata
  is exposed through matching responses; only decision outcomes and IDs.
- Historical audit is administrator-only.

## API surface

- `POST/GET /api/v1/work/enterprises/{enterprise_id}/orders`
- `GET /api/v1/work/orders/{order_id}`
- `GET /api/v1/work/orders/{order_id}/candidates`
- `GET /api/v1/work/orders/{order_id}/candidates/{person_id}`
- `POST /api/v1/work/orders/{order_id}/assign`
- `POST /api/v1/work/orders/{order_id}/start`
- `POST /api/v1/work/orders/{order_id}/complete`
- `POST /api/v1/work/orders/{order_id}/cancel`
- `GET /api/v1/work/audit` (admin)

## Explicit safety boundary

**This is an internal scheduling/eligibility gate, not a certified safety
function or legal permit-to-work system.** It does not ensure isolation/LOTO,
machine-specific authorizations, current site conditions, PPE, human
permit issuance, risk assessment, job handover or jurisdictional legal rules.
It must not autonomously authorize hazardous work.

Known initial gaps:
- No digital signing, approved permit issuance by authoritative regulators,
  or automated certificate provenance checks.
- No crew assignment, task decomposition, machine/resource reservations,
  emergency overrides, formal dispatch reviews, attachment storage or dispatch
  notifications.
- No *continuous* monitoring after a WorkOrder becomes in_progress. Later
  revocation/absence is caught at start but **not an automatic stop**.
- A manually canceled reservation is detected and blocks `start` but the
  WorkOrder status remains assigned until explicitly canceled/reconciled.
- WorkOrder list capped at 100; candidate list capped at 100, without pagination.
- No audited rejection events for attempts denied with 409, no service level
  objectives or conflict resolution after external schedule edits.
- SQLite API tests validate rules; PostgreSQL migration runs in CI.
  Multi-transaction PostgreSQL race tests and full Docker browser tests still
  needed before production.
- Existing identity/access system remains a development foundation; not ready
  for real personal records or high-risk industrial permit authorization.

**Use synthetic records only. Merge does not signify production approval.**
