"""PR11: scoped crews, leader substitution, priorities and manual safety review."""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.availability.models import WorkReservation
from app.availability.service import as_utc
from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_csrf
from app.organization.access import allowed_unit_ids
from app.personnel.models import Person
from app.personnel.service import require_visible_person
from app.work import execution, service as work_service
from app.work.models import WorkCrewMember, WorkOrder, WorkOrderAssignment
from app.work.router import read_order, require_dispatcher
from app.work.schemas import (
    CrewCreate, LeadReplacement, PriorityChange, ReasonNote,
    SafetyCheck, WorkView,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/work", tags=["work execution"])


def dispatch_locked(
    db: Session, user: UserAccount, order_id: UUID,
) -> WorkOrder:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    return order


def checked_person(
    db: Session, user: UserAccount, order: WorkOrder, person_id: UUID,
) -> tuple[Person, UUID]:
    person = db.get(Person, person_id)
    if person is None or person.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    db.refresh(person)
    if user.role != "admin":
        require_visible_person(db, user, person)
    candidate = work_service.assess_candidate(db, order, person)
    if not candidate.eligible or candidate.resource_id is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Hard staffing gates denied the participant",
                "blockers": [block.model_dump() for block in candidate.blockers],
            },
        )
    return person, candidate.resource_id


def new_reservation(
    db: Session, order: WorkOrder, resource_id: UUID, user: UserAccount,
    external_reference: str,
) -> WorkReservation:
    row = WorkReservation(
        enterprise_id=order.enterprise_id, resource_id=resource_id,
        starts_at=as_utc(order.starts_at), ends_at=as_utc(order.ends_at),
        external_reference=external_reference, created_by=user.id,
    )
    db.add(row)
    work_service.flush_safe(db)
    return row


def require_assigned(order: WorkOrder) -> None:
    if order.status != "assigned":
        raise HTTPException(
            status_code=409, detail="Crew staffing is allowed only before work starts"
        )
    if as_utc(order.ends_at) <= as_utc(work_service.utcnow()):
        raise HTTPException(status_code=409, detail="Cannot staff an expired work order")


