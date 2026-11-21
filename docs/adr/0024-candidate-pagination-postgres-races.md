# ADR-0024 — Scalable, scope-safe candidate discovery and PostgreSQL assignment races

> **Сверка 2026-11-21:** связанный [PR #31](https://github.com/uzbatsu-beep/HRMS/pull/31) объединён в `main`. Если в тексте осталось `Draft` или `Proposed`, это исторический статус **на момент написания ADR**, не состояние GitHub сегодня. [Текущая матрица](../REQUIREMENTS_MATRIX.md) · [Индекс](../DOCUMENTATION_INDEX.md) · [G6 NO-GO](../PILOT_READINESS_G6.md). Реальные ПДн использовать нельзя.


**Status:** PR #31, awaiting review. **Test data:** synthetic only.

## Problem and decision

The historical `GET /api/v1/work/orders/{id}/candidates` scans at most
100 persons sorted alphabetically **before** evaluating their qualifications.
An eligible worker after that cutoff is inaccessible through the browsing UI.
The previous result also filters current organizational visibility in Python
after `LIMIT`, which can yield short, incomplete pages for scoped accounts.

A new endpoint returns explicit **keyset pages** without requiring all
candidate eligibility checks in one request:

`GET /api/v1/work/orders/{id}/candidates-page?limit=20&after={UUID}&search=...`

Response: `{ items: CandidateView[], next_cursor: UUID | null, has_more: boolean }`.

- Default page size 20; minimum 1, maximum 100.
- Stable order by `(last_name, first_name, person_id)` (not global eligibility
  ranking); a typed `after` anchor must still match the requested search
  and caller's accessible dataset or the API returns 422.
- Search matches employee code, first, middle or last name and formatted
  `last_name + first_name`; `%`, `_`, and `!` are escaped as literal text.
- The database filters enterprise, active Person and WorkforceResource,
  planned primary-unit membership and **current** organizational scope
  (for non-admins) **before** fetching each limited page. SQL EXISTS avoids
  duplicated records due to joined historical employment rows. Current
  visibility uses the latest dated primary assignment (the same ordering as
  `current_assignment()`), not `ANY` historically overlapping assignment.
  This fails closed against a corrupt older in-scope employment row.
- Assessments are generated **only** for people on the returned page. Every
  candidate displays a truthful `eligible` state and hard-gate blocker
  reasons. There is no misleading `eligible_only` filter after LIMIT.
- The original `/candidates` endpoint is retained for backward compatibility
  but is a **legacy first-100 response**, not an exhaustive list.
- For work-order states other than `open` or `assigned`, the paginated
  endpoint returns an empty page.
- The frontend's work planner and crew selector use the new endpoint,
  a debounced search input, load-more and error/retry handling.

**Consistency:** keyset iteration is stable with unchanged names, unit scope
and staff roster. It is NOT a cross-request snapshot. Transfers, archive,
renames or concurrent org changes during paging can change membership/order.
Any subsequent assignment revalidates every hard gate under a transaction
lock. Do not treat a previously eligible page result as authorization.

## Concurrency testing and boundary

A separate PostgreSQL-only regression test runs **two authenticated HTTP
clients and two independent SQLAlchemy sessions simultaneously**. It verifies
both (1) same order / same resource and (2) different overlapping orders /
same resource: exactly one HTTP 200, the other 409; one active reservation
for the resource, and one corresponding WorkOrderAssignment.

The test uses the dedicated PostgreSQL 16 CI service after Alembic upgrade.
It is skipped by default for local and SQLite development unless the
`TWM_PG_CONCURRENCY_TESTS=1` flag is explicitly set alongside
`TWM_APP_ENV=test` on an isolated PostgreSQL test database.

The application currently serializes scheduling mutations per enterprise
with `SELECT ... FOR UPDATE`, and re-evaluates candidate availability before
creating a reservation. That protects the API paths covered by this test.
There is **no global PostgreSQL exclusion constraint** protecting arbitrary
external/direct DB writes to `work_reservations`. Such operations must not
bypass the application's transactional scheduling service.

## Non-goals / safety

No changes to credential approval, documented qualification rules, work
start/stop, physical interlocks or PTW/LOTO certification. Search and paging
are read-only diagnostics. No real worker records used.

## Acceptance

- >100 synthetic people, qualified worker after index 100 remains reachable
  by paging, searchable and assignable through unchanged hard gates.
- No duplicates across pages, stable same-name ordering, invalid/cross-unit
  cursor 422, search punctuation is literal, 1..100 limit validation.
- A scoped user cannot see future-transferred staff outside current
  visibility; another enterprise/work order stays 404.
- PostgreSQL concurrency race tests run in CI and both reserve exactly once.
- Existing backend, frontend, migration, Playwright E2E jobs all green.
