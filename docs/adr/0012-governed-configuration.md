# ADR-0012 — Governed configuration for non-safety personnel attributes

Status: proposed, PR #16. Backend is source of truth. Development and
synthetic data only.

## Domain boundary

The first Configurator vertical slice manages **informational** Person
custom fields only. Supported field kinds: text (1–400 characters), integer
(with optional -1e6..1e6 range), boolean, and controlled choice (2–30
distinct entries). At most 24 named fields per version. Strict schema code
patterns, reserved safety/identity field names and payload validation apply.
No user-provided Python, SQL, JavaScript, executable expressions, event hooks
or custom lifecycle rules are accepted. Choice options are the first governed
dictionary type; they are distinct from credential and job activity catalogs.

The existing relational core remains authoritative: enterprise, Person,
WorkforceResource, employment assignment, verification, role, safety status,
work order lifecycle and permit requirements CANNOT be configured here.
No implicit permit, qualification or staff-eligibility decisions derive from
informational custom fields. Rule changes affecting safety remain out of scope.

## State machine and dual control

- POST /api/v1/configuration/enterprises/{enterprise_id}/versions -> draft.
- PUT /api/v1/configuration/versions/{id} -> edit only while draft.
- POST /versions/{id}/validate -> validated (the schema is checked before
  draft creation/edit and rechecked on validation).
- POST /versions/{id}/approve -> approved, **must be a different administrator
  than the version creator**.
- POST /versions/{id}/publish {effective_on: YYYY-MM-DD} -> published;
  requires prior independent approval, forbids backdating and duplicate
  published effective dates for the same enterprise. Published versions are
  immutable. A new version is created from the existing effective definition.
- GET /enterprises/{id}/active -> most recent published version with
  effective_on <= current UTC date; a future-dated version remains invisible
  to data-entry until effective date. Historical versions remain readable
  to administrators via GET /enterprises/{id}/versions.
- All mutations require current admin session and CSRF. Enterprise row
  locks serialize create/edit/approve/publish and personnel attribute writes.
  Integrity violations return 409; rejected workflow transitions return 409.

An enterprise with only one admin can draft and validate but cannot approve;
the independent review gate is intentionally hard. Never bypass by publishing
directly or using a manager role.

## Person values and visibility

GET /api/v1/configuration/persons/{person_id}/fields returns the effective
configuration and latest value snapshot, filtered to field keys and values
still valid in the current published schema. It enforces the existing
server-side Personnel visibility, so arbitrary tenant/department lookups
return 404. No draft attributes or versioned schema can leak through it.

PUT to the same path is admin-only with CSRF. It validates each submitted
value (including required, type, integer bounds and choice membership);
unknown keys are rejected, not silently kept. Old values can remain
in historical revisions, but are not shown once their definitions are removed
or made invalid. A successful write creates an immutable
PersonFieldRevision row, instead of overwriting previous values.

ConfigurationAudit stores action, subject, version and changed field keys,
**never the personnel field contents**, to limit audit exposure. The UI shows
fields on the existing Person details pane; it does not persist UUIDs,
person data or config payloads in localStorage.

## Data and compatibility

Migration 0010_configuration adds config_versions, person_field_revisions and
configuration_audit, with composite tenant foreign keys and JSONB snapshots
for configuration/attribute documents. JSONB is NOT used as a replacement for
core relational domain models. This is additive and does not change any
existing safety/authorization/assignment API.

When a newly published schema changes a field type or controlled vocabulary,
previous snapshots remain in the database; incompatible values are hidden
from the current view and require explicit new values on next edit. This is
intentional: publication never reinterprets past evidence. Only current
UTC date is used for effective configuration.

## Deferred / not delivered

- Configurable transitions for WorkOrder lifecycle; any future changes must
  preserve immutable hard safety gates, independent safety engineering review,
  and a restricted declarative state machine.
- Credential requirements, legal permits, training validity, user roles and
  organization scopes are NOT editable through Configurator.
- Custom fields for WorkOrder/Asset and import/export/field-level security.
- Automatic retroactive field migrations, retention policy, encryption and
  production personal-data safeguards.
- Large-scale load tests and dual-admin UI impersonation workflows.

Review gates: clean PostgreSQL migrations, Pytest workflow/security/scope
regressions, Playwright smoke and role checks, Ruff, TypeScript/build.
