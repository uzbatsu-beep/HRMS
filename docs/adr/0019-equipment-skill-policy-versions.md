# ADR-0019 — Monotonic equipment skill policy revisions (PR #23)

Status: development / synthetic-only. Builds on ADR-0018 / PR #22.

## Decision

An existing, already independently approved equipment skill policy's
**minimum level may only be raised**, not silently rewritten, downgraded,
deleted or replaced. Each upgrade is submitted through the same independent
admin review as a new mandatory policy. Approval is atomic and activates
the new threshold for all assigned/candidate staff.

The original \`asset_skill_requirements\` record remains immutable as
baseline **v1**. The new \`asset_skill_policy_revisions\` table contains
append-only versions **v2+** with reference to baseline, minimum level,
approver/time and an approved proposal. It does not duplicate the baseline
row, avoiding any fabricated historical decisions for migrated data.
Multiple independently approved upgrades form v1 -> v2 -> v3 and beyond.

## API / lifecycle

- \`POST /api/v1/equipment/assets/{id}/policy-proposals\` with kind
  \`skill_upgrade\`, skill_id, min_level_id, expected_version and reason.
  Requires admin + CSRF, existing active skill baseline, same enterprise
  and scale, active Skill and *strictly higher ordinal*. A stale expected
  version returns 409 and a same/lower threshold returns 422.
- \`GET .../policy-proposals\` retains history including the requested
  previous version; the partial unique pending skill index also covers
  upgrades so that parallel approval requests cannot compete.
- \`POST .../approve\` **rechecks** threshold, version and active skill.
  Requires a *different* administrator and substantive review note. On
  success creates a new immutable revision (version + 1), marks proposal
  approved and writes equipment audit events **in one transaction**.
  Linked in_progress work moves to audited **application-only on_hold**.
  Approval never physically disables an industrial machine.
- \`POST .../reject\` is unchanged: terminal independent rejection leaves
  current effective threshold and work lifecycle untouched.
- \`GET /api/v1/equipment/assets/{id}/skill-policy-revisions\` returns
  admin-scoped, ordered v1 baseline plus approved later versions, with
  threshold level, actor/time and proposal provenance. Baseline proposal_id
  is null because old requirements may predate PR #22. Endpoint currently
  limits 200 active requirements and 100 revisions per requirement; it is
  an operator preview rather than a complete archival export.
- The normal asset DTO now returns \`min_level_id\`, \`min_ordinal\`, and
  \`version\` of the **latest approved** threshold. Work candidate matching,
  crew safety checks and start/resume/revalidate/complete share exactly
  this effective threshold through \`service.effective_skill_threshold\`.

## Data integrity

Migration \`0015_asset_skill_policy_versions\` adds enterprise-scoped
uniqueness on baseline IDs, new proposal expected_version and an expanded
check permitting only well-formed skill_upgrade, and immutable revision
records. Composite tenant FKs and scale-level FKs prevent cross-tenant and
mismatched scale references. Unique (requirement_id, version) and
(proposal_id) enforce one revision per reviewed policy decision.

The enterprise transaction lock serializes approvals. The server rechecks
expected_version at **submission AND approval**. An already approved
revision is never edited. Downgrades/migrations to older versions are not
supported as normal operations; a downgrade of this schema would lose the
newer enforceable thresholds and is **not safe on production data**.

## Compatibility and safety boundaries

Existing competency v1 requirements remain active without backfill.
The previous pending-add/approve API remains compatible for kinds skill
and credential; the new upgrade kind is additive. Requiring a second
reviewer and forbidding previously tolerated direct-write routes remains
the intentional breaking change introduced in PR #22.

This is **not** a safety PLC, machine interlock, physical isolation proof,
workplace inspection or legal permit-to-work. An HRMS on_hold does not stop
robots, presses or energized equipment. Use only synthetic data.

Acceptance: base v1 preserved, independent v2/v3, no downgrade, stale
version/duplicate rejection, scoped RBAC/CSRF, pending/rejected no change,
approval triggered hold, updated crew matching, SQLite and PostgreSQL
migrations, Ruff, TypeScript/Vite, Chromium Playwright.
