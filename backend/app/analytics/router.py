"""Read-only, server-authoritative operational dashboard with tenant/unit RBAC.

Definitions are recorded in docs/adr/0011-operational-analytics.md.
No safety authorization or utilization percentage is inferred from these metrics.
"""

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.availability.models import WorkReservation
from app.availability.service import as_utc, evaluate
from app.config import settings
from app.credentials.models import PersonCredential
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user
from app.organization.access import allowed_unit_ids
from app.organization.models import Enterprise, OrganizationUnit
from app.personnel.models import EmploymentAssignment, Person, WorkforceResource
from app.work.models import WorkOrder

UTC = timezone.utc
DAYS = 30
RENEWAL_DAYS = 30
PREVIEW_MINUTES = 15
STATUS_NAMES = ("open", "assigned", "in_progress", "on_hold", "completed", "cancelled")

router = APIRouter(prefix=f"{settings.api_v1_prefix}/analytics", tags=["analytics"])


class WorkforceMetrics(BaseModel):
    active_resources: int
    reservable_next_15m: int
    blocked_next_15m: int


class CredentialMetrics(BaseModel):
    expiring_within_30d: int
    expired_records: int
    pending_records: int


class WorkMetrics(BaseModel):
    open: int
    assigned: int
    in_progress: int
    on_hold: int
    completed: int
    cancelled: int


class DailyTrend(BaseModel):
    day: str
    created: int
    completed: int


class UnitLoad(BaseModel):
    unit_id: UUID
    unit_name: str
    reserved_hours: float


class WorkloadMetrics(BaseModel):
    reserved_hours: float
    resources_with_reservations: int
    by_unit: list[UnitLoad]


class HoldItem(BaseModel):
    id: UUID
    code: str
    title: str
    priority: str
    unit_id: UUID


class DashboardSummary(BaseModel):
    enterprise_id: UUID
    unit_id: UUID | None
    as_of: datetime
    period_days: int
    renewal_days: int
    period_start: str
    workforce: WorkforceMetrics
    work_orders: WorkMetrics
    credentials: CredentialMetrics
    workload: WorkloadMetrics
    trends: list[DailyTrend]
    holds: list[HoldItem]


def clipped_minutes(
    starts_at: datetime, ends_at: datetime, start: datetime, end: datetime,
) -> float:
    """Duration of a half-open reservation intersected with the reporting window."""
    return max(
        0.0,
        (min(as_utc(ends_at), end) - max(as_utc(starts_at), start)).total_seconds() / 60,
    )


