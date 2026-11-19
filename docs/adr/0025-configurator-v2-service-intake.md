# ADR-0025 — Configurator v2: governed service-intake forms and approval routes

**Date:** 2026-11-19  
**Status:** Proposed in PR #32, subject to explicit review/approval.  
**Data:** Isolated synthetic development/CI data only.

## Problem

Configurator v1 allows only versioned, independently reviewed informational fields
for `Person`. Technical-service teams also need bounded, configurable **intake
forms**, **states**, and **review routes** without programmers changing every
UI screen. Unrestricted workflow engines pose serious authorization and
industrial safety risks if coupled to `WorkOrder`, equipment permits, verified
competencies or physical safety controls.

## Decision and scope

Add an isolated **informational service-request** vertical slice rather than
making existing safety-critical lifecycles editable:

- `workflow_definition_versions`: per-enterprise, per-template-code revisions
  with a structured JSONB document, lifecycle
  `draft -> validated -> independently approved -> published`, effectivity
  date, author, reviewer and publisher.
- `workflow_service_cases`: an intake request scoped to a real existing
  enterprise and organizational unit; pinned to its published definition
  version. Title, bounded values and current state are persisted.
- `workflow_case_events`: append-only case creation and transition history,
  actor, from/to state, action and optional operator note.
- Existing `configuration_audit` records metadata for both definition and
  instance changes; **not** the free-form contents of an intake form.

This is a standalone request for review and tracking. It **cannot** create,
assign, approve, start, stop, complete, cancel or revalidate a `WorkOrder`.
It is NOT a `WorkPermit` or authority to perform hazardous work.
No configurable rule can bypass competence/credential/scheduling gates, RBAC,
enterprise/unit scope, equipment policy, human permit review or LOTO.

## Bounded declarative model

`WorkflowDocument` accepts only:
- Up to 12 informational custom fields: text, integer, boolean, choice, with
  the existing strict value validation and reserved safety/identity codes.
- 2–8 named states, one nonterminal initial state and at least one terminal
  state; every state must be reachable from initial state.
- 1–24 named transitions with an exact `from_state -> to_state`, fixed
  executor `creator | manager | admin` and optional
  `independent_review`. No transitions from terminal states.
- Every transition **into** a terminal state requires an independent
  manager/admin reviewer who is different from the request creator.

No expressions, scripts, webhooks, arbitrary callback URLs, dynamic SQL,
custom role creation, free-form transition guards or arbitrary entity targets
are accepted. Unknown top-level properties and unknown transition rules fail
validation. The validated graph and form are immutable after validation.

## Publication governance

Admin-only/CSRF-protected endpoints create, edit draft, validate, approve and
publish workflow definitions under an enterprise-level row lock.

- A second administrator **different from the author** must approve each
  validated definition before it may be published.
- A published definition is immutable. Future dates are supported; publishing
  in the past is blocked. Two versions of the **same template** cannot share
  one effective date.
- `GET /enterprises/{id}/workflows/active` exposes only current effective
  published definitions to users who can read that enterprise; other
  tenant requests return 404. Administrative history is admin-only.
- A case pins its definition ID. Later publications **do not** silently
  reinterpret already-created case transitions or values.
- Downgrading migration `0020` drops v2 tables; do not use destructive
  downgrade with retained real cases. Rollback requires data retention review.

## Instance authorization and consistency

- Ordinary scoped users may create a service case only in a visible
  organizational unit and only using the currently effective template.
- All reads, histories and pinned-definition views require current unit
  visibility; list filters enterprise/unit server-side.
- A transition requires an authenticated user, CSRF, enterprise row lock,
  fresh scope check, expected source-state match, existing transition in the
  case's immutable template, and exact executor role/creator rule.
- An `independent_review` transition is refused if actor == case creator,
  even when the creator is an administrator or manager.
- Every successful transition creates an immutable event and a metadata-only
  ConfigurationAudit entry in the same transaction.
- Stale transitions fail 409 rather than overwrite another operator's state.

UI action visibility is a convenience only; **the backend is authoritative**.

## API and UI

New endpoints under `/api/v1/configuration`:
`GET/POST /enterprises/{id}/workflow-versions`,
`PUT /workflow-versions/{id}`,
`POST /workflow-versions/{id}/{validate|approve|publish}`,
`GET /enterprises/{id}/workflows/active`,
`GET/POST /enterprises/{id}/service-requests`,
`GET /service-requests/{id}`,
`GET /service-requests/{id}/definition`,
`GET /service-requests/{id}/history`, and
`POST /service-requests/{id}/transitions`.

Existing Configurator fields for Person are unchanged. The v2 UI adds a
structured editor for form fields, states, routes, actor roles and independent
review; template governance actions; service-case creation; and case history.

## Limitations and future decisions

1. Configurable lifecycle is **not** connected to the `WorkOrder` or
   `WorkPermit` state machine. A future connection is a separate reviewed
   architecture/security milestone, not implicit in this PR.
2. Role execution is limited to existing `admin/manager` and case creator.
   Complex delegated role templates, per-transition scopes and reviewer
   queues are deferred. `manager` still requires ordinary exact unit scope.
3. This slice does not implement mail notifications, timers, retries,
   arbitrary automations, large queues, general-purpose BPMN, or field-level
   PII governance.
4. The scoped case-list endpoint is capped to the latest 100 items; a
   dedicated high-volume list/pagination release will be necessary before
   large pilot adoption.
5. No production personnel or operational data before G6 pilot security,
   backup/restore and retention gates.

## Acceptance criteria

Negative tests cover invalid/cyclic/unreachable graphs, direct terminal
bypass, field tampering, missing CSRF, creator self-approval, manager/viewer
authorization, out-of-scope cases, foreign enterprise IDs, stale transitions,
version mutability, future activation, and immutable audit history.
Full PostgreSQL 16 migrations, backend pytest/Ruff, TypeScript/Vite and
Chromium Playwright acceptance must all pass on final PR commit.
