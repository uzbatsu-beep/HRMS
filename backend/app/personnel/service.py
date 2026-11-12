"""Scoped read policies, temporal validation and transaction helpers."""

import json
from datetime import date

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.identity.models import UserAccount
from app.organization.access import allowed_unit_ids
from app.organization.models import Enterprise, OrganizationUnit
from app.personnel.models import (
    EmploymentAssignment,
    Person,
    PersonnelAuditEvent,
    TeamMembership,
    WorkforceResource,
)


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting personnel data") from exc


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting personnel data") from exc


def lock_enterprise(db: Session, enterprise_id: object) -> None:
    """Serialize dates/assignments across concurrent writes on PostgreSQL."""
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def check_unit(db: Session, enterprise_id: object, unit_id: object) -> OrganizationUnit:
    unit = db.get(OrganizationUnit, unit_id)
    if unit is None or unit.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Unit belongs to another enterprise or is missing")
    return unit


def active_during(start: date, end: date | None, on: date) -> bool:
    return start <= on and (end is None or on <= end)


def periods_overlap(
    a_start: date, a_end: date | None, b_start: date, b_end: date | None
) -> bool:
    return a_start <= (b_end or date.max) and b_start <= (a_end or date.max)


def current_assignment(
    db: Session, resource_id: object, on: date | None = None
) -> EmploymentAssignment | None:
    on = on or date.today()
    return db.scalar(
        select(EmploymentAssignment)
        .where(
            EmploymentAssignment.resource_id == resource_id,
            EmploymentAssignment.effective_from <= on,
            or_(
                EmploymentAssignment.effective_to.is_(None),
                EmploymentAssignment.effective_to >= on,
            ),
        )
        .order_by(EmploymentAssignment.effective_from.desc())
        .limit(1)
    )


def visible_person(db: Session, user: UserAccount, person: Person) -> bool:
    if user.role == "admin":
        return True
    if person.archived_at is not None:
        return False
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person.id)
    )
    if resource is None or not resource.is_active:
        return False
    assignment = current_assignment(db, resource.id)
    return (
        assignment is not None
        and assignment.unit_id in allowed_unit_ids(db, user, person.enterprise_id)
    )


def require_visible_person(db: Session, user: UserAccount, person: Person | None) -> Person:
    if person is None or not visible_person(db, user, person):
        raise HTTPException(status_code=404, detail="Person not found")
    return person


def resource_for_person(db: Session, person_id: object) -> WorkforceResource:
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person_id)
    )
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


def admin_resource(db: Session, resource_id: object) -> tuple[WorkforceResource, Person]:
    resource = db.get(WorkforceResource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    person = db.get(Person, resource.person_id)
    if person is None or not resource.is_active or person.archived_at is not None:
        raise HTTPException(status_code=409, detail="Resource has been archived")
    return resource, person


def personnel_audit(
    db: Session,
    admin: UserAccount,
    person: Person,
    action: str,
    details: dict[str, object],
) -> None:
    db.add(
        PersonnelAuditEvent(
            enterprise_id=person.enterprise_id,
            person_id=person.id,
            actor_user_id=admin.id,
            action=action,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
        )
    )


def check_assignment_availability(
    db: Session,
    resource_id: object,
    start: date,
    end: date | None,
) -> None:
    assignments = db.scalars(
        select(EmploymentAssignment).where(EmploymentAssignment.resource_id == resource_id)
    ).all()
    if any(periods_overlap(item.effective_from, item.effective_to, start, end) for item in assignments):
        raise HTTPException(status_code=409, detail="Primary assignment dates overlap")


def check_team_availability(
    db: Session,
    resource_id: object,
    unit_id: object,
    start: date,
    end: date | None,
) -> None:
    memberships = db.scalars(
        select(TeamMembership).where(
            TeamMembership.resource_id == resource_id,
            TeamMembership.unit_id == unit_id,
        )
    ).all()
    if any(periods_overlap(item.effective_from, item.effective_to, start, end) for item in memberships):
        raise HTTPException(status_code=409, detail="Team membership dates overlap")
