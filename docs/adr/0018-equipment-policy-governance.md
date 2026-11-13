# ADR-0018 — Independently approved, additive equipment policy proposals

Status: PR #22, development/synthetic data only.

## Motivation and safety boundary

Before PR #22, POST /assets/{asset_id}/required-credentials and
/required-skills inserted mandatory policies immediately from one admin. That
bypasses the independent review expected for changes which constrain
maintenance assignment and create application-only safety holds.

PR #22 makes **all new** equipment credential and skill policies pass through
a single pending -> approved/rejected review. Old direct-write endpoints now
return HTTP 409 and do not insert policies. Existing append-only requirements
survive migration unchanged; they remain active and are never backdated into
fabricated "approved" proposals.

## Data model

\`asset_policy_proposals\` has typed, scoped references to asset and either
credential type or Skill+Scale+minimum ScaleLevel; a substantive reason,
author and time; state (pending, approved, rejected); and optional reviewer,
decision time and review note. PostgreSQL composite tenant and scale FKs
enforce referential scope, a strict kind/payload XOR check prevents mixed
policy proposals, and a DB check ensures non-pending proposals have a review
by **a different account** and note. Two partial unique indexes prevent
duplicate pending proposals for an asset+policy key, including concurrent
requests. The application also uses the shared enterprise transaction lock.

Approved/rejected proposals are terminal; no update, delete, reopen or
downgrade API. Rejected proposals remain in history and may be followed
by a new proposal. A newly approved skill or credential is *additional*: it
never replaces an active rule or removes a previously required credential.
No lower threshold can overwrite an existing skill rule.

## API

- POST /api/v1/equipment/assets/{asset_id}/policy-proposals
  (admin + CSRF): validate tenant/skill/scale/type and check active or pending
  duplicates; **no work hold**, no new effective policy during submission.
- GET /api/v1/equipment/assets/{asset_id}/policy-proposals
  (admin-only): latest 100 proposals including decisions, visible to admins.
- POST /api/v1/equipment/assets/{asset_id}/policy-proposals/{id}/approve
  (admin + CSRF): reviewer must differ from proposer, all references are
  revalidated, and an effective typed policy record is added in the **same
  transaction** as state=approved and the audit. Work linked to the asset
  and actively in_progress is moved to audited **HRMS-only on_hold**.
  The response is the updated AssetView.
- POST .../{id}/reject (admin + CSRF): independent reasoned review; existing
  effective policy and in-progress work remain unaffected. It returns the
  terminal proposal.
- POST /required-credentials and /required-skills are retained as *explicitly
  disabled legacy routes* (HTTP 409 after authorization/CSRF), protecting against
  a silent bypass by old web clients.

A fresh approval of a previously submitted proposal can fail closed if the
skill has become inactive, a type is removed, a scale is invalid, or an
equivalent rule is already effective. Errors leave the proposal pending for
independent investigation. A reviewer can't approve and reject a single
proposal, and a single user can't propose then approve it.

## UI and compatibility

Equipment card shows the currently effective append-only requirements
separately from proposals and their human-readable decisions. Admin users
submit requests with reason. Pending rows offer Approve/Reject controls only
to a *different* admin; notes of at least 10 substantive characters are
mandatory. The server remains authoritative even if the UI is bypassed.
The original instant-add buttons are deliberately replaced. API consumers
using the old direct routes must upgrade; this is an intentional breaking
change. There is no automatic privilege grant to managers or viewers.

## Operational boundary and next work

An approved software qualification policy **cannot** verify physical isolation,
machine safety, permit-to-work legality, actual staff ability or machine
stops. Application \`on_hold\` is **not** a PLC/robot interlock. These records
are not signed, immutable storage and not compliance-grade certificates.
Further engineering: signed/versioned full policy documents, multi-approver
roles, evidence retention, organization-specific authorization matrix,
device interoperability and scheduled qualification rechecks.

Acceptance: Alembic upgrade; schema constraints, duplicate guards, role/tenant
and CSRF checks, independent review, stale validation, no premature activation
or on_hold, approval-triggered hold, historic active-policy preservation,
Pytest, TypeScript/Vite and Playwright synthetic acceptance.
