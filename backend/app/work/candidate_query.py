"""Keyset candidate queries with SQL-level tenant/scope filtering.

No eligibility filtering before/after LIMIT: every matching Person is reachable
even if their skill/credential/availability gates fail.
"""

from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session

from app.availability.service import as_utc
from app.identity.models import UserAccount
from app.organization.access import allowed_unit_ids
from app.personnel.models import EmploymentAssignment, Person, WorkforceResource
from app.work.models import WorkOrder
from app.work.schemas import CandidatePage, CandidateView
from app.work import service as work_service


def _search_pattern(value: str) -> str:
    """Treat %, _, and the escape character as literal user input."""
    return "%" + (
        value.casefold().replace("!", "!!").replace("%", "!%").replace("_", "!_")
    ) + "%"


def candidate_statement(
    db: Session, user: UserAccount, work: WorkOrder, search: str,
):
    day = as_utc(work.starts_at).date()
    scheduled = exists(
        select(EmploymentAssignment.id).where(
            EmploymentAssignment.resource_id == WorkforceResource.id,
            EmploymentAssignment.enterprise_id == work.enterprise_id,
            EmploymentAssignment.unit_id == work.unit_id,
            EmploymentAssignment.effective_from <= day,
            or_(
                EmploymentAssignment.effective_to.is_(None),
                EmploymentAssignment.effective_to >= day,
            ),
        )
    )
    statement = (
        select(Person)
        .join(WorkforceResource, WorkforceResource.person_id == Person.id)
        .where(
            Person.enterprise_id == work.enterprise_id,
            Person.archived_at.is_(None),
            WorkforceResource.enterprise_id == work.enterprise_id,
            WorkforceResource.is_active.is_(True),
            scheduled,
        )
    )
    if user.role != "admin":
        current_units = allowed_unit_ids(db, user, work.enterprise_id)
        today = date.today()
        visible_now = exists(
            select(EmploymentAssignment.id).where(
                EmploymentAssignment.resource_id == WorkforceResource.id,
                EmploymentAssignment.enterprise_id == work.enterprise_id,
                EmploymentAssignment.unit_id.in_(current_units),
                EmploymentAssignment.effective_from <= today,
                or_(
                    EmploymentAssignment.effective_to.is_(None),
                    EmploymentAssignment.effective_to >= today,
                ),
            )
        )
        statement = statement.where(visible_now)
    if search:
        pattern = _search_pattern(search)
        full_name = Person.last_name + " " + Person.first_name
        statement = statement.where(or_(
            Person.last_name.ilike(pattern, escape="!"),
            Person.first_name.ilike(pattern, escape="!"),
            Person.middle_name.ilike(pattern, escape="!"),
            Person.employee_code.ilike(pattern, escape="!"),
            full_name.ilike(pattern, escape="!"),
        ))
    return statement


def page_candidates(
    db: Session, user: UserAccount, work: WorkOrder, limit: int,
    after: UUID | None = None, search: str = "",
) -> CandidatePage:
    if work.status not in {"open", "assigned"}:
        return CandidatePage(items=[], next_cursor=None, has_more=False)
    base = candidate_statement(db, user, work, search.strip())
    if after is not None:
        # The anchor must exist within the SAME visible, searched result set.
        # A stale or foreign cursor is rejected without leaking its identity.
        anchor = db.scalar(base.where(Person.id == after))
        if anchor is None:
            raise HTTPException(status_code=422, detail="Invalid candidate cursor")
        base = base.where(or_(
            Person.last_name > anchor.last_name,
            and_(
                Person.last_name == anchor.last_name,
                Person.first_name > anchor.first_name,
            ),
            and_(
                Person.last_name == anchor.last_name,
                Person.first_name == anchor.first_name,
                Person.id > anchor.id,
            ),
        ))
    rows = db.scalars(
        base.order_by(Person.last_name, Person.first_name, Person.id)
        .limit(limit + 1)
    ).all()
    has_more = len(rows) > limit
    persons = rows[:limit]
    return CandidatePage(
        items=[work_service.assess_candidate(db, work, person) for person in persons],
        has_more=has_more,
        next_cursor=persons[-1].id if has_more and persons else None,
    )
