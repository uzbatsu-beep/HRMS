# ADR-0014 — Append-only equipment skills and software-readiness overview

Status: PR #18, development / synthetic data only.

## Reason and boundary

PR #17 introduced append-only equipment-specific credential policies and human
permit-to-work attestations. Machinery also requires **approved equipment-specific
competence levels**. A person's general work-order skill requirements must not
silently satisfy a more demanding equipment policy.

The new AssetSkillRequirement records asset, Skill, immutable Scale version
and a minimum SkillScaleLevel. Tenant/skill/level relationships are enforced
by composite SQL foreign keys. It is intentionally append-only: no update,
delete, or downgrade API. Only the installation admin can add it (CSRF required).
Duplicates, inactive skills, foreign enterprise IDs and incorrect scales are
denied. A new requirement on an in-progress equipment-linked work order triggers
an audited **application** status \`on_hold\`. It never physically stops a machine.

## Server enforcement

\`required_asset_skills\` evaluates each required skill against the most recent
**approved** PersonSkillAssessment, ordered by review time and assessment ID.
A newer lower-level approval overrides an older higher one. Missing, inactive,
mismatched scale and insufficient level fail closed with distinct blocker
codes. Asset skill rules are conjunctive with existing WorkSkillRequirement
and all mandatory activity and equipment credentials. Every crew candidate and
the whole assigned crew are checked again by the unchanged server-side safety
logic on start, revalidate, resume and completion. A new policy requires an
explicit human resumption after the new gate passes.

No safety claim or legal authorization is made by a stored skill assessment,
equipment policy, or HRMS work status.

## Operational readiness API

\`GET /api/v1/equipment/enterprises/{enterprise_id}/readiness?unit_id=...\`
returns **at most 200 currently nonterminal equipment-linked orders**, with
software asset + latest-permit blockers, status and counts. It is **not** a full
crew check; \`crew_eligibility_checked=false\` is explicit. It does not report
personal qualification or issue work authorization. Unit filtering is direct.
A non-admin must have grants on **both** the work unit and asset unit; otherwise
the item is not included. Unauthorized enterprise/unit filters return 404.
An empty admin enterprise returns zeros. The list is current snapshots only,
not an event stream and not a periodic safety inspection.

This read-only overview complements, rather than replaces, existing explicit
\`/work/orders/{id}/safety\` checks and transactional hard gates. It must not
be used as a physical start permission, an emergency stop or LOTO validation.

## What is deferred

Formal competence schemes, equipment-specific site policy versions/rollbacks,
policy publication by independent safety officers, uploads and signatures,
scheduled mandatory verification, safety PLC/robot interlocks, CMMS integration,
retention controls and detailed audit report exports are not implemented here.
The equipment register and monitoring remain synthetic-only until independent
engineering and legal review.

### Acceptance
- PostgreSQL migration from \`0011_equipment_permits\` to \`0012_asset_skill_gates\`.
- RBAC/CSRF/tenant/duplicate/mismatched-scale regression tests.
- Last approved rating, policy addition during execution and hold/resume flow.
- Readiness totals, error cases and scope; Playwright rendering and save path.
- Ruff lint, complete Pytest suite, TypeScript/Vite, Chromium E2E.


### Superseded creation path (PR #22)

The direct admin add routes described above were intentionally disabled by
PR #22 (409); all **new** requirements now use independently approved policy
proposals. Existing active requirements remain effective. For enforced
approval and migration semantics see ADR-0018.