@router.get(
    "/enterprises/{enterprise_id}/summary",
    response_model=DashboardSummary,
)
def dashboard_summary(
    enterprise_id: UUID,
    unit_id: UUID | None = Query(default=None),
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> DashboardSummary:
    """All roles can read only their explicitly authorized organizational scope."""
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")

    permitted = allowed_unit_ids(db, user, enterprise_id)
    if not permitted:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if unit_id is not None and unit_id not in permitted:
        raise HTTPException(status_code=404, detail="Unit not found")
    scope = {unit_id} if unit_id is not None else permitted

    now = datetime.now(UTC)
    today = now.date()
    first_day = today - timedelta(days=DAYS - 1)
    start = datetime.combine(first_day, time.min, tzinfo=UTC)

    # Select current primary assignments *before* applying the RBAC unit filter,
    # so an older in-scope assignment cannot mask a newer out-of-scope transfer.
    rows = db.execute(
        select(Person, WorkforceResource, EmploymentAssignment)
        .join(WorkforceResource, WorkforceResource.person_id == Person.id)
        .join(EmploymentAssignment, EmploymentAssignment.resource_id == WorkforceResource.id)
        .where(
            Person.enterprise_id == enterprise_id,
            Person.archived_at.is_(None),
            WorkforceResource.is_active.is_(True),
            EmploymentAssignment.enterprise_id == enterprise_id,
            EmploymentAssignment.effective_from <= today,
            or_(
                EmploymentAssignment.effective_to.is_(None),
                EmploymentAssignment.effective_to >= today,
            ),
        )
        .order_by(
            EmploymentAssignment.resource_id,
            EmploymentAssignment.effective_from.desc(),
            EmploymentAssignment.id.desc(),
        )
    ).all()
    current: dict[UUID, tuple[Person, WorkforceResource, UUID]] = {}
    for person, resource, assignment in rows:
        if resource.id not in current:
            current[resource.id] = (person, resource, assignment.unit_id)
    visible = {
        resource_id: item for resource_id, item in current.items()
        if item[2] in scope
    }
    person_ids = {person.id for person, _, _ in visible.values()}
    resource_ids = set(visible)

    reservable = 0
    interval_end = now + timedelta(minutes=PREVIEW_MINUTES)
    for person, resource, _ in visible.values():
        if evaluate(db, person, resource, now, interval_end).available:
            reservable += 1

    work_rows = db.scalars(
        select(WorkOrder).where(
            WorkOrder.enterprise_id == enterprise_id, WorkOrder.unit_id.in_(scope)
        )
    ).all()
    counts = {status: 0 for status in STATUS_NAMES}
    created = defaultdict(int)
    completed = defaultdict(int)
    holds: list[WorkOrder] = []
    for order in work_rows:
        counts[order.status] += 1
        if start <= as_utc(order.created_at) <= now:
            created[as_utc(order.created_at).date()] += 1
        if order.completed_at and start <= as_utc(order.completed_at) <= now:
            completed[as_utc(order.completed_at).date()] += 1
        if order.status == "on_hold":
            holds.append(order)

    credential_rows: list[PersonCredential] = []
    if person_ids:
        credential_rows = list(db.scalars(
            select(PersonCredential).where(
                PersonCredential.enterprise_id == enterprise_id,
                PersonCredential.person_id.in_(person_ids),
            )
        ).all())
    renewal_end = today + timedelta(days=RENEWAL_DAYS)
    expiring = sum(
        row.status == "verified" and row.valid_from <= today
        and row.expires_on is not None and today <= row.expires_on <= renewal_end
        for row in credential_rows
    )
    expired = sum(
        row.status == "verified" and row.expires_on is not None
        and row.expires_on < today for row in credential_rows
    )
    pending = sum(row.status == "pending" for row in credential_rows)

    minutes_by_resource: dict[UUID, float] = defaultdict(float)
    if resource_ids:
        reservations = db.scalars(
            select(WorkReservation).where(
                WorkReservation.enterprise_id == enterprise_id,
                WorkReservation.resource_id.in_(resource_ids),
                WorkReservation.cancelled_at.is_(None),
                WorkReservation.starts_at < now,
                WorkReservation.ends_at > start,
            )
        ).all()
        for reservation in reservations:
            minutes_by_resource[reservation.resource_id] += clipped_minutes(
                reservation.starts_at, reservation.ends_at, start, now,
            )

    minutes_by_unit: dict[UUID, float] = defaultdict(float)
    for resource_id, minutes in minutes_by_resource.items():
        minutes_by_unit[visible[resource_id][2]] += minutes
    unit_names = {
        item.id: item.name for item in db.scalars(
            select(OrganizationUnit).where(
                OrganizationUnit.enterprise_id == enterprise_id,
                OrganizationUnit.id.in_(scope),
            )
        ).all()
    }

    holds.sort(
        key=lambda item: (
            {"critical": 0, "urgent": 1, "normal": 2, "routine": 3}.get(item.priority, 4),
            -as_utc(item.on_hold_at or item.created_at).timestamp(),
        )
    )
    return DashboardSummary(
        enterprise_id=enterprise_id,
        unit_id=unit_id,
        as_of=now,
        period_days=DAYS,
        renewal_days=RENEWAL_DAYS,
        period_start=first_day.isoformat(),
        workforce=WorkforceMetrics(
            active_resources=len(visible),
            reservable_next_15m=reservable,
            blocked_next_15m=len(visible) - reservable,
        ),
        work_orders=WorkMetrics(**counts),
        credentials=CredentialMetrics(
            expiring_within_30d=expiring,
            expired_records=expired,
            pending_records=pending,
        ),
        workload=WorkloadMetrics(
            reserved_hours=round(sum(minutes_by_resource.values()) / 60, 2),
            resources_with_reservations=sum(v > 0 for v in minutes_by_resource.values()),
            by_unit=[
                UnitLoad(
                    unit_id=key,
                    unit_name=unit_names[key],
                    reserved_hours=round(minutes / 60, 2),
                )
                for key, minutes in sorted(
                    minutes_by_unit.items(),
                    key=lambda item: (-item[1], unit_names.get(item[0], "")),
                )
            ],
        ),
        trends=[
            DailyTrend(
                day=(first_day + timedelta(days=i)).isoformat(),
                created=created[first_day + timedelta(days=i)],
                completed=completed[first_day + timedelta(days=i)],
            )
            for i in range(DAYS)
        ],
        holds=[
            HoldItem(
                id=item.id, code=item.code, title=item.title,
                priority=item.priority, unit_id=item.unit_id,
            )
            for item in holds[:8]
        ],
    )
