"""Personnel API: scoped profiles, dated transfers, additional teams and archiving."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import exists, or_, select
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids
from app.organization.permissions import can_review_person
from app.competence.models import UserPersonLink
from app.organization.models import Enterprise, OrganizationUnit
from app.personnel.models import (
    EmploymentAssignment,
    Person,
    PersonnelAuditEvent,
    TeamMembership,
    WorkforceResource,
)
from app.personnel.schemas import (
    AssignmentCreate,
    AssignmentView,
    MembershipClose,
    PersonCreate,
    PersonDetail,
    PersonUpdate,
    PersonView,
    PersonnelAuditView,
    TeamMembershipCreate,
    TeamMembershipView,
    TransferCreate,
)
from app.personnel.service import (
    admin_resource,
    check_assignment_availability,
    check_team_availability,
    check_unit,
    commit_or_conflict,
    current_assignment,
    flush_or_conflict,
    lock_enterprise,
    personnel_audit,
    require_visible_person,
    resource_for_person,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/personnel", tags=["personnel"])


def require_enterprise(db: Session, enterprise_id: UUID) -> Enterprise:
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return enterprise


def profile_view(db: Session, person: Person) -> PersonView:
    resource = resource_for_person(db, person.id)
    current = (
        current_assignment(db, resource.id)
        if resource.is_active and person.archived_at is None
        else None
    )
    unit = db.get(OrganizationUnit, current.unit_id) if current is not None else None
    return PersonView(
        id=person.id,
        resource_id=resource.id,
        enterprise_id=person.enterprise_id,
        employee_code=person.employee_code,
        first_name=person.first_name,
        last_name=person.last_name,
        middle_name=person.middle_name,
        archived_at=person.archived_at,
        current_unit_id=current.unit_id if current else None,
        current_unit_name=unit.name if unit else None,
        position_title=current.position_title if current else None,
        current_since=current.effective_from if current else None,
    )


def profile_detail(db: Session, person: Person, user: UserAccount) -> PersonDetail:
    profile = profile_view(db, person)
    resource = resource_for_person(db, person.id)
    assignments = list(
        db.scalars(
            select(EmploymentAssignment)
            .where(EmploymentAssignment.resource_id == resource.id)
            .order_by(EmploymentAssignment.effective_from.desc())
        ).all()
    )
    teams = list(
        db.scalars(
            select(TeamMembership)
            .where(TeamMembership.resource_id == resource.id)
            .order_by(TeamMembership.effective_from.desc())
        ).all()
    )
    if user.role != "admin":
        permitted = allowed_unit_ids(db, user, person.enterprise_id)
        assignments = [assignment for assignment in assignments if assignment.unit_id in permitted]
        teams = [team for team in teams if team.unit_id in permitted]
    return PersonDetail(
        **profile.model_dump(),
        assignments=[AssignmentView.model_validate(row) for row in assignments],
        team_memberships=[TeamMembershipView.model_validate(row) for row in teams],
    )


@router.get("/enterprises/{enterprise_id}/persons", response_model=list[PersonView])
def list_persons(
    enterprise_id: UUID,
    q: Annotated[str | None, Query(max_length=100)] = None,
    unit_id: UUID | None = None,
    include_archived: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[PersonView]:
    enterprise = require_enterprise(db, enterprise_id)
    if user.role != "admin" and not allowed_unit_ids(db, user, enterprise.id):
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if include_archived and user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    if unit_id is not None:
        check_unit(db, enterprise_id, unit_id)

    query = select(Person).where(Person.enterprise_id == enterprise_id)
    if not include_archived:
        query = query.where(Person.archived_at.is_(None))
    if q:
        search = f"%{q.strip()}%"
        query = query.where(
            or_(
                Person.employee_code.ilike(search),
                Person.first_name.ilike(search),
                Person.last_name.ilike(search),
                Person.middle_name.ilike(search),
            )
        )

    today = date.today()
    if user.role != "admin" or unit_id is not None:
        allowed = allowed_unit_ids(db, user, enterprise_id)
        if user.role != "admin" and unit_id is not None and unit_id not in allowed:
            raise HTTPException(status_code=404, detail="Unit not found")
        target_ids = {unit_id} if unit_id is not None else allowed
        if not target_ids:
            return []
        eligible = (
            select(EmploymentAssignment.id)
            .join(
                WorkforceResource,
                WorkforceResource.id == EmploymentAssignment.resource_id,
            )
            .where(
                WorkforceResource.person_id == Person.id,
                WorkforceResource.is_active.is_(True),
                EmploymentAssignment.enterprise_id == enterprise_id,
                EmploymentAssignment.unit_id.in_(target_ids),
                EmploymentAssignment.effective_from <= today,
                or_(
                    EmploymentAssignment.effective_to.is_(None),
                    EmploymentAssignment.effective_to >= today,
                ),
            )
        )
        query = query.where(exists(eligible))

    rows = db.scalars(
        query.order_by(Person.last_name, Person.first_name, Person.employee_code)
        .limit(limit).offset(offset)
    ).all()
    return [profile_view(db, person) for person in rows]


@router.post(
    "/enterprises/{enterprise_id}/persons",
    response_model=PersonDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_person(
    enterprise_id: UUID,
    payload: PersonCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonDetail:
    require_enterprise(db, enterprise_id)
    lock_enterprise(db, enterprise_id)
    if payload.unit_id is not None:
        check_unit(db, enterprise_id, payload.unit_id)
    person = Person(
        enterprise_id=enterprise_id,
        employee_code=payload.employee_code.strip().upper(),
        first_name=payload.first_name.strip(),
        last_name=payload.last_name.strip(),
        middle_name=payload.middle_name.strip() if payload.middle_name else None,
    )
    if not person.first_name or not person.last_name:
        raise HTTPException(status_code=422, detail="First and last names must not be empty")
    db.add(person)
    flush_or_conflict(db)
    resource = WorkforceResource(enterprise_id=enterprise_id, person_id=person.id)
    db.add(resource)
    flush_or_conflict(db)
    if payload.unit_id is not None:
        db.add(
            EmploymentAssignment(
                enterprise_id=enterprise_id,
                resource_id=resource.id,
                unit_id=payload.unit_id,
                effective_from=payload.effective_from,
                position_title=payload.position_title,
            )
        )
    personnel_audit(
        db, admin, person, "person.created",
        {"employee_code": person.employee_code, "unit_id": payload.unit_id},
    )
    commit_or_conflict(db)
    return profile_detail(db, person, admin)


@router.get("/persons/{person_id}/review-capabilities")
def personnel_review_capabilities(
    person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, bool]:
    """Return only own reviewer permissions for a visible active Person.

    Does not expose other users' grants. Actual approval still re-checks
    record status, author != reviewer, own-link and evidence/expiry rules.
    """
    person = db.get(Person, person_id)
    require_visible_person(db, user, person)
    linked = db.scalar(select(UserPersonLink.person_id).where(
        UserPersonLink.user_id == user.id,
    ))
    if linked == person_id:
        return {"competence_review": False, "credential_review": False}
    return {
        "competence_review": can_review_person(
            db, user, person, "competence.assessment.review",
        ),
        "credential_review": can_review_person(
            db, user, person, "credentials.record.review",
        ),
    }


@router.get("/persons/{person_id}", response_model=PersonDetail)
def get_person(
    person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonDetail:
    person = require_visible_person(db, user, db.get(Person, person_id))
    return profile_detail(db, person, user)


@router.patch(
    "/persons/{person_id}",
    response_model=PersonDetail,
    dependencies=[Depends(require_csrf)],
)
def update_person(
    person_id: UUID,
    payload: PersonUpdate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonDetail:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if person.archived_at is not None:
        raise HTTPException(status_code=409, detail="Person is archived")
    changed = payload.model_fields_set
    if not changed:
        raise HTTPException(status_code=422, detail="No changes provided")
    lock_enterprise(db, person.enterprise_id)
    db.refresh(person)
    before = {name: getattr(person, name) for name in changed}
    for name in changed:
        value = getattr(payload, name)
        if name in {"first_name", "last_name"}:
            if value is None or not value.strip():
                raise HTTPException(status_code=422, detail=f"{name} must not be empty")
            value = value.strip()
        elif value is not None:
            value = value.strip() or None
        setattr(person, name, value)
    after = {name: getattr(person, name) for name in changed}
    personnel_audit(db, admin, person, "person.updated", {"before": before, "after": after})
    commit_or_conflict(db)
    return profile_detail(db, person, admin)


@router.post(
    "/persons/{person_id}/archive",
    response_model=PersonDetail,
    dependencies=[Depends(require_csrf)],
)
def archive_person(
    person_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonDetail:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    lock_enterprise(db, person.enterprise_id)
    db.refresh(person)
    if person.archived_at is not None:
        raise HTTPException(status_code=409, detail="Person already archived")
    resource = resource_for_person(db, person.id)
    person.archived_at = datetime.now(timezone.utc)
    resource.is_active = False
    personnel_audit(db, admin, person, "person.archived", {"resource_id": str(resource.id)})
    commit_or_conflict(db)
    return profile_detail(db, person, admin)


@router.post(
    "/resources/{resource_id}/assignments",
    response_model=AssignmentView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_primary_assignment(
    resource_id: UUID,
    payload: AssignmentCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> EmploymentAssignment:
    resource, person = admin_resource(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    check_unit(db, resource.enterprise_id, payload.unit_id)
    check_assignment_availability(db, resource_id, payload.effective_from, payload.effective_to)
    row = EmploymentAssignment(
        enterprise_id=resource.enterprise_id,
        resource_id=resource.id,
        unit_id=payload.unit_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        position_title=payload.position_title,
    )
    db.add(row)
    flush_or_conflict(db)
    personnel_audit(
        db, admin, person, "assignment.created",
        {
            "assignment_id": row.id, "unit_id": row.unit_id,
            "effective_from": row.effective_from, "effective_to": row.effective_to,
        },
    )
    commit_or_conflict(db)
    return row


@router.post(
    "/resources/{resource_id}/transfer",
    response_model=AssignmentView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def transfer_resource(
    resource_id: UUID,
    payload: TransferCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> EmploymentAssignment:
    resource, person = admin_resource(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    check_unit(db, resource.enterprise_id, payload.unit_id)
    previous = current_assignment(db, resource.id, payload.effective_on)
    if previous is None:
        raise HTTPException(status_code=409, detail="No assignment at transfer date")
    db.refresh(previous)
    if previous.effective_from >= payload.effective_on:
        raise HTTPException(status_code=409, detail="Transfer must follow assignment start")
    if previous.unit_id == payload.unit_id:
        raise HTTPException(status_code=409, detail="Resource is already in this unit")
    previous_end = previous.effective_to
    previous.effective_to = payload.effective_on - timedelta(days=1)
    # Validate new interval against all other assignments; the previous record is
    # intentionally shortened before the overlap scan.
    flush_or_conflict(db)
    check_assignment_availability(db, resource.id, payload.effective_on, previous_end)
    new = EmploymentAssignment(
        enterprise_id=resource.enterprise_id,
        resource_id=resource.id,
        unit_id=payload.unit_id,
        position_title=payload.position_title or previous.position_title,
        effective_from=payload.effective_on,
        effective_to=previous_end,
    )
    db.add(new)
    flush_or_conflict(db)
    personnel_audit(
        db, admin, person, "assignment.transferred",
        {
            "previous_id": previous.id, "from_unit": previous.unit_id,
            "new_id": new.id, "to_unit": new.unit_id,
            "effective_on": payload.effective_on,
        },
    )
    commit_or_conflict(db)
    return new


@router.post(
    "/resources/{resource_id}/teams",
    response_model=TeamMembershipView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def add_team_membership(
    resource_id: UUID,
    payload: TeamMembershipCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> TeamMembership:
    resource, person = admin_resource(db, resource_id)
    lock_enterprise(db, resource.enterprise_id)
    check_unit(db, resource.enterprise_id, payload.unit_id)
    check_team_availability(
        db, resource.id, payload.unit_id, payload.effective_from, payload.effective_to
    )
    membership = TeamMembership(
        enterprise_id=resource.enterprise_id,
        resource_id=resource.id,
        unit_id=payload.unit_id,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
    )
    db.add(membership)
    flush_or_conflict(db)
    personnel_audit(
        db, admin, person, "team.joined",
        {"team_id": membership.id, "unit_id": membership.unit_id},
    )
    commit_or_conflict(db)
    return membership


@router.patch(
    "/teams/{membership_id}/close",
    response_model=TeamMembershipView,
    dependencies=[Depends(require_csrf)],
)
def close_membership(
    membership_id: UUID,
    payload: MembershipClose,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> TeamMembership:
    membership = db.get(TeamMembership, membership_id)
    if membership is None:
        raise HTTPException(status_code=404, detail="Membership not found")
    lock_enterprise(db, membership.enterprise_id)
    db.refresh(membership)
    resource, person = admin_resource(db, membership.resource_id)
    if payload.effective_to < membership.effective_from:
        raise HTTPException(status_code=422, detail="End date precedes start")
    if membership.effective_to is not None and payload.effective_to > membership.effective_to:
        raise HTTPException(status_code=409, detail="Cannot extend membership via close")
    before = membership.effective_to
    membership.effective_to = payload.effective_to
    personnel_audit(
        db, admin, person, "team.closed",
        {"team_id": membership.id, "before": before, "after": membership.effective_to},
    )
    commit_or_conflict(db)
    return membership


@router.get("/audit", response_model=list[PersonnelAuditView])
def list_personnel_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[PersonnelAuditEvent]:
    query = select(PersonnelAuditEvent).order_by(PersonnelAuditEvent.created_at.desc())
    if enterprise_id is not None:
        query = query.where(PersonnelAuditEvent.enterprise_id == enterprise_id)
    return list(db.scalars(query.limit(100)).all())
