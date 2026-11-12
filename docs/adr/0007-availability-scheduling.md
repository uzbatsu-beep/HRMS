# ADR-0007 — Recurring shift calendars and conflict-safe planned reservations

**Status:** Accepted for PR #9 (development baseline)  
**Date:** 2026-11-13  
**Depends on:** ADR-0003 Organization scopes, ADR-0004 Personnel, ADR-0006 Credentials

## Context and objectives

The system already distinguishes Persons from assignable WorkforceResources and
stores their dated primary department assignments. A skills/certificates matrix
does not imply a specialist is on shift or available during a requested interval.

The first scheduling slice must distinguish:
- **shift coverage:** working hours expected according to the person's recurring
  weekly schedule;
- **enterprise closures:** holidays and production shutdown days;
- **resource unavailability:** leave, training or other blocking intervals;
- **planned workload:** existing time reservations that must not overlap;
- **person's employment state and primary departmental assignment.**

## Data model

- `ShiftRule`: per-resource recurring weekly weekday (Monday=0..Sunday=6),
  IANA timezone, local start/end clock time, effective calendar-day range,
  and optional non-destructive `disabled_at`.
- `CalendarClosure`: enterprise-wide nonworking local calendar day keyed
  by enterprise/date/timezone. This is a simplified explicit holiday/shutdown
  mechanism, **not** an automatic jurisdictional public-holiday service.
- `AbsencePeriod`: resource-specific UTC timestamp range with half-open
  interval semantics, category `leave|training|unavailable`, optional admin-only
  note and optional cancellation timestamp.
- `WorkReservation`: a provisional resource-specific scheduled hold with
  UTC timestamps, optional enterprise-unique external reference, actor and
  optional cancellation timestamp. **Not a WorkOrder, assignment or permit.**
- `SchedulingAuditEvent`: append-only log of shifts, closures, absence and
  reservation create/disable/cancel operations in the same transaction.

All resource references carry enterprise ID and have composite same-enterprise
FKs. Shift rules are not overwritten after use; disable and publish another
rule. Absence/reservation cancellations retain original records.

## Interval and timezone policy

- API receives full ISO 8601 **offset-aware** instants; it normalizes and stores
  timestamps in UTC. Local input fields in the first React UI are explicitly
  labeled **UTC**, not the browser's local timezone.
- Intervals are **half-open [start,end)**. An appointment ending at 10:00
  does not conflict with one starting at 10:00.
- Requested availability/reservation interval must be nonzero, <=24 hours.
- Each recurring weekly shift is defined in a named IANA timezone; if local
  end <= local start, it is an overnight shift ending on the next day.
- An interval is eligible only if it fits entirely inside **one** recurring
  shift occurrence. Combining separate adjacent shifts is intentionally not
  implemented in this first release.
- DST gap and fold values are **fail closed**. If a shift boundary is
  nonexistent or ambiguous, that occurrence does not count as valid shift
  coverage and returns a reason when relevant; no arbitrary fold resolution
  is guessed. Valid unambiguous overnight shifts across DST remain possible.
- A Person must have an effective primary EmploymentAssignment across the
  corresponding local dates; a mid-interval unit change blocks availability.
- Enterprise closures supersede shift coverage; any intersection with a
  designated local non-working calendar date blocks the requested interval.

## Fail-closed calendar evaluation

`evaluate(db, person, workforce_resource, start, end)` returns
`available` and explicit blockers. It denies if:

1. Person is archived or workforce resource is inactive;
2. no valid single shift covers the entire requested period;
3. no primary employment assignment exists for each local calendar date
   or the unit changes mid-interval;
4. the interval touches any configured enterprise closure;
5. it intersects any active absence period;
6. it intersects any active existing reservation.

The function does **not** check legal credential validity or competence.
Future work assignment must combine `evaluate_activity` (PR #8), approved
competence requirements (PR #7) and scheduling availability at the **actual
assignment/start time**. A successful calendar query must not imply safe work
eligibility.

## Authorization and sensitive information

- All mutations are **admin only** in this initial release and require CSRF.
  Manager/viewer roles have read-only access restricted by current primary
  departmental grants (ADR-0003/4). A linked employee may view their own
  calendar even without rights to other departments.
- Nonadmins see unavailability periods but never the absence category/note.
  They see booked time but not the external work reference. This masks
  potentially sensitive details while preserving basic calendar visibility.
- Out-of-scope Person endpoints return 404.
- Audit is admin-only.

## Preventing double bookings

When a new reservation is submitted, the server takes a PostgreSQL
`SELECT ... FOR UPDATE` lock on its Enterprise, refreshes the resource
and Person, and rechecks availability before inserting the new reservation.
Concurrent transactions creating reservations through this API serialize
on that Enterprise lock and cannot both book the same interval.

SQLite fixtures verify business logic but do **not** reproduce PostgreSQL
concurrency locking. A specialized concurrent PostgreSQL integration test is
required before production. Out-of-band writers bypassing the API must be
forbidden or protected by database policies.

Absences, calendar shutdowns or shift changes entered after a reservation
**can invalidate a previously booked slot**. In this baseline they are
authoritative; the next availability query reports blockers, but automatic
reservation suspension or dispatch escalation is deferred.

## Workload semantics

`GET /persons/{id}/load` returns:
- sum of active reservation minutes intersecting a requested range;
- sum of active absence minutes intersecting the same range;
- active reservation count.

This is a **planned booked-time summary, not a utilization percentage**.
It does not account for legal rest rules, scheduled breaks, paid hours, FTE
capacity, labor-law compliance, partial-day overtime, closure reductions or
deduplicate overlapping absence records. Avoid treating it as payroll or OEE.

## Initial API

- `GET/POST /api/v1/availability/enterprises/{enterprise_id}/closures`
- `POST /api/v1/availability/resources/{resource_id}/shifts`
- `POST /api/v1/availability/shifts/{rule_id}/disable`
- `POST /api/v1/availability/resources/{resource_id}/absences`
- `POST /api/v1/availability/absences/{absence_id}/cancel`
- `POST /api/v1/availability/resources/{resource_id}/reservations`
- `POST /api/v1/availability/reservations/{reservation_id}/cancel`
- `GET /api/v1/availability/persons/{person_id}/calendar?start&end`
- `GET /api/v1/availability/persons/{person_id}/check?start&end`
- `GET /api/v1/availability/persons/{person_id}/load?start&end`
- `GET /api/v1/availability/audit` (admin)

## Deferred for production

1. Organizational shift templates and propagation, configurable holidays,
   editable calendar exceptions, recurring absence rules and substitutions.
2. Labor-law compliant rest/overtime rules, paid leave and accruals.
3. Work-order transactional linkage, capacity >1, bookings against equipment
   and explicit machine+credential authorization.
4. Enterprise configured timezone by site rather than per-rule manual input.
5. Event notifications, revalidation and automatic conflict escalation after
   shift, closure or absence changes; scalable calendar indexing/pagination.
6. True workload capacity calculations, duplicate absence unioning and
   configurable FTE/shift lengths.
7. Fine-grained self-service leave requests, manager approval workflows,
   secure privacy controls and production authentication.

**Development/test only with synthetic personnel and safety data.**
