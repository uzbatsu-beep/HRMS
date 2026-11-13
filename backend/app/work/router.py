"""Work Management API: scoped planning and atomic, non-bypassable assignment."""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.availability.models import WorkReservation
from app.availability.service import as_utc, check_range
from app.competence.models import Skill, SkillScaleLevel
from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids
from app.organization.models import Enterprise, OrganizationUnit
from app.personnel.models import EmploymentAssignment, Person, WorkforceResource
from app.personnel.service import require_visible_person
from app.work import service as work_service
from app.work.models import WorkAuditEvent, WorkOrder, WorkOrderAssignment, WorkSkillRequirement
from app.work.schemas import (
    AssignmentCreate, CandidateView, WorkCreate, WorkAuditView, WorkView,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/work", tags=["work management"])


def read_order(db: Session, user: UserAccount, order_id: UUID) -> WorkOrder:
    order = db.get(WorkOrder, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Work order not found")
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    return order


def require_dispatcher(user: UserAccount) -> None:
    if user.role not in {"admin", "manager"}:
        raise HTTPException(status_code=403, detail="Dispatch role required")


@router.post(
    "/enterprises/{enterprise_id}/orders",
    response_model=WorkView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_order(
    enterprise_id: UUID, payload: WorkCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    require_dispatcher(user)
    check_range(payload.starts_at, payload.ends_at, max_days=1)
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    unit = db.get(OrganizationUnit, payload.unit_id)
    if unit is None or unit.enterprise_id != enterprise_id:
        raise HTTPException(status_code=404, detail="Organizational unit not found")
    work_service.lock_enterprise(db, enterprise_id)
    if user.role != "admin" and payload.unit_id not in allowed_unit_ids(
        db, user, enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Organizational unit not found")
    validated: list[tuple[Skill, SkillScaleLevel]] = []
    for entry in payload.required_skills:
        skill = db.get(Skill, entry.skill_id)
        level = db.get(SkillScaleLevel, entry.min_level_id)
        if (
            skill is None or not skill.is_active or skill.enterprise_id != enterprise_id
            or level is None or level.scale_id != skill.scale_id
        ):
            raise HTTPException(
                status_code=422, detail="Skill/level is inactive, foreign or mismatched"
            )
        validated.append((skill, level))
    order = WorkOrder(
        enterprise_id=enterprise_id, unit_id=unit.id,
        code=payload.code.strip().lower(), title=payload.title.strip(),
        description=payload.description.strip() if payload.description else None,
        activity_code=payload.activity_code.strip().lower(),
        starts_at=as_utc(payload.starts_at), ends_at=as_utc(payload.ends_at),
        status="open", created_by=user.id,
    )
    db.add(order)
    work_service.flush_safe(db)
    for skill, level in validated:
        db.add(WorkSkillRequirement(
            enterprise_id=enterprise_id, work_order_id=order.id,
            skill_id=skill.id, scale_id=skill.scale_id, min_level_id=level.id,
        ))
    work_service.flush_safe(db)
    work_service.audit(db, user, order, "work.created", {
        "code": order.code, "activity_code": order.activity_code,
        "unit_id": order.unit_id, "skills": [x.id for x, _ in validated],
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.get("/enterprises/{enterprise_id}/orders", response_model=list[WorkView])
def list_orders(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkView]:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    query = select(WorkOrder).where(WorkOrder.enterprise_id == enterprise_id)
    if user.role != "admin":
        units = allowed_unit_ids(db, user, enterprise_id)
        if not units:
            raise HTTPException(status_code=404, detail="Enterprise not found")
        query = query.where(WorkOrder.unit_id.in_(units))
    rows = db.scalars(query.order_by(WorkOrder.created_at.desc()).limit(100)).all()
    return [work_service.view_work(db, row) for row in rows]


@router.get("/orders/{order_id}", response_model=WorkView)
def get_order(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    return work_service.view_work(db, read_order(db, user, order_id))


@router.get("/orders/{order_id}/candidates", response_model=list[CandidateView])
def list_candidates(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CandidateView]:
    order = read_order(db, user, order_id)
    if order.status != "open":
        return []
    day = as_utc(order.starts_at).date()
    # Only staffing resources currently in the work's target unit; never
    # enumerate other departments or tenants.
    people = db.scalars(
        select(Person)
        .join(WorkforceResource, WorkforceResource.person_id == Person.id)
        .join(EmploymentAssignment, EmploymentAssignment.resource_id == WorkforceResource.id)
        .where(
            Person.enterprise_id == order.enterprise_id,
            Person.archived_at.is_(None),
            WorkforceResource.is_active.is_(True),
            EmploymentAssignment.unit_id == order.unit_id,
            EmploymentAssignment.effective_from <= day,
            (
                (EmploymentAssignment.effective_to.is_(None))
                | (EmploymentAssignment.effective_to >= day)
            ),
        )
        .order_by(Person.last_name, Person.first_name, Person.id)
        .limit(100)
    ).all()
    result = [work_service.assess_candidate(db, order, person) for person in people]
    return sorted(result, key=lambda item: (not item.eligible, item.full_name))


@router.get("/orders/{order_id}/candidates/{person_id}", response_model=CandidateView)
def check_candidate(
    order_id: UUID, person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CandidateView:
    order = read_order(db, user, order_id)
    person = db.get(Person, person_id)
    if person is None or person.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    if user.role != "admin":
        require_visible_person(db, user, person)
    return work_service.assess_candidate(db, order, person)


@router.post(
    "/orders/{order_id}/assign",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def assign_order(
    order_id: UUID, payload: AssignmentCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    person = db.get(Person, payload.person_id)
    if person is None or person.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Candidate not found")
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    db.refresh(person)
    if user.role != "admin":
        if order.unit_id not in allowed_unit_ids(db, user, order.enterprise_id):
            raise HTTPException(status_code=404, detail="Work order not found")
        require_visible_person(db, user, person)
    if order.status != "open":
        raise HTTPException(status_code=409, detail="Work order is not open")
    if as_utc(order.ends_at) <= work_service.utcnow():
        raise HTTPException(status_code=409, detail="Cannot assign expired work")
    candidate = work_service.assess_candidate(db, order, person)
    if not candidate.eligible or candidate.resource_id is None:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Hard staffing gates denied the assignment",
                "blockers": [item.model_dump() for item in candidate.blockers],
            },
        )
    reservation = WorkReservation(
        enterprise_id=order.enterprise_id, resource_id=candidate.resource_id,
        starts_at=as_utc(order.starts_at), ends_at=as_utc(order.ends_at),
        external_reference=f"WO:{order.id}", created_by=user.id,
    )
    db.add(reservation)
    work_service.flush_safe(db)
    db.add(WorkOrderAssignment(
        enterprise_id=order.enterprise_id, work_order_id=order.id,
        person_id=person.id, resource_id=candidate.resource_id,
        reservation_id=reservation.id, assigned_by=user.id,
    ))
    order.status = "assigned"
    work_service.flush_safe(db)
    work_service.audit(db, user, order, "work.assigned", {
        "person_id": person.id, "resource_id": candidate.resource_id,
        "reservation_id": reservation.id,
        "skills": candidate.verified_skills,
        "credentials": candidate.verified_credentials,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/start",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def start_order(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    if order.status != "assigned":
        raise HTTPException(status_code=409, detail="Work must be assigned before starting")
    now = as_utc(work_service.utcnow())
    if not as_utc(order.starts_at) <= now < as_utc(order.ends_at):
        raise HTTPException(status_code=409, detail="Work cannot start outside planned interval")
    assignment = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == order.id
    ))
    if assignment is None:
        raise HTTPException(status_code=409, detail="Missing assignment")
    reserved = db.get(WorkReservation, assignment.reservation_id)
    if (
        reserved is None or reserved.cancelled_at is not None
        or reserved.resource_id != assignment.resource_id
        or reserved.enterprise_id != order.enterprise_id
        or as_utc(reserved.starts_at) != as_utc(order.starts_at)
        or as_utc(reserved.ends_at) != as_utc(order.ends_at)
    ):
        raise HTTPException(status_code=409, detail="Work reservation was changed/cancelled")
    person = db.get(Person, assignment.person_id)
    if person is None:
        raise HTTPException(status_code=409, detail="Assignee no longer exists")
    db.refresh(person)
    if user.role != "admin":
        require_visible_person(db, user, person)
    candidate = work_service.assess_candidate(
        db, order, person, exclude_reservation_id=reserved.id
    )
    if not candidate.eligible or candidate.resource_id != assignment.resource_id:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Hard staffing gates denied work start",
                "blockers": [item.model_dump() for item in candidate.blockers],
            },
        )
    order.status = "in_progress"
    order.started_at = now
    work_service.audit(db, user, order, "work.started", {
        "person_id": person.id, "reservation_id": reserved.id,
        "skills": candidate.verified_skills,
        "credentials": candidate.verified_credentials,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/complete",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def complete_order(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    if order.status != "in_progress":
        raise HTTPException(status_code=409, detail="Only active work can be completed")
    order.status = "completed"
    order.completed_at = work_service.utcnow()
    work_service.audit(db, user, order, "work.completed", {})
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.post(
    "/orders/{order_id}/cancel",
    response_model=WorkView, dependencies=[Depends(require_csrf)],
)
def cancel_order(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkView:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    if order.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Work order is already terminal")
    assignment = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == order.id
    ))
    now = work_service.utcnow()
    if assignment is not None:
        reservation = db.get(WorkReservation, assignment.reservation_id)
        if reservation is not None and reservation.cancelled_at is None:
            reservation.cancelled_at = now
    order.status = "cancelled"
    order.cancelled_at = now
    work_service.audit(db, user, order, "work.cancelled", {
        "reservation_id": assignment.reservation_id if assignment else None,
    })
    work_service.commit_safe(db)
    db.refresh(order)
    return work_service.view_work(db, order)


@router.get("/audit", response_model=list[WorkAuditView])
def list_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkAuditEvent]:
    query = select(WorkAuditEvent)
    if enterprise_id is not None:
        query = query.where(WorkAuditEvent.enterprise_id == enterprise_id)
    return list(db.scalars(
        query.order_by(WorkAuditEvent.created_at.desc()).limit(100)
    ).all())