@router.post(
    "/orders/{order_id}/crew",
    response_model=WorkView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_crew_member(
    order_id: UUID, payload: CrewCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    require_assigned(order)
    leader = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == order.id
    ))
    if leader is None:
        raise HTTPException(status_code=409, detail="Lead must be assigned first")
    if payload.person_id == leader.person_id:
        raise HTTPException(status_code=409, detail="Lead cannot also be a crew member")
    prior = db.scalar(select(WorkCrewMember).where(
        WorkCrewMember.work_order_id == order.id,
        WorkCrewMember.person_id == payload.person_id,
    ))
    if prior is not None:
        raise HTTPException(
            status_code=409, detail="Member already exists in the crew history"
        )
    if len(execution.active_crew(db, order.id)) >= 8:
        raise HTTPException(status_code=409, detail="Maximum 8 supporting crew members")
    person, resource_id = checked_person(db, user, order, payload.person_id)
    slot = new_reservation(
        db, order, resource_id, user, f"WO:{order.id}:crew:{person.id}"
    )
    member = WorkCrewMember(
        enterprise_id=order.enterprise_id, work_order_id=order.id,
        person_id=person.id, resource_id=resource_id,
        reservation_id=slot.id, role=payload.role, joined_by=user.id,
    )
    db.add(member)
    work_service.flush_safe(db)
    work_service.audit(db, user, order, "crew.added", {
        "member_id": member.id, "person_id": person.id,
        "role": member.role, "reservation_id": slot.id,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/crew/{member_id}/remove",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def remove_crew_member(
    order_id: UUID, member_id: UUID, payload: ReasonNote,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    require_assigned(order)
    member = db.get(WorkCrewMember, member_id)
    if (
        member is None or member.work_order_id != order.id
        or member.removed_at is not None
    ):
        raise HTTPException(status_code=404, detail="Active crew member not found")
    slot = db.get(WorkReservation, member.reservation_id)
    if slot is None or slot.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=409, detail="Crew reservation is inconsistent")
    now = as_utc(work_service.utcnow())
    member.removed_at = now
    if slot.cancelled_at is None:
        slot.cancelled_at = now
    work_service.audit(db, user, order, "crew.removed", {
        "member_id": member.id, "person_id": member.person_id,
        "reason": payload.reason, "reservation_id": slot.id,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/replace-lead",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def replace_lead(
    order_id: UUID, payload: LeadReplacement,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    require_assigned(order)
    leader = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == order.id
    ))
    if leader is None:
        raise HTTPException(status_code=409, detail="Missing work order lead")
    if payload.person_id == leader.person_id:
        raise HTTPException(status_code=409, detail="Replacement is the existing lead")
    if db.scalar(select(WorkCrewMember.id).where(
        WorkCrewMember.work_order_id == order.id,
        WorkCrewMember.person_id == payload.person_id,
        WorkCrewMember.removed_at.is_(None),
    )) is not None:
        raise HTTPException(status_code=409, detail="Crew member cannot also become lead")
    person, resource_id = checked_person(db, user, order, payload.person_id)
    old_slot = db.get(WorkReservation, leader.reservation_id)
    if old_slot is None or old_slot.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Current lead reservation is invalid")
    old_person, old_reservation = leader.person_id, leader.reservation_id
    new_slot = new_reservation(
        db, order, resource_id, user, f"WO:{order.id}:swap:{uuid4().hex[:16]}"
    )
    now = as_utc(work_service.utcnow())
    old_slot.cancelled_at = now
    leader.person_id = person.id
    leader.resource_id = resource_id
    leader.reservation_id = new_slot.id
    leader.assigned_by = user.id
    leader.assigned_at = now
    work_service.flush_safe(db)
    work_service.audit(db, user, order, "lead.replaced", {
        "old_person_id": old_person, "new_person_id": person.id,
        "old_reservation_id": old_reservation,
        "new_reservation_id": new_slot.id, "reason": payload.reason,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/priority",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def change_priority(
    order_id: UUID, payload: PriorityChange,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    if order.status not in {"open", "assigned"}:
        raise HTTPException(status_code=409, detail="Priority locked after work starts")
    if order.priority == payload.priority:
        raise HTTPException(status_code=409, detail="Priority is unchanged")
    old = order.priority
    order.priority = payload.priority
    work_service.audit(db, user, order, "priority.changed", {
        "old": old, "new": payload.priority, "reason": payload.reason,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.get("/orders/{order_id}/safety", response_model=SafetyCheck)
def read_safety_check(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SafetyCheck:
    order = read_order(db, user, order_id)
    check = execution.team_safety_check(db, order)
    # A GET is diagnostic, it cannot change work state or guarantee future validity.
    if user.role != "admin":
        # Do not expose a person's eligibility where their CURRENT profile is
        # out of the dispatcher's view, even if they were visible at assignment.
        for member in check.members:
            person = db.get(Person, member.person_id)
            require_visible_person(db, user, person)
    return check


@router.post(
    "/orders/{order_id}/revalidate",
    response_model=SafetyCheck, dependencies=[Depends(require_csrf)],
)
def revalidate_work(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SafetyCheck:
    order = dispatch_locked(db, user, order_id)
    if order.status not in {"assigned", "in_progress", "on_hold"}:
        raise HTTPException(status_code=409, detail="Work not available for a safety recheck")
    check = execution.team_safety_check(db, order)
    if user.role != "admin":
        for member in check.members:
            person = db.get(Person, member.person_id)
            require_visible_person(db, user, person)
    order.last_safety_check_at = check.checked_at
    if not check.passed and order.status == "in_progress":
        execution.set_safety_hold(
            order, check, "A manual safety recheck found invalid participant eligibility"
        )
        work_service.audit(db, user, order, "safety.hold", execution.summarize_failures(check))
    else:
        work_service.audit(db, user, order, "safety.checked", {
            "passed": check.passed, "member_count": len(check.members),
        })
    work_service.commit_safe(db)
    check.status = order.status
    return check


@router.post(
    "/orders/{order_id}/hold",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def manual_hold(
    order_id: UUID, payload: ReasonNote,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    if order.status != "in_progress":
        raise HTTPException(status_code=409, detail="Only active work can be put on hold")
    checked = execution.team_safety_check(db, order)
    execution.set_safety_hold(order, checked, payload.reason)
    work_service.audit(db, user, order, "safety.manual_hold", {
        "reason": payload.reason,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/resume",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def resume_work(
    order_id: UUID, payload: ReasonNote,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    order = dispatch_locked(db, user, order_id)
    if order.status != "on_hold":
        raise HTTPException(status_code=409, detail="Work is not on hold")
    now = as_utc(work_service.utcnow())
    if not as_utc(order.starts_at) <= now < as_utc(order.ends_at):
        raise HTTPException(status_code=409, detail="Cannot resume outside planned window")
    check = execution.team_safety_check(db, order)
    if user.role != "admin":
        for member in check.members:
            person = db.get(Person, member.person_id)
            require_visible_person(db, user, person)
    if not check.passed:
        raise HTTPException(
            status_code=409, detail=execution.summarize_failures(check)
        )
    prior_reason = order.hold_reason
    order.status = "in_progress"
    order.hold_reason = None
    order.last_safety_check_at = check.checked_at
    work_service.audit(db, user, order, "safety.resumed", {
        "reason": payload.reason, "prior_hold_reason": prior_reason,
        "member_count": len(check.members),
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)
