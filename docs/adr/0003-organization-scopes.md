# ADR-0003 — Configurable organization hierarchy and explicit unit scopes

**Status:** Accepted for PR #5 (initial domain implementation)  
**Date:** 2026-11-12

## Context

TWM must serve internal technical services in potentially different organizational
layouts. Fixed “plant → department → team” depth is inadequate; access to
personnel and other future records must be restricted to explicitly assigned
organizational scopes.

## Decision

- `Enterprise` is the top-level grouping and security boundary.
- `OrganizationUnitType` is a per-enterprise configurable dictionary with stable
  code and display name; types do not define a fixed depth or hardcoded hierarchy.
- `OrganizationUnit` belongs to one enterprise and may reference a parent
  from that same enterprise. A unit can have any depth.
- Each enterprise enforces unique unit codes and type codes.
- PostgreSQL composite foreign keys guarantee that a unit's parent and
  type belong to the same enterprise. Application validation denies cyclic moves.
- Admin changes to the organization hierarchy take an enterprise row lock
  to serialize concurrent tree mutations (SQLite test backend does not emulate
  PostgreSQL locking).
- `UserUnitScope` grants are explicit and default-deny for manager/viewer.
  A grant can include descendants or only its target node.
- An administrator is installation-wide at this stage; manager/viewer access
  is read-only until domain-specific permissions are designed.
- The backend calculates effective allowed unit IDs on each request from the
  current hierarchy and grants, rather than trusting the frontend.
- Hidden parent IDs are masked in scoped read responses.
- Organization mutations and scope assignments/revocations append audit events
  in the same database transaction.
- Admin-only mutations require CSRF validation via the existing session model.
- No delete endpoint for units, types or enterprises is provided in this PR;
  archive/validity lifecycle follows once personnel references exist.

## Initial endpoints

- `GET/POST /api/v1/org/enterprises`
- `GET/POST /api/v1/org/enterprises/{enterprise_id}/types`
- `GET/POST /api/v1/org/enterprises/{enterprise_id}/units`
- `GET /api/v1/org/units/{unit_id}`
- `PATCH /api/v1/org/units/{unit_id}`
- `GET/POST /api/v1/org/scopes`
- `DELETE /api/v1/org/scopes/{scope_id}`
- `GET /api/v1/org/audit` (admin)

## Limitations before production

1. Organization scopes are initially a **read policy for organization entities**
   only. Future personnel/credential/workorder endpoints must explicitly call
   shared access policies; never assume permissions are inherited implicitly.
2. There is no separate site-level or user-permission policy editor yet.
3. Access expansion from a structural move is intentional and audit-logged; an
   enterprise administrator must review grants when moving a subtree.
4. Hierarchy filtering currently loads unit/grant rows for the enterprise into
   memory; scale/latency measurements will determine when recursive database
   queries or materialized paths become necessary.
5. No configurable validity dates, delegated administration, OIDC, audit retention
   policy, or soft-deletion exists yet.
6. Local authentication from PR #4 still lacks login throttling and recovery
   workflows; deployment remains development/test-only.
