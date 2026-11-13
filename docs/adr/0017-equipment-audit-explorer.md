# ADR-0017 — Read-only equipment audit explorer with keyset pagination

Status: PR #21 (synthetic-development preview only).

## Motivation

EquipmentAuditEvent already records significant software actions on asset
registry records, permits and maintenance windows. The legacy admin-only API
returns the newest 100 events as a flat list and includes unstructured
details_json. A useful operational audit screen needs bounded filters, paging
and safer summary fields. It is not proof of physical machine conditions or
a substitute for a legal/compliance-grade records system.

## API

\`GET /api/v1/equipment/enterprises/{enterprise_id}/audit/explorer\`

- **Admin-only**. The given enterprise must exist; no tenant fallback and
  no unscoped event search. Admin scope remains system-wide as in the rest of
  the prototype.
- \`limit\`: 1–50 (default 20), \`action\`: exact event code, \`subject_id\`:
  event subject UUID, \`actor_id\`: user UUID, \`since\` / \`until\`:
  timezone-aware inclusive timestamps; \`cursor\`: opaque keyset token.
- Uses immutable event ordering \`created_at DESC, id DESC\`, including a
  deterministic UUID tie-breaker for same-time records. SQL \`limit + 1\`
  determines \`has_more\` / \`next_cursor\`; no potentially expensive OFFSET.
  A cursor is a validation-checked base64url timestamp/UUID pair; it is not
  a security token, and cannot override filters or RBAC.
- The new \`EquipmentAuditPage.items\` deliberately exposes **metadata only**:
  event id, action, current actor username and id, subject id, and event time.
  It **never returns details_json**, handwritten reasons or evidence/document
  references. The legacy \`/audit\` API is retained for backward compatibility;
  its detail visibility remains restricted to admins, so the new explorer
  reduces exposure for the new UI but does not globally remove legacy access.
- Pagination is point-in-time, not a signed or snapshot-isolated export.
  New events may appear before the first page, and a user can refresh to
  include them. Audit history itself is application-level, not tamper-proof.

## Frontend

Admin-only Equipment module includes a compact audit explorer with filters
for event category, subject/actor UUID, local-time window, refresh and
previous/next page. The UI renders human-friendly event labels, timestamp,
current username and IDs. \`subject_id\` identifies the event's source record:
on downtime/permit actions it is the window or permit ID, **not necessarily**
the EquipmentAsset ID. Explicitly do not promise a universal asset filter.
A selection change resets history state and scope. Bulk audit scans are never
issued by manager/viewer clients.

## Boundaries and acceptance

No database migration, scheduled monitor, retention policy, digital signature,
work authorization, physical plant intervention, machine evidence or certified
compliance claim. The underlying event table and audit writes are unchanged.

Acceptance: full PostgreSQL migration suite, Ruff, Python regression for
paging/same-timestamp tie-breaks, tenant/role protections, bounds and malformed
cursor handling; TypeScript/Vite; Playwright UI with >20 records, navigation,
filters and manager/viewer denial. Only synthetic data is permitted.
