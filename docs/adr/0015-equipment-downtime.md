# ADR-0015 — Equipment maintenance windows, software reservation gate

Status: PR #19, development/synthetic-only.

## Scope

AssetDowntimeWindow records a planned equipment unavailability interval:
tenant ID, asset, timezone-aware start/end, reason, author and created time.
Cancellation retains the original row and adds cancellation timestamp, actor
and substantive reason. There is no update, delete, silent rescheduling or
backdating of an already finished interval via the API. A replacement schedule
is a new record. The UI accepts browser-local time and converts it to UTC;
all persisted times are timezone-aware.

The allowed interval is nonempty, <= 14 days, and must not have ended already.
Every admin mutation uses CSRF and a shared PostgreSQL enterprise-row lock,
serializing new windows and conflicting updates. Scheduling a partially
overlapping active window on the same asset fails with HTTP 409. Half-open
range semantics [starts_at, ends_at) mean adjacent windows are allowed.
Cancelled rows no longer block. A read-only scoped GET provides up to 100
recent windows including cancellation history. Admin actions are separately
audited without overwriting the cancelled record.

## Work order behavior

Existing **unlinked** WorkOrders retain their previous behavior. Linked orders
acquire an additional mandatory equipment-calendar gate. Any active (not
cancelled) downtime window whose interval intersects the **entire planned**
work-order interval produces EQUIPMENT_DOWNTIME_CONFLICT. The conflict is
independent of whether the start/end of the downtime is presently in the future.
This deliberately conservative planner requires the dispatcher to reschedule
work instead of silently ignoring a later maintenance collision.

The rule participates in explainable pre-assignment matching and in the
existing centralized crew safety check at start, manual revalidation, resume
and completion. Readiness reports include the same software blocker; they do
NOT check physical state or crew qualifications.

Scheduling a conflicting window while work is in_progress immediately places
that WorkOrder in the **application-only** on_hold state, audited with the
change. It does not stop machinery. Cancelling the downtime does not
automatically resume the work. An authorized dispatcher must explicitly
revalidate the other crew, credential, permit, asset and calendar gates before
resumption.

## Authorization & trust

Admin may create/cancel; manager/viewer may read only assets inside their unit
grants. Cross-tenant references and unscoped assets return 404. Invalid,
duplicate, overlapping and cancelled-again updates fail closed.
The asset and work order relationships are tenant-scoped via composite
foreign keys, with a database interval check.

**NOT an industrial safety function.** The scheduling record is a human
planning declaration, not telemetry of the asset's run/stop state, an
emergency-stop or lockout verification. No automatic job timer, scheduler,
notification, proof of energy isolation, permit validity certificate,
machine-controller integration or legally effective PTW is introduced.

Work performed around equipment must follow independent site procedures,
trained operators and validated safety functions. Use synthetic data only
until independent engineering/legal review.

## Acceptance

PostgreSQL Alembic migration from 0012_asset_skill_gates to
0013_asset_downtime; Ruff, Pytest (including negative privilege and
half-open interval cases), frontend TypeScript+Vite and Playwright E2E.
