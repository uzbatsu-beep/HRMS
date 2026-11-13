"""Explainable work matching across skills, credentials, availability and organization."""

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.availability.models import ShiftRule
from app.availability.service import as_utc, evaluate
from app.competence.models import PersonSkillAssessment, Skill, SkillScaleLevel
from app.credentials.service import evaluate_activity
from app.identity.models import UserAccount
from app.organization.models import Enterprise
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import current_assignment
from app.work.models import WorkAuditEvent, WorkCrewMember, WorkOrder, WorkSkillRequirement
from app.work.schemas import Blocker, CandidateView, CrewMemberView, RequiredSkillView, WorkView, AssignmentView
from app.work.models import WorkOrderAssignment

UTC = timezone.utc


def utcnow() -> datetime:
    return datetime.now(UTC)


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def flush_safe(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting work order data") from exc


def commit_safe(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting work order data") from exc


def audit(
    db: Session, user: UserAccount, work: WorkOrder, action: str, details: dict[str, object]
) -> None:
    db.add(
        WorkAuditEvent(
            enterprise_id=work.enterprise_id, actor_user_id=user.id,
            work_order_id=work.id, action=action,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
        )
    )


def relevant_dates(db: Session, resource_id: UUID, start: datetime, end: datetime) -> set:
    """Check both UTC and relevant plant local dates to avoid midnight expiry gaps."""
    start, end = as_utc(start), as_utc(end)
    last = end - timedelta(microseconds=1)
    dates = {start.date(), last.date()}
    rules = db.scalars(select(ShiftRule).where(
        ShiftRule.resource_id == resource_id, ShiftRule.disabled_at.is_(None)
    )).all()
    for rule in rules:
        zone = ZoneInfo(rule.time_zone)
        dates.add(start.astimezone(zone).date())
        dates.add(last.astimezone(zone).date())
    return dates


def assess_candidate(
    db: Session, work: WorkOrder, person: Person,
    exclude_reservation_id: UUID | None = None,
) -> CandidateView:
    blockers: list[Blocker] = []
    verified_skills: list[UUID] = []
    credential_ids: set[UUID] = set()
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person.id)
    )

    def block(source: str, code: str, message: str) -> None:
        blockers.append(Blocker(source=source, code=code, message=message))

    if person.enterprise_id != work.enterprise_id:
        block("person", "WRONG_ENTERPRISE", "Person is outside the work enterprise")
    if person.archived_at is not None or resource is None or not resource.is_active:
        block("person", "INACTIVE_PERSON", "Person or resource is inactive")

    start, end = as_utc(work.starts_at), as_utc(work.ends_at)
    if resource is not None and person.enterprise_id == work.enterprise_id:
        unit_ids: set[UUID] = set()
        for on in sorted(relevant_dates(db, resource.id, start, end)):
            assignment = current_assignment(db, resource.id, on)
            if assignment is None:
                block("organization", "NO_ASSIGNMENT", "No active primary assignment")
                break
            unit_ids.add(assignment.unit_id)
        if unit_ids and unit_ids != {work.unit_id}:
            block(
                "organization", "WRONG_WORK_UNIT",
                "Person's primary department does not match the work order",
            )

    requirements = list(db.scalars(select(WorkSkillRequirement).where(
        WorkSkillRequirement.work_order_id == work.id
    )).all())
    if not requirements:
        block("skill", "NO_REQUIRED_SKILLS", "Work has no fixed technical skill requirements")
    for requirement in requirements:
        skill = db.get(Skill, requirement.skill_id)
        threshold = db.get(SkillScaleLevel, requirement.min_level_id)
        if (
            skill is None or not skill.is_active or skill.enterprise_id != work.enterprise_id
            or skill.scale_id != requirement.scale_id or threshold is None
            or threshold.scale_id != requirement.scale_id
        ):
            block("skill", "INVALID_SKILL_POLICY", "Required skill is inactive or inconsistent")
            continue
        approvals = db.scalars(
            select(PersonSkillAssessment)
            .where(
                PersonSkillAssessment.enterprise_id == work.enterprise_id,
                PersonSkillAssessment.person_id == person.id,
                PersonSkillAssessment.skill_id == skill.id,
                PersonSkillAssessment.status == "approved",
            )
            .order_by(
                PersonSkillAssessment.reviewed_at.desc(),
                PersonSkillAssessment.id.desc(),
            )
            .limit(1)
        ).all()
        if not approvals:
            block("skill", "MISSING_VERIFIED_SKILL", f"No approved level for '{skill.code}'")
            continue
        rated = db.get(SkillScaleLevel, approvals[0].level_id)
        if rated is None or rated.scale_id != requirement.scale_id:
            block("skill", "INVALID_SKILL_RATING", f"Invalid approved rating for '{skill.code}'")
        elif rated.ordinal < threshold.ordinal:
            block(
                "skill", "INSUFFICIENT_SKILL_LEVEL",
                f"Approved '{skill.code}' level {rated.ordinal} < required {threshold.ordinal}",
            )
        else:
            verified_skills.append(skill.id)

    if person.enterprise_id == work.enterprise_id:
        # Independent mandatory credential policy is enforced on all relevant
        # date boundaries, not just the first day of a multi-day overnight shift.
        if resource is None:
            block("credential", "NO_RESOURCE", "No assignable resource")
        else:
            for on in sorted(relevant_dates(db, resource.id, start, end)):
                check = evaluate_activity(db, person, work.activity_code, on)
                for failure in check.blockers:
                    block("credential", failure.code, f"{on.isoformat()}: {failure.message}")
                for proof in check.valid_credentials:
                    credential_ids.add(proof.credential_id)

    if resource is not None and person.enterprise_id == work.enterprise_id:
        calendar = evaluate(
            db, person, resource, start, end,
            exclude_reservation_id=exclude_reservation_id,
        )
        for failure in calendar.blockers:
            block("calendar", failure.code, failure.message)

    # No implicit pass for an unconfigured, unstaffed or malformed work order.
    return CandidateView(
        person_id=person.id, employee_code=person.employee_code,
        full_name=f"{person.last_name} {person.first_name}",
        resource_id=resource.id if resource else None,
        eligible=not blockers, blockers=blockers,
        verified_skills=verified_skills,
        verified_credentials=sorted(credential_ids, key=str),
    )


