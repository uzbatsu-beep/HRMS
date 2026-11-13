# ADR-0013 — Equipment-linked work permits and enforced software gates

Status: PR #17, development/synthetic-only.

## Scope
EquipmentAsset registry is tenant+unit scoped, with code, kind, optional serial,
and active/out_of_service state. Admin creates and changes state; manager/viewer
read their granted units only. Append-only AssetCredentialRequirement associates
existing independently verified credential types with a machine. Every
requirement applies to **each** assigned crew member on **every** relevant
calendar boundary and is AND-ed with immutable activity-level requirements.
There is no path to weaken or delete a requirement in this PR.

A WorkOrder may be linked exactly once to one asset while **open and unstaffed**.
Manager must be permitted to see both job unit and asset unit. No re-linking,
cross-tenant link or post-assignment link is possible. All legacy unlinked
orders continue to use their preexisting gates; this is essential for
backward compatibility but **not** a claim that they are safe to perform on
equipment. Operators must link all machinery-targeted work before assignment.

## Permit record
WorkPermit has immutable version number; vN+1 may be prepared only after
explicitly revoking vN. Status workflow: draft -> submitted -> approved,
and revoke from any non-revoked state. The approved permit must be the latest.
A draft includes three operator/human attestation flags (hazards reviewed,
energy isolation asserted, area access asserted) and a bounded documentary
reference. Submission fails unless all three assertions are true and a
reference is present. These are **unverified human statements**.

Approval is administrator-only and cannot be performed by the preparer.
No API supports self-approval. A pending/expired/cancelled/revoked latest
permit blocks work. Revocation during an in-progress job immediately changes
the software status to on_hold. Resumption requires fresh approved vN+1
and all crew/credentials/calendar checks to pass.

The asset may be marked out of service by admin with a substantive reason.
Affected in-progress jobs enter on_hold in the same enterprise transaction.
Adding an equipment credential requirement similarly places affected
in-progress jobs on hold. Returning asset to active **never** automatically
resumes work; fresh eligibility and explicit human resumption are required.

## Server enforcement
A linked WorkOrder is denied at start, resume, completion and revalidate when
asset is missing/out_of_service, latest permit isn't approved or attestation
is incomplete. The same centralized team_safety_check adds equipment blockers
and still checks every member's previous mandatory skills, activity
credentials, work calendar and reservation. Prior UI eligibility results
have no authority; actual writes lock the enterprise row and re-evaluate.

All changes and human decisions are recorded in equipment audit events,
with nonempty reasons and document references. The system does not store
signed scans or validate external evidence; an evidence reference is a
traceability identifier, NOT evidence authenticity. Completed/cancelled
jobs cannot receive a new or revoked permit.

RBAC: employee/manager/viewer cannot approve or edit asset policy.
Manager with explicit unit grants can link and prepare/submit permits for
in-scope jobs. Admin can approve someone else's submitted permit. Scope
applies to GET and POST at backend; CSRF enforced for mutations. A manager
with work-scope but no equipment-scope must not see the linked asset details.
The audit endpoint is admin-only.

## Limitations
- No machine/PLC/robot safety interlocks, certified safety functions, LOTO
  verification, legal/regulatory permit-to-work, physical inspection evidence,
  permit expiration beyond the immutable WorkOrder window, ongoing event-loop
  monitoring or configurable legal safety checks.
- Equipment-specific *skills* and external asset EAM/CMMS synchronization
  are deferred; currently asset policy covers verified credential types.
- The three attestation categories are pilot workflow fields, NOT
  applicable legal or site-specific work rules. Engineers must validate
  the site permit and lockout regime outside this prototype.
- UI and tests contain only synthetic data.

Accept only with PostgreSQL Alembic migration, Pytest authorization and
state-gate tests, Playwright E2E, Ruff and frontend build all passing.
