# ADR-0021 — Independent per-unit competence and credential review (PR #25)

Status: Draft; synthetic data only. Extends ADR-0020 / PR #24.

## Decision and migration

Two new exact-unit permission codes extend the existing UserUnitPermission
matrix (no new roles, no new grants by default):
- competence.assessment.review — approve/reject pending evidence-based assessments.
- credentials.record.review — verify/reject pending personnel credentials.

Migration 0017_personnel_review_grants updates the enumerated CHECK
constraint in PostgreSQL. Historical equipment-specific grants are retained.
Downgrade fails if any new grant remains, rather than silently deleting it.

The existing administrator can assign/revoke these operations in the
**Organization** module's per-unit permissions matrix. All permission writes
remain admin-only with CSRF and organization audit. Existing account roles
Admin, Manager and Viewer are not altered.

## Authorization

For a non-manager Reviewer:
1. Login must be active.
2. Person must be active and visible through normal organizational scope.
3. The Person's **current primary EmploymentAssignment** must resolve to the
   exact unit covered by the operation grant. Descendant visibility alone
   does not create a descendant operation grant.
4. The operation grant must match its explicit code; assessment review
   cannot verify a certificate, and vice versa.
5. The reviewer must be independent of the assessment/document submitter,
   and must not review their own linked Person.

Existing admins and managers retain their previous review ability,
subject to their established Person visibility rules and separation of
duties. This compatibility decision does not create a deny privilege or
convert the role system into dynamic RBAC.

## API and frontend

The existing review endpoints use the new grants as an alternative to
manager/admin role checks, without altering evidence, status, expiry and
self-review gates:
- POST /api/v1/competence/assessments/{id}/review
- POST /api/v1/credentials/records/{id}/review

Authenticated /api/v1/personnel/persons/{id}/review-capabilities returns
only the caller's own competence_review and credential_review booleans
for an existing and ordinarily visible active Person; it does not expose
the permission matrix or other accounts. The response returns both false
when the caller is linked to the Person as their own profile.

The competence list endpoint shows pending assessments to a granted
reviewer; regular Viewer still receives approved-only external records.
The competence and credential panels use the server-derived capabilities
to show independent approval/rejection actions. A grant for reviewing does
**not** enable creation of expert assessments or credential records.

Credential revocation, Person changes, catalog edits, organization grants,
policy generation, work starts, asset interlocks and all other routes remain
subject to the existing stronger role and safety checks.

## Safety and next steps

A recorded assessment or checked credential is administrative evidence,
not proof of occupational safety, legal PTW/LOTO, electrical isolation or
a PLC/robot interlock. Existing validity and evidence checks stay
mandatory and cannot be bypassed by granting review permission. All CI
tests and sample data are synthetic.

Future incremental RBAC work: WorkOrder planning/dispatch/cancellation
operations, role templates/job functions, grant expiration and versioning,
formal person-level reviewer qualification and evidence integrity.

Acceptance: migration, grant revoke/duplicate and org audit via PR #24,
credential and competence independent review, expired/invalid/self records
still rejected, cross-unit isolation, personnel transfer, capability
response and browser reviewer workflow. Full pytest, Ruff, TypeScript/Vite,
PostgreSQL migrations, and Playwright.