def view_work(db: Session, work: WorkOrder) -> WorkView:
    requirement_rows = list(db.scalars(select(WorkSkillRequirement).where(
        WorkSkillRequirement.work_order_id == work.id
    ).order_by(WorkSkillRequirement.skill_id)).all())
    requirements: list[RequiredSkillView] = []
    for item in requirement_rows:
        skill = db.get(Skill, item.skill_id)
        level = db.get(SkillScaleLevel, item.min_level_id)
        requirements.append(
            RequiredSkillView(
                id=item.id, skill_id=item.skill_id, scale_id=item.scale_id,
                min_level_id=item.min_level_id, min_ordinal=level.ordinal if level else -1,
                skill_name=skill.name if skill else "Archived/missing skill",
            )
        )
    assignment = db.scalar(select(WorkOrderAssignment).where(
        WorkOrderAssignment.work_order_id == work.id
    ))
    crew_rows = list(db.scalars(select(WorkCrewMember).where(
        WorkCrewMember.work_order_id == work.id
    ).order_by(WorkCrewMember.joined_at, WorkCrewMember.id)).all())
    crew = [
        CrewMemberView(
            id=item.id, person_id=item.person_id,
            resource_id=item.resource_id, reservation_id=item.reservation_id,
            role=item.role, joined_at=as_utc(item.joined_at),
            removed_at=as_utc(item.removed_at) if item.removed_at else None,
        )
        for item in crew_rows
    ]
    return WorkView(
        id=work.id, enterprise_id=work.enterprise_id, unit_id=work.unit_id,
        code=work.code, title=work.title, description=work.description,
        activity_code=work.activity_code, starts_at=as_utc(work.starts_at),
        ends_at=as_utc(work.ends_at), status=work.status,
        created_at=as_utc(work.created_at),
        started_at=as_utc(work.started_at) if work.started_at else None,
        completed_at=as_utc(work.completed_at) if work.completed_at else None,
        cancelled_at=as_utc(work.cancelled_at) if work.cancelled_at else None,
        required_skills=requirements,
        assignment=AssignmentView(
            id=assignment.id, person_id=assignment.person_id,
            resource_id=assignment.resource_id, reservation_id=assignment.reservation_id,
            assigned_at=as_utc(assignment.assigned_at),
        ) if assignment else None,
        priority=work.priority, crew=crew,
        on_hold_at=as_utc(work.on_hold_at) if work.on_hold_at else None,
        hold_reason=work.hold_reason,
        last_safety_check_at=(
            as_utc(work.last_safety_check_at) if work.last_safety_check_at else None
        ),
    )
