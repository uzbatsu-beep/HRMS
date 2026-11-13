"""Review all active crew participants under the enterprise transaction lock.

No background watcher or industrial safety function is provided. Explicit checks
must be called by dispatchers; safety holds prevent completing work in the UI.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.availability.models import WorkReservation
from app.availability.service import as_utc
from app.personnel.models import Person
from app.work.models import WorkCrewMember, WorkOrder, WorkOrderAssignment
from app.work.schemas import Blocker, CandidateView, SafetyCheck, SafetyMember
from app.work.service import assess_candidate, utcnow


def active_crew(db: Session, work_id: UUID) -> list[WorkCrewMember]:
    return list(db.scalars(
        select(WorkCrewMember).where(
            WorkCrewMember.work_order_id == work_id,
            WorkCrewMember.removed_at.is_(None),
        ).order_by(WorkCrewMember.joined_at, WorkCrewMember.id)
    ).all())


def team_safety_check(db: Session, order: WorkOrder) -> SafetyCheck:
    leader = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == order.id
    ))
    members: list[SafetyMember] = []
    roster: list[tuple[str, UUID, UUID, UUID]] = []
    if leader:
        roster.append(("lead", leader.person_id, leader.resource_id, leader.reservation_id))
    for member in active_crew(db, order.id):
        roster.append((member.role, member.person_id, member.resource_id, member.reservation_id))
    unique: set[UUID] = set()
    for role, person_id, resource_id, reservation_id in roster:
        person = db.get(Person, person_id)
        if person is None:
            result = CandidateView(
                person_id=person_id, employee_code="", full_name="Unavailable",
                resource_id=None, eligible=False,
                blockers=[Blocker(
                    source="person", code="PERSON_MISSING",
                    message="Assigned person no longer exists",
                )],
                verified_skills=[], verified_credentials=[],
            )
        else:
            result = assess_candidate(
                db, order, person, exclude_reservation_id=reservation_id
            )
        reservation = db.get(WorkReservation, reservation_id)
        valid = (
            reservation is not None
            and reservation.enterprise_id == order.enterprise_id
            and reservation.resource_id == resource_id
            and reservation.cancelled_at is None
            and as_utc(reservation.starts_at) == as_utc(order.starts_at)
            and as_utc(reservation.ends_at) == as_utc(order.ends_at)
        )
        if not valid:
            result.blockers.append(Blocker(
                source="calendar", code="RESERVATION_INVALID",
                message="Participant's planned reservation is missing, cancelled or changed",
            ))
        if person_id in unique:
            result.blockers.append(Blocker(
                source="person", code="DUPLICATE_PARTICIPANT",
                message="A specialist cannot occupy two work crew roles",
            ))
        unique.add(person_id)
        if result.resource_id != resource_id:
            result.blockers.append(Blocker(
                source="person", code="RESOURCE_MISMATCH",
                message="Assigned resource no longer matches the person",
            ))
        result.eligible = not result.blockers
        members.append(SafetyMember(
            role=role, person_id=person_id, reservation_valid=valid,
            candidate=result,
        ))
    return SafetyCheck(
        work_order_id=order.id, checked_at=as_utc(utcnow()),
        status=order.status,
        passed=bool(leader) and all(member.candidate.eligible for member in members),
        members=members,
    )


def summarize_failures(check: SafetyCheck) -> dict[str, object]:
    return {
        "message": "One or more crew members failed mandatory work gates",
        "members": [
            {
                "person_id": str(member.person_id),
                "role": member.role,
                "blockers": [block.model_dump() for block in member.candidate.blockers],
            }
            for member in check.members if not member.candidate.eligible
        ],
        **({"missing_leader": True} if not check.members else {}),
    }


def set_safety_hold(order: WorkOrder, checked: SafetyCheck, reason: str) -> None:
    order.status = "on_hold"
    order.on_hold_at = as_utc(utcnow())
    order.hold_reason = reason[:400]
    order.last_safety_check_at = checked.checked_at


def full_reservation(
    db: Session, order: WorkOrder, member_id: UUID
) -> WorkReservation | None:
    row = db.get(WorkReservation, member_id)
    if (
        row is None or row.enterprise_id != order.enterprise_id
        or as_utc(row.starts_at) != as_utc(order.starts_at)
        or as_utc(row.ends_at) != as_utc(order.ends_at)
    ):
        return None
    return row
