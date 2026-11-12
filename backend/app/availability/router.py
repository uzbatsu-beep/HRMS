"""Scoped scheduling and calendar APIs with transactional reservation checks."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import AwareDatetime
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.availability.models import (
    AbsencePeriod, CalendarClosure, SchedulingAuditEvent, ShiftRule, WorkReservation,
)
from app.availability.schemas import (
    AbsenceCreate, AbsenceView, AuditView, AvailabilityResult, CalendarView,
    ClosureCreate, ClosureView, ReservationCreate, ReservationView,
    ShiftRuleCreate, ShiftRuleView, WorkloadSummary,
)
from app.availability.service import (
    as_utc, audit, check_range, commit_safe, evaluate, flush_safe, intersects, lock_enterprise,
)
from app.competence.models import UserPersonLink
from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import can_read_enterprise
from app.organization.models import Enterprise
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import require_visible_person

router = APIRouter(prefix=f"{settings.api_v1_prefix}/availability", tags=["availability"])


def available_person(
    db: Session, user: UserAccount, person_id: UUID,
) -> tuple[Person, WorkforceResource]:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if user.role != "admin":
        linked = db.scalar(
            select(UserPersonLink.person_id)
            .where(UserPersonLink.user_id == user.id)
        )
        if linked != person.id or person.archived_at is not None:
            require_visible_person(db, user, person)
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person.id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return person, resource


def resource_for_write(db: Session, resource_id: UUID) -> tuple[Person, WorkforceResource]:
    resource = db.get(WorkforceResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    person = db.get(Person, resource.person_id)
    if person is None or person.archived_at is not None or not resource.is_active:
        raise HTTPException(status_code=409, detail="Person or resource is inactive")
    return person, resource


def readable_enterprise(db: Session, user: UserAccount, enterprise_id: UUID) -> None:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if can_read_enterprise(db, user, enterprise_id):
        return
    linked = db.scalar(
        select(Person.id)
        .join(UserPersonLink, UserPersonLink.person_id == Person.id)
        .join(WorkforceResource, WorkforceResource.person_id == Person.id)
        .where(
            UserPersonLink.user_id == user.id, Person.enterprise_id == enterprise_id,
            Person.archived_at.is_(None), WorkforceResource.is_active.is_(True),
        )
        .limit(1)
    )
    if linked is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")


@router.get(
    "/enterprises/{enterprise_id}/closures", response_model=list[ClosureView],
)
def list_closures(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CalendarClosure]:
    readable_enterprise(db, user, enterprise_id)
    return list(db.scalars(
        select(CalendarClosure).where(CalendarClosure.enterprise_id == enterprise_id)
        .order_by(CalendarClosure.local_date)
    ).all())


@router.post(
    "/enterprises/{enterprise_id}/closures",
    response_model=ClosureView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_closure(
    enterprise_id: UUID, payload: ClosureCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CalendarClosure:
    readable_enterprise(db, admin, enterprise_id)
    lock_enterprise(db, enterprise_id)
    if not payload.label.strip():
        raise HTTPException(status_code=422, detail="Calendar label cannot be blank")
    entry = CalendarClosure(
        enterprise_id=enterprise_id, local_date=payload.local_date,
        time_zone=payload.time_zone, label=payload.label.strip(),
    )
    db.add(entry)
    flush_safe(db)
    audit(db, admin, enterprise_id, "calendar.closed", entry.id, {
        "local_date": entry.local_date, "time_zone": entry.time_zone,
    })
    commit_safe(db)
    db.refresh(entry)
    return entry


@router.post(
    "/resources/{resource_id}/shifts",
    response_model=ShiftRuleView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_shift(
    resource_id: UUID, payload: ShiftRuleCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ShiftRule:
    person, resource = resource_for_write(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    # Do not silently permit excessive 23-hour schedules.
    start_seconds = (
        payload.local_start.hour * 3600 + payload.local_start.minute * 60
        + payload.local_start.second
    )
    end_seconds = (
        payload.local_end.hour * 3600 + payload.local_end.minute * 60
        + payload.local_end.second
    )
    seconds = (end_seconds - start_seconds) % 86400
    if seconds > 18 * 3600:
        raise HTTPException(status_code=422, detail="Shift may not exceed 18 local hours")
    shift = ShiftRule(
        enterprise_id=resource.enterprise_id, resource_id=resource.id,
        weekday=payload.weekday, local_start=payload.local_start,
        local_end=payload.local_end, time_zone=payload.time_zone,
        valid_from=payload.valid_from, valid_to=payload.valid_to,
    )
    db.add(shift)
    flush_safe(db)
    audit(db, admin, person.enterprise_id, "shift.created", shift.id, {
        "resource_id": resource.id, "weekday": shift.weekday,
        "start": shift.local_start, "end": shift.local_end,
        "zone": shift.time_zone,
    })
    commit_safe(db)
    db.refresh(shift)
    return shift


@router.post(
    "/shifts/{rule_id}/disable",
    response_model=ShiftRuleView, dependencies=[Depends(require_csrf)],
)
def disable_shift(
    rule_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ShiftRule:
    rule = db.get(ShiftRule, rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Shift not found")
    lock_enterprise(db, rule.enterprise_id)
    db.refresh(rule)
    if rule.disabled_at is not None:
        raise HTTPException(status_code=409, detail="Shift is already disabled")
    rule.disabled_at = datetime.now(timezone.utc)
    audit(db, admin, rule.enterprise_id, "shift.disabled", rule.id, {
        "resource_id": rule.resource_id,
    })
    commit_safe(db)
    return rule


@router.post(
    "/resources/{resource_id}/absences",
    response_model=AbsenceView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_absence(
    resource_id: UUID, payload: AbsenceCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AbsenceView:
    check_range(payload.starts_at, payload.ends_at, max_days=366)
    person, resource = resource_for_write(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    # Absence is authoritative: it can invalidate an earlier reservation.
    absence = AbsencePeriod(
        enterprise_id=person.enterprise_id, resource_id=resource.id,
        starts_at=as_utc(payload.starts_at), ends_at=as_utc(payload.ends_at),
        category=payload.category, note=payload.note.strip() if payload.note else None,
        created_by=admin.id,
    )
    db.add(absence)
    flush_safe(db)
    audit(db, admin, person.enterprise_id, "absence.created", absence.id, {
        "resource_id": resource.id, "starts_at": absence.starts_at,
        "ends_at": absence.ends_at, "category": absence.category,
    })
    commit_safe(db)
    return absence_view(absence, True)


@router.post(
    "/absences/{absence_id}/cancel",
    response_model=AbsenceView, dependencies=[Depends(require_csrf)],
)
def cancel_absence(
    absence_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AbsenceView:
    absence = db.get(AbsencePeriod, absence_id)
    if absence is None:
        raise HTTPException(status_code=404, detail="Absence not found")
    lock_enterprise(db, absence.enterprise_id)
    db.refresh(absence)
    if absence.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Absence already cancelled")
    absence.cancelled_at = datetime.now(timezone.utc)
    audit(db, admin, absence.enterprise_id, "absence.cancelled", absence.id, {
        "resource_id": absence.resource_id,
    })
    commit_safe(db)
    return absence_view(absence, True)


@router.post(
    "/resources/{resource_id}/reservations",
    response_model=ReservationView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def reserve(
    resource_id: UUID, payload: ReservationCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ReservationView:
    person, resource = resource_for_write(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    # Re-read the subject under the same enterprise lock as personnel mutations.
    db.refresh(person)
    db.refresh(resource)
    result = evaluate(db, person, resource, payload.starts_at, payload.ends_at)
    if not result.available:
        raise HTTPException(
            status_code=409, detail={
                "message": "Calendar reservation blocked",
                "blockers": [item.model_dump() for item in result.blockers],
            },
        )
    reference = payload.external_reference.strip() if payload.external_reference else None
    entry = WorkReservation(
        enterprise_id=person.enterprise_id, resource_id=resource.id,
        starts_at=as_utc(payload.starts_at), ends_at=as_utc(payload.ends_at),
        external_reference=reference or None, created_by=admin.id,
    )
    db.add(entry)
    flush_safe(db)
    audit(db, admin, person.enterprise_id, "reservation.created", entry.id, {
        "resource_id": resource.id, "starts_at": entry.starts_at,
        "ends_at": entry.ends_at, "reference": entry.external_reference,
    })
    commit_safe(db)
    return reservation_view(entry, True)


@router.post(
    "/reservations/{reservation_id}/cancel",
    response_model=ReservationView, dependencies=[Depends(require_csrf)],
)
def cancel_reservation(
    reservation_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ReservationView:
    entry = db.get(WorkReservation, reservation_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Reservation not found")
    lock_enterprise(db, entry.enterprise_id)
    db.refresh(entry)
    if entry.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Reservation already cancelled")
    entry.cancelled_at = datetime.now(timezone.utc)
    audit(db, admin, entry.enterprise_id, "reservation.cancelled", entry.id, {
        "resource_id": entry.resource_id,
    })
    commit_safe(db)
    return reservation_view(entry, True)


def absence_view(item: AbsencePeriod, privileged: bool) -> AbsenceView:
    return AbsenceView(
        id=item.id, starts_at=item.starts_at, ends_at=item.ends_at,
        category=item.category if privileged else None,
        note=item.note if privileged else None,
        cancelled_at=item.cancelled_at,
    )


def reservation_view(item: WorkReservation, privileged: bool) -> ReservationView:
    return ReservationView(
        id=item.id, starts_at=item.starts_at, ends_at=item.ends_at,
        external_reference=item.external_reference if privileged else None,
        cancelled_at=item.cancelled_at,
    )


@router.get("/persons/{person_id}/calendar", response_model=CalendarView)
def calendar(
    person_id: UUID,
    start: AwareDatetime = Query(...),  # noqa: B008
    end: AwareDatetime = Query(...),  # noqa: B008
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CalendarView:
    check_range(start, end, max_days=31)
    person, resource = available_person(db, user, person_id)
    start, end = as_utc(start), as_utc(end)
    # Query all records for the selected resource; trim returned intervals.
    shifts = list(db.scalars(select(ShiftRule).where(
        ShiftRule.resource_id == resource.id,
    ).order_by(ShiftRule.weekday)).all())
    absences = list(db.scalars(select(AbsencePeriod).where(
        AbsencePeriod.resource_id == resource.id,
        AbsencePeriod.starts_at < end, AbsencePeriod.ends_at > start,
    ).order_by(AbsencePeriod.starts_at)).all())
    booked = list(db.scalars(select(WorkReservation).where(
        WorkReservation.resource_id == resource.id,
        WorkReservation.starts_at < end, WorkReservation.ends_at > start,
    ).order_by(WorkReservation.starts_at)).all())
    closures = list(db.scalars(select(CalendarClosure).where(
        CalendarClosure.enterprise_id == person.enterprise_id,
    ).order_by(CalendarClosure.local_date)).all())
    return CalendarView(
        resource_id=resource.id,
        shift_rules=[ShiftRuleView.model_validate(row) for row in shifts],
        absences=[absence_view(row, user.role == "admin") for row in absences],
        reservations=[reservation_view(row, user.role == "admin") for row in booked],
        closures=[ClosureView.model_validate(row) for row in closures],
    )


@router.get("/persons/{person_id}/check", response_model=AvailabilityResult)
def check_availability(
    person_id: UUID,
    start: AwareDatetime = Query(...),  # noqa: B008
    end: AwareDatetime = Query(...),  # noqa: B008
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AvailabilityResult:
    person, resource = available_person(db, user, person_id)
    return evaluate(db, person, resource, start, end)


@router.get("/persons/{person_id}/load", response_model=WorkloadSummary)
def workload(
    person_id: UUID,
    start: AwareDatetime = Query(...),  # noqa: B008
    end: AwareDatetime = Query(...),  # noqa: B008
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkloadSummary:
    check_range(start, end, max_days=31)
    _, resource = available_person(db, user, person_id)
    start, end = as_utc(start), as_utc(end)
    def minutes_between(one: datetime, two: datetime) -> int:
        left, right = max(start, as_utc(one)), min(end, as_utc(two))
        return max(0, int((right - left).total_seconds() // 60))

    reservations = list(db.scalars(select(WorkReservation).where(
        WorkReservation.resource_id == resource.id, WorkReservation.cancelled_at.is_(None),
        WorkReservation.starts_at < end, WorkReservation.ends_at > start,
    )).all())
    absences = list(db.scalars(select(AbsencePeriod).where(
        AbsencePeriod.resource_id == resource.id, AbsencePeriod.cancelled_at.is_(None),
        AbsencePeriod.starts_at < end, AbsencePeriod.ends_at > start,
    )).all())
    return WorkloadSummary(
        resource_id=resource.id, starts_at=start, ends_at=end,
        reserved_minutes=sum(minutes_between(r.starts_at, r.ends_at) for r in reservations),
        absence_minutes=sum(minutes_between(a.starts_at, a.ends_at) for a in absences),
        active_reservations=len(reservations),
    )


@router.get("/audit", response_model=list[AuditView])
def list_scheduling_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[SchedulingAuditEvent]:
    stmt = select(SchedulingAuditEvent).order_by(SchedulingAuditEvent.created_at.desc())
    if enterprise_id is not None:
        stmt = stmt.where(SchedulingAuditEvent.enterprise_id == enterprise_id)
    return list(db.scalars(stmt.limit(100)).all())
