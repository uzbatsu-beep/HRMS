# ADR-0004 — Personnel, assignable workforce resources and temporal assignments

- **Status:** Accepted for PR #6 implementation
- **Date:** 2026-11-12
- **Depends on:** ADR-0001 (modular monolith), ADR-0002 (identity), ADR-0003 (organization scopes)

## Context

TWM manages people and the enterprise's assignable technical workforce. A human identity is
not interchangeable with an operational labor resource. A specialist can change departments,
work under different role titles and participate in additional teams, while the historical
assignment records must remain available.

Organization visibility is already restricted by explicit grants. Personnel is the first
domain to **enforce those grants on its own API**, rather than relying on frontend filtering.

## Decisions

### Canonical data model

- `Person`: enterprise, unique normalized employee code, first/last/middle name, archival
  timestamp, created/updated timestamps. No date of birth, addresses, payroll or identity
  document details in the initial version.
- `WorkforceResource`: independent UUID, 1:1 with a Person in this initial implementation,
  resource kind and active flag. Further resource types and contractors require their own
  specific workflows; this is not a general vendor/personnel registry.
- `EmploymentAssignment`: one **primary** unit and optional free-text position title for an
  inclusive effective_from/effective_to period. Data preserves every prior assignment.
- `TeamMembership`: additional unit affiliation for a dated interval, independent of
  the person's primary assignment.
- `PersonnelAuditEvent`: append-only event on profile creation/update/archive and
  department or team changes, with actor and change details.

Composite foreign keys enforce enterprise consistency at DB level:
resource → person, assignment → resource, assignment → unit, team → resource and unit.

### Server-enforced access

- Admin can create/edit/archive people and manage assignments globally.
- Manager and Viewer can **read only**; their effective scope is computed by
  `allowed_unit_ids` (ADR-0003) on every request.
- A non-admin may see a Person only if that Person has a current, dated **primary**
  assignment in an explicitly allowed unit, the resource is active, and the Person is
  not archived. No assignments means no visibility.
- Additional TeamMembership **does not grant read access to a person's profile**.
  Granting access through secondary teams would expand exposure of personal information
  and requires an explicit later product decision.
- Individual detail endpoints return 404 (not 403) when the Person does not exist or is
  outside the user's allowed scope.
- In profile history, non-admins see only assignment and team records whose unit IDs
  are within their present allowed organizational scope. Hidden past departments are not
  enumerated or exposed.
- List endpoints filter at the DB level *before pagination* using a correlated current
  assignment selection; they do not fetch all people and merely hide rows in React.

### Temporal integrity

- Date intervals are **inclusive**, stored as native SQL DATE values; timestamps for
  audit/archiving are timezone-aware UTC.
- The application refuses overlapping **primary** assignment ranges for the same resource.
- Team membership intervals must not overlap another membership in the **same unit**.
- A transfer is atomic: lock enterprise, close the currently effective primary assignment
  on the day before the new effective date, create its replacement, verify it does not
  overlap another scheduled period, and audit the change.
- The transfer effective date must be after the prior assignment began. To start an
  assignment from an empty schedule, use the initial assignment endpoint.
- For concurrency control on PostgreSQL, assignment mutations take a
  `SELECT ... FOR UPDATE` lock on the enterprise. SQLite tests do not reproduce
  concurrent PostgreSQL lock behavior.
- A resource with no current assignment can still exist, but is invisible to non-admins.

### Archiving and history

- Archiving sets Person.archived_at and marks its WorkforceResource inactive.
- Past assignments, team memberships and audit events are **not deleted or rewritten**.
- Archived persons are excluded from normal roster queries and all non-admin reads.
- Admin can explicitly request archived people in the roster. Destructive delete is not
  implemented.

## Initial REST API

- `GET/POST /api/v1/personnel/enterprises/{enterprise_id}/persons`
- `GET/PATCH /api/v1/personnel/persons/{person_id}`
- `POST /api/v1/personnel/persons/{person_id}/archive`
- `POST /api/v1/personnel/resources/{resource_id}/assignments`
- `POST /api/v1/personnel/resources/{resource_id}/transfer`
- `POST /api/v1/personnel/resources/{resource_id}/teams`
- `PATCH /api/v1/personnel/teams/{membership_id}/close`
- `GET /api/v1/personnel/audit` (admin only)

All writes require an authenticated admin session and a valid CSRF header.

## Follow-ups and limits

1. A dedicated Position/JobTitle catalogue with effective dates is deferred. PR #6 stores
   position_title as free text for early implementation only.
2. Granular field-level PII permissions, masking, privacy retention and employee consent
   rules are not yet present. **Do not load real personal data into the development build.**
3. Qualification, credential, competence and work-order domains are not connected yet.
4. Preventing overlap uses application checks serialized by enterprise lock, rather than
   a PostgreSQL EXCLUDE constraint. Direct DB writers must not bypass the API.
5. No bulk imports, exports, photo uploads, search indexing or multi-resource-per-person yet.
6. Roster is paginated and currently limits one request to 100 rows; comprehensive search
   and server-side count/ordering are future tasks.
7. Organization scope rights do not delegate mutation: managers can view scoped people,
   but only administrators can change personnel at this stage.
8. Foundation authentication still needs rate limiting, password recovery, audit retention
   and OIDC integration before any production deployment.
