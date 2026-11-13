# ADR-0009 — Multi-person crew, audited lead substitution and explicit safety holds

**Status:** Accepted for PR #11 development implementation  
**Date:** 2026-11-13  
**Depends on:** ADR-0008 Work Management and prior domain checks.

## Problem

PR #10 can assign exactly one responsible Person to a technical task. Real
maintenance often requires several persons in distinct operational roles and
safe replacement of the person in charge. Planned tasks also need priorities
and a way to respond to revoked credentials or new absences **after** work starts.

These changes must **not** weaken existing competence, mandatory credential,
scope, or calendar hard gates.

## Model and roles

The existing `WorkOrderAssignment` remains the single **lead** for each WorkOrder.
There is still at most one responsible lead per job; replacements update that
single link transactionally and leave a full audit trail.

`WorkCrewMember` adds up to eight additional Persons to an already
**assigned** WorkOrder. Allowed roles:
- `specialist` — participating technical specialist;
- `assistant` — supporting worker;
- `observer` — observer participating in the job.

Every active crew member, **including observers**, must pass the full set of
PR #10 requirements for the activity: relevant approved skill level, active
mandatory credentials, same target department, valid working shift, no
absence, no calendar closure, and no conflicting reservation. Roles only
describe participation; they do not waive requirements or partition work.

Each member has one distinct WorkReservation covering exactly the job's
interval and is mapped to the WorkOrder with enterprise-safe composite
foreign keys. A participant cannot also be the lead or occupy two active
roles on the same WorkOrder. This first slice retains one record per
Person per WorkOrder; removed Person entries cannot be silently re-added
to the same job. Such changes require a new WorkOrder or future versioned
membership records.

## Concurrency and authorization

Writes are allowed to scoped `manager` and `admin` users only, with CSRF.

All mutations acquire the shared Enterprise row lock used in PR #10.
Before adding a crew member, the server **re-evaluates** eligibility under the
lock. The reservation and membership insert are committed atomically. A
late conflict returns 409 without allocating the Person.

Crew removal marks the membership and the reservation canceled (history
preserved) and requires a reason.

Lead replacement is allowed only for an `assigned` WorkOrder before it
starts. The new lead must pass all gates. The old reservation is canceled,
the new reservation created, and the current lead assignment updated
**in one transaction**. The old/new Person, reservations and reason are
captured in WorkAuditEvent. Assigning the same Person or an active crew
member as new lead is rejected.

No crew changes or lead replacements are possible once `in_progress` or
`on_hold`.

## Prioritization

WorkOrder gains a priority:
`routine | normal | urgent | critical`. Existing orders migrate to
`normal`. Priority is a dispatch/sorting field, **not** an override.
A scoped dispatcher can change it while the WorkOrder is `open` or
`assigned` with an auditable reason (minimum 10 non-whitespace characters).
After the job starts, priority is locked.

## Mandatory recheck of the complete roster

At `/start`, the server revalidates **all** active participants and their
individual reservations in addition to PR #10's existing lead gate.
One failed member blocks the whole work start. The check is on the
planned interval, and each participant's own reservation is excluded
from overlap detection; others' reservations are never excluded.

A separate `team_safety_check` explains all per-member blockers and
detects missing/canceled/mismatched reservation records. The
read-only `GET /safety` is diagnostic and never changes state.

`POST /revalidate` records an explicit, human-triggered check for an
`assigned`, `in_progress`, or `on_hold` order. If an active
`in_progress` order fails, it enters `on_hold` and records a full audit
event. A human dispatcher may also submit a manual hold with a mandatory
reason.

`on_hold` is **a software workflow state only**, not a machine interlock or
a certified safety stop. It prevents `complete` and requires documented
manual resume. Resume requires the current clock to fall inside the
planned interval, every roster member to pass a fresh full recheck,
and a substantive reason. Previously logged hold events are retained.

`complete` also rechecks the entire roster. If a new violation is
detected, it transitions the WorkOrder to `on_hold`, logs the reasons
and returns HTTP 409. Completion from `on_hold` is rejected.
Cancellation releases the lead and every active crew reservation.

**No continuous monitoring is implemented.** A credential revoked after
work starts is discovered only by a subsequent explicit revalidation or
completion attempt. No external machine, PLC, robot, or process is
automatically stopped. On-site procedures must handle actual safety
decisions and interventions.

## API additions

- `POST /api/v1/work/orders/{id}/crew`
- `POST /api/v1/work/orders/{id}/crew/{crew_member_id}/remove`
- `POST /api/v1/work/orders/{id}/replace-lead`
- `POST /api/v1/work/orders/{id}/priority`
- `GET /api/v1/work/orders/{id}/safety`
- `POST /api/v1/work/orders/{id}/revalidate`
- `POST /api/v1/work/orders/{id}/hold`
- `POST /api/v1/work/orders/{id}/resume`

Existing `WorkOrder` responses include `priority`, full crew history,
the current hold reason, and last recorded safety-check time.

## Constraints and production blockers

1. Physical proof of permit authenticity, regulator approval, LOTO,
   machine-specific authorization, risk assessment and PPE checks remain
   external to the product.
2. No continuous watching or event-driven response on credential revocation
   after work starts; current process requires manual revalidation.
3. No machine interlocks, automatic safety stop, human permit issuance,
   formal supervisor handover, equipment isolation or emergency stop wiring.
4. Every member currently shares the same skill threshold and credential
   policy. Role-specific skill policies and minimum role counts are deferred.
5. WorkOrder is still one 24-hour segment; no multi-day sequences, relief
   crews, shift handovers or parallel capacity >1 are implemented.
6. Individual crew membership is append-only within an order (removed
   members cannot be re-added). A formal versioned roster process is future work.
7. The interface is a planning/development tool; it is not a certified
   personnel safety system, even if all gates return passed.
8. PR tests use SQLite for API behavior and PostgreSQL for migration.
   A dedicated concurrent PostgreSQL race harness and staged site safety
   review are required before any production use.

**Only synthetic data are suitable for this stage.**
