# ADR-0011 — Operational Analytics v1 (PR #15)

Status: proposed for review. Read-only analytics; no new DB migrations.

## Scope and defaults

- Users: every authenticated role, with **backend** organizational RBAC.
- Enterprise required. A unit filter is optional; when omitted, count only the
  units in the user's currently permitted set, never the entire tenant by default.
- A forbidden or nonexistent enterprise or unit returns 404; anonymous 401.
  Unit hierarchy follows the existing scope grants; selecting a unit means that
  single unit (not its descendants). Self-service Person links alone do not grant
  organizational analytics access.
- Reporting is an as-of snapshot, recalculated per request; no client-side caching
  of metrics across accounts or scopes.
- No artificial values, synthetic baseline, inferred overtime or utilization %.

## Endpoint

GET /api/v1/analytics/enterprises/{enterprise_id}/summary?unit_id={optional_uuid}

The response includes as_of (UTC), period_start (UTC date), period_days=30,
renewal_days=30, workforce, work_orders, credentials, workload, trends, holds.

## Exact metric contracts

1. **Work orders by status:** totals of all orders in the allowed unit set,
   irrespective of creation date. Active work means the current status is
   'in_progress'; assigned, open and on_hold are separate.
2. **Daily trend:** 30 UTC calendar dates including today, from 00:00 on
   today minus 29 days to the response timestamp. Created uses created_at;
   completed uses completed_at, and includes 0-count days. It is an event trend,
   not a historical reconstruction of status.
3. **On hold:** work orders currently in on_hold status; up to eight detail rows,
   with critical/urgent priority first. These are current recorded holds, not
   independent live recalculations of eligibility.
4. **Current workforce:** active, non-archived resources with a primary employment
   assignment effective on the current UTC date; their *latest* current assignment
   determines the unit for scope and grouping. Other/secondary team memberships
   do not expand visibility. Reservable_next_15m uses the same server scheduling
   evaluate() as reservation checks over [as_of, as_of + 15 minutes). It checks
   valid shifts, closures, current assignment, absences and reservations; **does
   not check skill/credential eligibility**, physical attendance or safety gates.
   Blocked = active_resources minus reservable; not a reason breakdown.
5. **Credential counts:** count records (not distinct people) for the visible
   current active workforce. Expiring = verified, already valid, with expires_on
   between today's UTC date and today + 30 days inclusive. Expired = verified
   records with expires_on before today; pending = all pending records. Replaced
   or redundant historical records may still count; these metrics are NOT claims
   about whether people are eligible for any particular work order.
6. **Reservation workload:** sum of clipped intervals for active (not cancelled)
   reservations intersecting [00:00 UTC 29 days ago, as_of); include only resources
   currently visible. Units are *current* assignment units, not historical booking
   ownership. Include direct calendar reservations and work-order-linked reservations;
   these are planned reservations, not performed hours.
   resources_with_reservations counts unique resources with positive clipped time.
   Rounding to 0.01 hour applies after summing each resource or unit.
7. **Empty/new enterprises:** metrics are zero, 30 trend days are returned; if
   non-admin users lack any unit grant, the endpoint fails closed.

## Security and caveats

Server-side scope enforcement precedes all domain reads and never assumes the
frontend enterprise/department is authorized. Every domain query filters tenant
and authorized units/persons/resources. No names, hidden IDs, absence reasons,
credential document numbers or crew details are included in aggregates.
Account/enterprise transitions reset the frontend's displayed snapshot.
Authentication cookie and standard GET authorization apply.

First iteration executes the existing evaluate() once per currently visible
resource and reads authorized work orders/credentials into memory. This is
suitable for small pilot datasets; high-cardinality production use should
replace it with batched/SQL aggregation and add performance tests, cache
invalidation and indexing after measured profiling. No background watcher or
permit-to-work decision is introduced.

## Validation gates

- Pytest: role and scope isolation, data accuracy and interval/expiry boundaries.
- Playwright: scope transitions and dashboard loading states.
- Ruff, migrations, frontend type check/build and E2E in GitHub Actions.
- Use synthetic records only. Merge only after user review and successful checks.
