# ADR-0005 — Versioned competence catalog and evidence-backed review

**Status:** Accepted for PR #7 (development stage)  
**Date:** 2026-11-12  
**Depends on:** ADR-0002 Identity, ADR-0003 Organization Scope, ADR-0004 Personnel

## Problem

TWM needs configurable skills and competence levels suitable for different
technical services (PLC programming, electrical safety, robotics, mechanics,
hydraulics, maintenance, diagnostics, etc.). Self-reported capability is not
the same as manager-confirmed competence. Ratings must be explainable, preserved
over time and safe to use later in a workforce matching engine.

## Decisions

### Skill taxonomy

- Each `SkillCategory` belongs to one Enterprise, has a code, name and optional
  parent category; hierarchy depth is unrestricted. Categories are created, not
  rearranged, in this first slice.
- Each `Skill` has one immutable scale-version reference, category and code.
  Skills may be archived (not hard-deleted); historical assessments remain.
- Enterprise-specific codes are unique. Composite PostgreSQL foreign keys
  prevent foreign categories and scales from another enterprise.

### Versioned grading scales

- `SkillScale` is a **published version** identified by enterprise, stable code
  and version integer. Each version has 2–10 uniquely ordered `SkillScaleLevel`
  rows (ordinal, label, optional description).
- A scale and its levels are created **atomically**. No edit/delete endpoint is
  exposed for a published scale. To change wording or ordinal semantics, publish
  another version with the same code and a different version number.
- A skill continues to reference its original scale; changing to a new scale
  version is **not** an implicit conversion.
- Never compare raw ordinals from different scale versions or scales.
  Application validation **and composite foreign keys** ensure every submitted
  level belongs to the skill's actual scale.

### Identity and submission

- UserAccount remains separate from Person (see ADR-0004).
- `UserPersonLink` is created only by an admin and establishes the identity
  entitled to submit a **self-assessment** for exactly one Person. Each Person may
  have at most one linked account in this initial implementation.
- Self-assessment is allowed only for the linked, non-archived Person with active
  WorkforceResource. This self-service path does not grant access to any other
  Person, enterprise or department.
- An admin or in-scope manager can submit an **expert proposal** for an active
  Person. It is still `pending` until reviewed by a different authorized user.
- Every assessment is an append-only record with immutable submitted level,
  scale version, submitter, source and evidence metadata. New proposals do not
  overwrite prior approvals.

### Evidence and review

- `SkillEvidence` stores 0–8 pieces of **metadata**, consisting of type,
  description and optional reference. Types: observation, training, document, other.
- **Approval requires at least one evidence record** and a textual justification.
  Evidence metadata is *not* proof of validity on its own; the reviewer must check
  the underlying facts/document in the enterprise workflow before approving.
- Reviewer must be **admin or in-scope manager**, distinct from the submitter,
  and must not be linked to the assessed Person. A reviewer cannot approve
  their own competence.
- Review is terminal: `pending → approved` or `pending → rejected`; repeat
  approval/rejection returns conflict, preventing silent history rewrites.
- State transitions use a transaction and `SELECT ... FOR UPDATE`.
  Audit events record actor and decision.
- A skill archived before review cannot gain new approval. Old records remain.

### Matrix semantics

- Matrix contains **only approved assessments** for currently active skills and
  non-archived Persons.
- For a Person+Skill, display the most recently *reviewed* approved assessment.
  Later pending/rejected proposals cannot silently supersede an approval.
- Non-admin readers see only employees whose **current primary assignment**
  is in their granted organizational subtree, plus their own linked Person.
  The query filters at SQL level *before* limiting results.
- Matrix output includes skill, level label and ordinal, Person and confirmation
  timestamp; it is not a legal certification, safety permit or training license.
- In this initial release, the API retrieves at most 1,000 approved assessment
  records and returns at most 200 last-approved Person+Skill pairs per request.
  Keyset pagination is needed before large enterprise adoption.

### Access control

| Action | Admin | Manager with scope | Viewer with scope | Linked self |
|---|---|---|---|---|
| Read catalog | Yes | Yes | Yes | Own enterprise only |
| Add category, scale, skill | Yes | No | No | No |
| Link UserAccount to Person | Yes | No | No | No |
| Submit expert proposal | Yes | Yes | No | No |
| Submit self-assessment | If linked | If linked | If linked | Yes |
| Review pending proposal | Yes, independent | Yes, independent | No | No |
| Read assessment history | Yes | In scope | Approved only | Own full history |
| Read verified matrix | Yes | In scope | In scope | Own records |
| Archive skill | Yes | No | No | No |

All mutations require authenticated cookie session and the CSRF token
introduced in PR #4. No scope is inferred from UI state or selected enterprise.

## API endpoints

- `GET/POST /api/v1/competence/enterprises/{id}/categories`
- `GET/POST /api/v1/competence/enterprises/{id}/scales`
- `GET/POST /api/v1/competence/enterprises/{id}/skills`
- `POST /api/v1/competence/skills/{id}/archive`
- `GET/POST /api/v1/competence/links` (admin)
- `GET /api/v1/competence/me/link` (own person/enterprise)
- `GET /api/v1/competence/persons/{id}/assessments`
- `POST /api/v1/competence/persons/{id}/self-assessments`
- `POST /api/v1/competence/persons/{id}/expert-assessments`
- `POST /api/v1/competence/assessments/{id}/review`
- `GET /api/v1/competence/enterprises/{id}/matrix`
- `GET /api/v1/competence/audit` (admin)

## Limitations and required follow-up

1. Evidence documents/attachments are not stored yet. A reference or user-entered
   narrative is not verification of a certificate. Implement secured document
   storage, malware checks, retention and independent document verification.
2. This is **not** a legal permit/credential module; explicit Credentials safety
   gates follow in a separate PR. Matching Engine may later use approved skills
   but MUST independently enforce valid permits.
3. No delegated catalog administration or enterprise-specific field-level privacy
   policy, revision of accepted reviews or appeal workflow.
4. No automatic recertification or expiration of skill assessments. The review
   timestamp is available; validity policy must be configured in later releases.
5. Skill scale version migration, category reparenting and granular catalogue
   configuration version deployment remain future changes.
6. Identity management has no login throttling, SSO, or production-grade
   retention policies yet. **Use synthetic data only; not production ready.**
