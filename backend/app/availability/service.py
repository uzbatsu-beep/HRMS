"""Predictable fail-closed UTC scheduling evaluation with local weekly shifts."""

import json
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.availability.models import (
    AbsencePeriod, CalendarClosure, SchedulingAuditEvent, ShiftRule, WorkReservation,
)
from app.availability.schemas import AvailabilityResult, Blocker
from app.identity.models import UserAccount
from app.organization.models import Enterprise
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import current_assignment

UTC = timezone.utc
MAX_REQUEST_HOURS = 24


def as_utc(value: datetime) -> datetime:
    """Normalize aware timestamps and SQLite's timezone-naive UTC roundtrips."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def check_range(start: datetime, end: datetime, max_days: int = 1) -> None:
    if end <= start:
        raise HTTPException(status_code=422, detail="End must be after start")
    if end - start > timedelta(days=max_days):
        raise HTTPException(status_code=422, detail="Requested interval is too long")


def intersects(
    a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime
) -> bool:
    """Half-open [start, end): adjacent appointments do not overlap."""
    return a_start < b_end and b_start < a_end


def local_to_utc(naive_local: datetime, zone: ZoneInfo) -> datetime | None:
    """Reject nonexistent and ambiguous wall-clock boundaries, rather than guessing."""
    one = naive_local.replace(tzinfo=zone, fold=0)
    two = naive_local.replace(tzinfo=zone, fold=1)
    if one.utcoffset() != two.utcoffset():
        return None
    utc = one.astimezone(UTC)
    if utc.astimezone(zone).replace(tzinfo=None) != naive_local:
        return None
    return utc


def shift_covers(
    rule: ShiftRule, start: datetime, end: datetime
) -> tuple[bool, bool, date | None]:
    zone = ZoneInfo(rule.time_zone)
    local_day = start.astimezone(zone).date()
    dst_invalid = False
    # An overnight shift can begin on the previous day.
    for offset in (-1, 0, 1):
        day = local_day + timedelta(days=offset)
        if day.weekday() != rule.weekday:
            continue
        if day < rule.valid_from or (rule.valid_to and day > rule.valid_to):
            continue
        local_start = datetime.combine(day, rule.local_start)
        overnight = rule.local_end <= rule.local_start
        end_day = day + timedelta(days=1) if overnight else day
        local_end = datetime.combine(end_day, rule.local_end)
        utc_start = local_to_utc(local_start, zone)
        utc_end = local_to_utc(local_end, zone)
        if utc_start is None or utc_end is None or utc_end <= utc_start:
            dst_invalid = True
            continue
        if start >= utc_start and end <= utc_end:
            return True, dst_invalid, day
    return False, dst_invalid, None


def audit(
    db: Session, user: UserAccount, enterprise_id: UUID, action: str,
    subject_id: UUID, details: dict[str, object],
) -> None:
    db.add(
        SchedulingAuditEvent(
            enterprise_id=enterprise_id, actor_user_id=user.id,
            action=action, subject_id=subject_id,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
        )
    )


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def flush_safe(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scheduling data conflict") from exc


def commit_safe(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Scheduling data conflict") from exc


def evaluate(
    db: Session, person: Person, resource: WorkforceResource,
    start: datetime, end: datetime,
    exclude_reservation_id: UUID | None = None,
) -> AvailabilityResult:
    """Evaluate availability inside a transaction; no claim about credentials/skills."""
    start, end = as_utc(start), as_utc(end)
    check_range(start, end, max_days=1)
    blockers: list[Blocker] = []

    if person.archived_at is not None or not resource.is_active:
        blockers.append(
            Blocker(code="INACTIVE_PERSON", message="Person or workforce resource is inactive")
        )
    rules = list(
        db.scalars(
            select(ShiftRule).where(
                ShiftRule.resource_id == resource.id,
                ShiftRule.disabled_at.is_(None),
            )
        ).all()
    )
    coverage_dates: list[date] = []
    invalid_dst = False
    for rule in rules:
        covered, ambiguous, day = shift_covers(rule, start, end)
        invalid_dst = invalid_dst or ambiguous
        if covered and day is not None:
            zone = ZoneInfo(rule.time_zone)
            last = (end - timedelta(microseconds=1)).astimezone(zone).date()
            coverage_dates = [
                day + timedelta(days=i) for i in range((last - day).days + 1)
            ]
            break
    if not coverage_dates:
        code = "AMBIGUOUS_SHIFT_TIME" if invalid_dst else "NO_SHIFT"
        blockers.append(
            Blocker(code=code, message="No single valid shift covers the whole interval")
        )
        coverage_dates = [start.date(), (end - timedelta(microseconds=1)).date()]

    # A person must belong to one valid primary organizational assignment for
    # every local calendar date occupied by the requested work interval.
    assignment_units: set[UUID] = set()
    for calendar_day in set(coverage_dates):
        assignment = current_assignment(db, resource.id, calendar_day)
        if assignment is None:
            blockers.append(
                Blocker(
                    code="NO_ASSIGNMENT",
                    message="Missing primary employment assignment during the interval",
                )
            )
            break
        assignment_units.add(assignment.unit_id)
    if len(assignment_units) > 1:
        blockers.append(
            Blocker(
                code="ASSIGNMENT_CHANGED",
                message="The worker changes primary organizational unit mid-interval",
            )
        )

    closures = db.scalars(
        select(CalendarClosure).where(
            CalendarClosure.enterprise_id == person.enterprise_id
        )
    ).all()
    for closure in closures:
        zone = ZoneInfo(closure.time_zone)
        local_open = datetime.combine(closure.local_date, time.min).replace(tzinfo=zone)
        local_close = (
            datetime.combine(closure.local_date + timedelta(days=1), time.min)
            .replace(tzinfo=zone)
        )
        if intersects(start, end, local_open.astimezone(UTC), local_close.astimezone(UTC)):
            blockers.append(
                Blocker(
                    code="CALENDAR_CLOSED", message="Enterprise non-working calendar day",
                )
            )
            break

    absences = db.scalars(
        select(AbsencePeriod).where(
            AbsencePeriod.resource_id == resource.id,
            AbsencePeriod.cancelled_at.is_(None),
            AbsencePeriod.starts_at < end,
            AbsencePeriod.ends_at > start,
        )
    ).all()
    if any(
        intersects(start, end, as_utc(item.starts_at), as_utc(item.ends_at))
        for item in absences
    ):
        blockers.append(
            Blocker(code="ABSENT", message="The requested interval intersects unavailability")
        )

    reservations_stmt = select(WorkReservation).where(
        WorkReservation.resource_id == resource.id,
        WorkReservation.cancelled_at.is_(None),
        WorkReservation.starts_at < end,
        WorkReservation.ends_at > start,
    )
    if exclude_reservation_id is not None:
        reservations_stmt = reservations_stmt.where(WorkReservation.id != exclude_reservation_id)
    reservations = db.scalars(reservations_stmt).all()
    if any(
        intersects(start, end, as_utc(item.starts_at), as_utc(item.ends_at))
        for item in reservations
    ):
        blockers.append(
            Blocker(code="BOOKED", message="The worker is already reserved")
        )

    return AvailabilityResult(
        resource_id=resource.id, starts_at=start, ends_at=end,
        available=not blockers, blockers=blockers,
    )
