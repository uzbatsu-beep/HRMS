# ADR-0020 — Exact-unit permission matrix for equipment policy operations

Status: PR #24 / synthetic development, not a complete platform RBAC replacement.

## Motivation

PR #22/#23 used two global admin accounts for independent policy approval.
A maintenance engineer and a safety reviewer should instead be capable of
proposing and reviewing **within their granted organizational unit** without
receiving user-management, asset-state, permit or enterprise-wide rights.

## Permissions and two-factor authorization

Three enumerated operation permissions are introduced:

| Permission | Enables |
|---|---|
| equipment.policy.read | Read policy proposals and immutable skill revision history |
| equipment.policy.propose | Read + submit policy/skill increase proposal |
| equipment.policy.review | Read + independently approve/reject a proposal |

These are **operation grants, not login roles**. Existing Admin/Manager/Viewer
account roles remain unchanged. Admin retains legacy global permissions.
For a non-admin, access requires BOTH:
1. Its current active organizational scope includes the asset's unit via the
   already deployed \`allowed_unit_ids\` resolution; and
2. \`UserUnitPermission\` has an exact \`unit_id\` match and the required
   operation code. Permission grants never inherit to descendants, even when
   a normal organization scope does. Missing account, asset or unit scope
   yields 404; visible asset without permission yields 403.

The server evaluates current grants **on every request**; revoked grants
take effect for authenticated users without requiring them to log out.
Even a user with both propose and review cannot approve their OWN proposal.
The independent-review constraint remains in both Python and the database.
No privileges are implied by "Manager" or "Viewer" role alone.

## Grant management

An admin-only exact-unit matrix supports:
- \`GET /api/v1/org/permissions?unit_id=&user_id=\` (bounded administrative view)
- \`POST /api/v1/org/permissions\` with account, unit and code (CSRF required)
- \`DELETE /api/v1/org/permissions/{id}\` (CSRF required)
- \`GET /api/v1/equipment/assets/{id}/policy-capabilities\` for any
  organization-scoped authenticated viewer, returning only own can_read,
  can_propose and can_review booleans.

Grants are auditable using OrganizationAuditEvent permission.granted and
permission.revoked, with actor, unit and code. The database enforces a
limited allowed-code set, unique user+unit+code, and user/unit foreign keys.
Only active non-admin users can be granted. Duplicate grant => 409.
Admin UI also offers a deliberate *separate* exact organizational unit
scope grant; granting an operation alone does NOT create unit visibility.

## Workflows and UI

Policy reads, skill revision history, proposal submission and approve/reject
all use this fine-grained authorization. **Other routes are unchanged:**
asset creation/state change, maintenance scheduling, credential/skill
catalog edits, work permits, personnel, credentials and org management
remain under their previous role/scope checks.

The Equipment module still uses the existing organization-scoped read APIs
for credential types, skills and scales. The policy panel now asks the
server for own capabilities and dynamically shows read-only, proposer or
reviewer controls. The administrator sees a per-unit matrix for granting
rights. The frontend is advisory: server and DB remain authoritative.

## Security boundaries and remaining roadmap

This is a deliberately narrow RBAC vertical slice. Do not treat it as a
generic customizable role-definition engine. Later work: governed role
templates/job functions, explicit deny/revocation of individual roles,
row-level enterprise policy definitions, credential attestation roles,
policy expiry, and formal separation-of-duties rules.

Grant decisions are application authorization, not certified safety
hardware. No machine stop, PLC/robot interlock, legal permit-to-work or
LOTO confirmation is performed. Use synthetic data only.

Acceptance: Alembic 0016, API grant/list/revoke duplicate and CSRF, no
scope -> 404, scope alone -> 403, delegated maker/checker, independent
review, immediate revoke, unit isolation, unchanged legacy admin gates,
Ruff, full Pytest and Playwright synthetic browser workflow.
