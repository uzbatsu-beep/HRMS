# ADR-0006 — Credential records, independent verification and deny-by-default work gates

**Status:** Accepted for PR #8, development implementation  
**Date:** 2026-11-13  
**Depends on:** ADR-0002 Identity, ADR-0003 Organization, ADR-0004 Personnel,
ADR-0005 Competence

## Problem

A verified technical skill is not an electrical-safety permit, industrial
safety certificate or legal qualification. Workforce matching and assignment
must never infer authorization from `PersonSkillAssessment` alone.

TWM needs a structured credential register and a reusable, explicit
**deny-by-default requirement check**. Credential validity depends on identity,
document type, independently verified record, dates, revocation and the
exact kind of activity.

## Decision

### Data model

- `CredentialType` is an enterprise-specific immutable definition identified
  by unique code and category: `permit`, `certificate`, `qualification`,
  `training`. It has `is_safety_critical` and `requires_expiry`.
- A safety-critical type **must** require a non-null expiration date. This
  invariant is checked by Pydantic, application code and PostgreSQL type check.
- `PersonCredential` captures employee, type, document reference, issuer,
  issue/start/expiry dates, terminal review states, reviewer and revocation
  metadata. Every renewal is a **new record** rather than overwriting history.
- Credential states: `pending → verified/rejected`; a verified record can
  be `revoked`. Rejected/revoked states cannot be silently reapproved.
- `CredentialRequirement` is a mandatory (all-of) requirement mapping a
  stable enterprise-local `activity_code` to a credential type.
- Requirements are **append-only in the first API version**, with no delete
  or waive endpoint. Changes to a safety policy require a later governed
  versioned configuration workflow.
- `CredentialAuditEvent` logs catalog additions, requirements, submissions,
  review decisions and revocations. Changes and their audit event are written
  in one database transaction.
- Composite foreign keys prevent cross-enterprise types and employee records.
- No actual binary document or scanned certificate is stored in this PR;
  the reference, issuer and dates are **user-entered metadata**.

### Review policy

- Only an administrator can create document records and requirements.
- A **different authenticated** admin or an in-scope manager may review a
  `pending` record. A submitter is not allowed to review their own submission.
- A user whose UserAccount is linked to the Person (ADR-0005) may **not approve
  their own** credential, even when they are an administrator.
- The reviewer records a non-empty justification (at least 10 characters).
  Approval requires a valid issue/reference record and must not approve a
  document already expired as of the current server date.
- Review state transitions take an enterprise-row lock and row refresh with
  `SELECT ... FOR UPDATE`. A subsequent decision cannot overwrite a prior one.
- An admin can revoke only a verified record, with a required reason.
  Repeated revocation, approval of a rejected record and approval of a
  revoked record are rejected.
- Review status records that a user marked the document as verified. It does
  **not** prove cryptographic authenticity, legal validity, regulator approval
  or physical inspection. Those controls require later integrations/procedures.

### Eligibility check

`evaluate_activity(db, person, activity_code, on)` is a backend-only
function reusable by future matching and work-management modules.

A person is eligible to pass this **credential-policy check** only when:

1. The Person and WorkforceResource are active and have a primary
   EmploymentAssignment covering the requested date.
2. At least one mandatory requirement exists for the activity in the
   Person's enterprise. **An unconfigured activity fails closed**.
3. For every required CredentialType there exists a PersonCredential:
   - belonging to the correct person, type and enterprise;
   - with `status=verified`, not revoked;
   - issued and valid no later than the requested date;
   - not past its expiration date (inclusive end date);
   - with a non-null expiration for types that require it.

A missing, pending, rejected, revoked, expired or not-yet-effective record
never satisfies a requirement. All required credentials are combined with
logical **AND**, never 'any one of these'. Results include explicit blockers
(e.g. `NO_POLICY`, `MISSING_CREDENTIAL`, `UNVERIFIED_CREDENTIAL`,
`EXPIRED_CREDENTIAL`, `REVOKED_CREDENTIAL`).

**Important scope boundary:** PR #8 exposes a diagnostic eligibility endpoint.
It does **not** yet contain a WorkOrder or staff-assignment API. The future
work-assignment code MUST invoke this predicate inside the same
authorization/assignment transaction and reject work on a negative result.
A green diagnostic response is not a legal work permit or safety guarantee.

### Authorization

- Admin manages type definitions, requirements, record submission, review and
  revocation, and may view all employees within the installation.
- A manager can view/review only Person records whose **current primary**
  assignment is inside an explicitly granted organizational scope.
- Viewer can view authorized person records but cannot review or change them.
- An authenticated user linked to a non-archived Person may read **their own**
  records even without visibility into other departments.
- Out-of-scope Person endpoints return 404, avoiding direct object enumeration.
- All authenticated mutations require PR #4 CSRF protection.
- Work eligibility is computed from authoritative database state, not caller
  provided document/status flags. It is never authorized on the frontend.

## Endpoints

- `GET/POST /api/v1/credentials/enterprises/{id}/types`
- `GET/POST /api/v1/credentials/enterprises/{id}/requirements`
- `GET /api/v1/credentials/persons/{person_id}`
- `POST /api/v1/credentials/enterprises/{id}/records`
- `POST /api/v1/credentials/records/{id}/review`
- `POST /api/v1/credentials/records/{id}/revoke`
- `GET /api/v1/credentials/persons/{person_id}/eligibility/{activity_code}?on=YYYY-MM-DD`
- `GET /api/v1/credentials/audit` (admin only)

## Deferred safety work before production

1. Physical/remote evidence verification and authentic document storage,
   anti-malware checks, jurisdiction-specific legal applicability and certificate
   issuer validation.
2. **Versioned activity policies with four-eyes publication**, effective date
   intervals, change impact analysis and no administrative bypass.
3. Required training/permit level, specific equipment/machine authorization,
   regulatory jurisdiction, activity location and employer scope.
4. WorkOrder-level mandatory check in a transaction and continuous re-check
   before start; cancellation/escalation for expired or revoked permits.
5. Expiry warnings, renewal planning, alerts and dashboards.
6. Production-grade SSO, MFA, login throttling, personal-data access policy,
   immutable audit storage and retention.
7. Database-side protection against out-of-band writes bypassing the API; do
   not treat this first development implementation as a compliance-certified
   safety system.

**Current build is for synthetic development/test data only.**
