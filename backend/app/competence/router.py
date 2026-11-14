"""Versioned catalog, submitted assessments, independent review and verified matrix."""

import json
from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids, can_read_enterprise
from app.organization.permissions import can_review_person
from app.organization.models import Enterprise
from app.personnel.models import EmploymentAssignment, Person, WorkforceResource
from app.personnel.service import require_visible_person
from app.competence.models import (
    CompetenceAuditEvent, PersonSkillAssessment, Skill, SkillCategory,
    SkillEvidence, SkillScale, SkillScaleLevel, UserPersonLink,
)
from app.competence.schemas import (
    AssessmentCreate, AssessmentView, AuditView, CategoryCreate, CategoryView,
    EvidenceView, LevelView, LinkCreate, LinkView, OwnLinkView, MatrixRow, ReviewCreate,
    ScaleCreate, ScaleView, SkillCreate, SkillView,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/competence", tags=["competence"])


def flush_safe(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting competence data") from exc


def commit_safe(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting competence data") from exc


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def check_enterprise(db: Session, enterprise_id: UUID, user: UserAccount) -> None:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    linked = db.scalar(
        select(Person.id)
        .join(UserPersonLink, UserPersonLink.person_id == Person.id)
        .where(
            UserPersonLink.user_id == user.id, Person.enterprise_id == enterprise_id,
            Person.archived_at.is_(None),
        )
        .limit(1)
    )
    if not can_read_enterprise(db, user, enterprise_id) and linked is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")


def own_person_id(db: Session, user: UserAccount) -> UUID | None:
    return db.scalar(
        select(UserPersonLink.person_id).where(UserPersonLink.user_id == user.id)
    )


def read_person(db: Session, person_id: UUID, user: UserAccount) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if own_person_id(db, user) == person_id and person.archived_at is None:
        resource = db.scalar(
            select(WorkforceResource.id).where(
                WorkforceResource.person_id == person.id,
                WorkforceResource.is_active.is_(True),
            )
        )
        if resource is not None:
            return person
    return require_visible_person(db, user, person)


def audit(
    db: Session, actor: UserAccount, enterprise_id: UUID, action: str,
    subject_id: UUID, info: dict[str, object],
) -> None:
    db.add(
        CompetenceAuditEvent(
            enterprise_id=enterprise_id, actor_id=actor.id,
            action=action, subject_id=subject_id,
            payload=json.dumps(info, ensure_ascii=False, default=str),
        )
    )


def scale_view(db: Session, scale: SkillScale) -> ScaleView:
    levels = list(
        db.scalars(
            select(SkillScaleLevel)
            .where(SkillScaleLevel.scale_id == scale.id)
            .order_by(SkillScaleLevel.ordinal)
        ).all()
    )
    return ScaleView(
        id=scale.id, enterprise_id=scale.enterprise_id, code=scale.code,
        name=scale.name, version=scale.version,
        levels=[LevelView.model_validate(item) for item in levels],
    )


def assessment_view(db: Session, assessment: PersonSkillAssessment) -> AssessmentView:
    evidence = list(
        db.scalars(
            select(SkillEvidence)
            .where(SkillEvidence.assessment_id == assessment.id)
            .order_by(SkillEvidence.id)
        ).all()
    )
    return AssessmentView(
        id=assessment.id, enterprise_id=assessment.enterprise_id,
        person_id=assessment.person_id, skill_id=assessment.skill_id,
        scale_id=assessment.scale_id, level_id=assessment.level_id,
        source=assessment.source, status=assessment.status,
        submitted_by=assessment.submitted_by, submitted_at=assessment.submitted_at,
        reviewed_by=assessment.reviewed_by, reviewed_at=assessment.reviewed_at,
        review_note=assessment.review_note,
        evidence=[EvidenceView.model_validate(item) for item in evidence],
    )


@router.get("/enterprises/{enterprise_id}/categories", response_model=list[CategoryView])
def list_categories(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[SkillCategory]:
    check_enterprise(db, enterprise_id, user)
    return list(
        db.scalars(
            select(SkillCategory)
            .where(SkillCategory.enterprise_id == enterprise_id)
            .order_by(SkillCategory.name)
        ).all()
    )


@router.post(
    "/enterprises/{enterprise_id}/categories",
    response_model=CategoryView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_category(
    enterprise_id: UUID, payload: CategoryCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SkillCategory:
    check_enterprise(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    if payload.parent_id is not None:
        parent = db.get(SkillCategory, payload.parent_id)
        if parent is None or parent.enterprise_id != enterprise_id:
            raise HTTPException(status_code=422, detail="Invalid parent category")
    record = SkillCategory(
        enterprise_id=enterprise_id, parent_id=payload.parent_id,
        code=payload.code.strip().lower(), name=payload.name.strip(),
    )
    if not record.name:
        raise HTTPException(status_code=422, detail="Category name cannot be blank")
    db.add(record)
    flush_safe(db)
    audit(db, admin, enterprise_id, "category.created", record.id, {"code": record.code})
    commit_safe(db)
    db.refresh(record)
    return record


@router.get("/enterprises/{enterprise_id}/scales", response_model=list[ScaleView])
def list_scales(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ScaleView]:
    check_enterprise(db, enterprise_id, user)
    rows = db.scalars(
        select(SkillScale)
        .where(SkillScale.enterprise_id == enterprise_id)
        .order_by(SkillScale.code, SkillScale.version)
    ).all()
    return [scale_view(db, scale) for scale in rows]


@router.post(
    "/enterprises/{enterprise_id}/scales",
    response_model=ScaleView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_scale(
    enterprise_id: UUID, payload: ScaleCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ScaleView:
    check_enterprise(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    scale = SkillScale(
        enterprise_id=enterprise_id, code=payload.code.lower(),
        name=payload.name.strip(), version=payload.version,
    )
    if not scale.name:
        raise HTTPException(status_code=422, detail="Scale name cannot be blank")
    db.add(scale)
    flush_safe(db)
    for item in payload.levels:
        label = item.label.strip()
        if not label:
            raise HTTPException(status_code=422, detail="Level label cannot be blank")
        db.add(
            SkillScaleLevel(
                scale_id=scale.id, ordinal=item.ordinal, label=label,
                description=item.description,
            )
        )
    flush_safe(db)
    audit(
        db, admin, enterprise_id, "scale.published", scale.id,
        {"code": scale.code, "version": scale.version},
    )
    commit_safe(db)
    return scale_view(db, scale)


@router.get("/enterprises/{enterprise_id}/skills", response_model=list[SkillView])
def list_skills(
    enterprise_id: UUID, include_archived: bool = False,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[Skill]:
    check_enterprise(db, enterprise_id, user)
    query = select(Skill).where(Skill.enterprise_id == enterprise_id)
    if not include_archived:
        query = query.where(Skill.is_active.is_(True))
    return list(db.scalars(query.order_by(Skill.name)).all())


@router.post(
    "/enterprises/{enterprise_id}/skills",
    response_model=SkillView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_skill(
    enterprise_id: UUID, payload: SkillCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Skill:
    check_enterprise(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    category = db.get(SkillCategory, payload.category_id)
    scale = db.get(SkillScale, payload.scale_id)
    if category is None or category.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Category belongs to another enterprise")
    if scale is None or scale.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Scale belongs to another enterprise")
    record = Skill(
        enterprise_id=enterprise_id, category_id=category.id, scale_id=scale.id,
        code=payload.code.lower(), name=payload.name.strip(), is_active=True,
    )
    if not record.name:
        raise HTTPException(status_code=422, detail="Skill name cannot be blank")
    db.add(record)
    flush_safe(db)
    audit(db, admin, enterprise_id, "skill.created", record.id, {"code": record.code})
    commit_safe(db)
    db.refresh(record)
    return record


@router.post(
    "/skills/{skill_id}/archive",
    response_model=SkillView, dependencies=[Depends(require_csrf)],
)
def archive_skill(
    skill_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Skill:
    skill = db.get(Skill, skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    lock_enterprise(db, skill.enterprise_id)
    db.refresh(skill)
    if not skill.is_active:
        raise HTTPException(status_code=409, detail="Skill already archived")
    skill.is_active = False
    audit(db, admin, skill.enterprise_id, "skill.archived", skill.id, {})
    commit_safe(db)
    return skill


@router.get("/links", response_model=list[LinkView])
def list_links(
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[UserPersonLink]:
    return list(db.scalars(select(UserPersonLink).order_by(UserPersonLink.user_id)).all())


@router.get("/me/link", response_model=OwnLinkView | None)
def own_link(
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OwnLinkView | None:
    link = db.get(UserPersonLink, user.id)
    if link is None:
        return None
    person = db.get(Person, link.person_id)
    if person is None or person.archived_at is not None:
        return None
    resource = db.scalar(
        select(WorkforceResource.id)
        .where(WorkforceResource.person_id == person.id, WorkforceResource.is_active.is_(True))
    )
    if resource is None:
        return None
    enterprise = db.get(Enterprise, person.enterprise_id)
    if enterprise is None:
        return None
    return OwnLinkView(
        user_id=user.id, person_id=person.id, enterprise_id=person.enterprise_id,
        enterprise_name=enterprise.name,
    )


@router.post(
    "/links", response_model=LinkView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_link(
    payload: LinkCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserPersonLink:
    person = db.get(Person, payload.person_id)
    user = db.get(UserAccount, payload.user_id)
    if person is None or person.archived_at is not None:
        raise HTTPException(status_code=422, detail="Person must be active")
    if user is None or not user.is_active:
        raise HTTPException(status_code=422, detail="User must be active")
    lock_enterprise(db, person.enterprise_id)
    link = UserPersonLink(
        user_id=user.id, person_id=person.id, linked_by=admin.id,
    )
    db.add(link)
    flush_safe(db)
    audit(
        db, admin, person.enterprise_id, "identity.linked", person.id,
        {"user_id": user.id},
    )
    commit_safe(db)
    return link


def submit_assessment(
    db: Session, user: UserAccount, person_id: UUID,
    payload: AssessmentCreate, source: str,
) -> AssessmentView:
    person = db.get(Person, person_id)
    if person is None or person.archived_at is not None:
        raise HTTPException(status_code=404, detail="Person not found")
    if source == "self":
        if own_person_id(db, user) != person_id:
            raise HTTPException(status_code=403, detail="Person is not linked to your account")
    else:
        if user.role not in {"admin", "manager"}:
            raise HTTPException(status_code=403, detail="Review role required")
        require_visible_person(db, user, person)

    skill = db.get(Skill, payload.skill_id)
    if skill is None or skill.enterprise_id != person.enterprise_id or not skill.is_active:
        raise HTTPException(status_code=422, detail="Skill is not active in this enterprise")
    level = db.get(SkillScaleLevel, payload.level_id)
    if level is None or level.scale_id != skill.scale_id:
        raise HTTPException(status_code=422, detail="Level does not belong to skill scale")
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person_id)
    )
    if resource is None or not resource.is_active:
        raise HTTPException(status_code=409, detail="Workforce resource is inactive")

    lock_enterprise(db, person.enterprise_id)
    record = PersonSkillAssessment(
        enterprise_id=person.enterprise_id, person_id=person.id,
        skill_id=skill.id, scale_id=skill.scale_id, level_id=level.id,
        source=source, status="pending", submitted_by=user.id,
    )
    db.add(record)
    flush_safe(db)
    for item in payload.evidence:
        db.add(
            SkillEvidence(
                assessment_id=record.id, kind=item.kind,
                description=item.description.strip(),
                reference=item.reference,
            )
        )
    flush_safe(db)
    audit(
        db, user, person.enterprise_id, "assessment.submitted", record.id,
        {"source": source, "person_id": person.id, "skill_id": skill.id},
    )
    commit_safe(db)
    db.refresh(record)
    return assessment_view(db, record)


@router.post(
    "/persons/{person_id}/self-assessments",
    response_model=AssessmentView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def self_assessment(
    person_id: UUID, payload: AssessmentCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssessmentView:
    return submit_assessment(db, user, person_id, payload, "self")


@router.post(
    "/persons/{person_id}/expert-assessments",
    response_model=AssessmentView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def expert_assessment(
    person_id: UUID, payload: AssessmentCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssessmentView:
    return submit_assessment(db, user, person_id, payload, "expert")


@router.get("/persons/{person_id}/assessments", response_model=list[AssessmentView])
def list_assessments(
    person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AssessmentView]:
    person = read_person(db, person_id, user)
    query = select(PersonSkillAssessment).where(PersonSkillAssessment.person_id == person.id)
    if (
        user.role == "viewer"
        and own_person_id(db, user) != person.id
        and not can_review_person(db, user, person, "competence.assessment.review")
    ):
        query = query.where(PersonSkillAssessment.status == "approved")
    rows = db.scalars(
        query.order_by(PersonSkillAssessment.submitted_at.desc()).limit(100)
    ).all()
    return [assessment_view(db, item) for item in rows]


@router.post(
    "/assessments/{assessment_id}/review",
    response_model=AssessmentView,
    dependencies=[Depends(require_csrf)],
)
def review_assessment(
    assessment_id: UUID, payload: ReviewCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssessmentView:
    record = db.get(PersonSkillAssessment, assessment_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Assessment not found")
    person = db.get(Person, record.person_id)
    if person is None or person.archived_at is not None:
        raise HTTPException(status_code=404, detail="Person not found")
    if not can_review_person(db, user, person, "competence.assessment.review"):
        raise HTTPException(status_code=403, detail="Assessment review permission required")
    require_visible_person(db, user, person)
    if own_person_id(db, user) == record.person_id:
        raise HTTPException(status_code=403, detail="Self-review is forbidden")
    lock_enterprise(db, record.enterprise_id)
    db.refresh(record, with_for_update=True)
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="Assessment has already been reviewed")
    if record.submitted_by == user.id:
        raise HTTPException(status_code=403, detail="Creator cannot review own assessment")
    if payload.decision == "approved":
        evidence_exists = db.scalar(
            select(SkillEvidence.id)
            .where(SkillEvidence.assessment_id == record.id).limit(1)
        )
        if evidence_exists is None:
            raise HTTPException(status_code=422, detail="Approval requires evidence")
        skill = db.get(Skill, record.skill_id)
        if skill is None or not skill.is_active:
            raise HTTPException(status_code=409, detail="Skill is archived")
    record.status = payload.decision
    record.review_note = payload.note.strip()
    record.reviewed_by = user.id
    record.reviewed_at = datetime.now(timezone.utc)
    audit(
        db, user, record.enterprise_id, "assessment.reviewed", record.id,
        {"decision": record.status, "person_id": record.person_id, "skill_id": record.skill_id},
    )
    commit_safe(db)
    db.refresh(record)
    return assessment_view(db, record)


@router.get("/enterprises/{enterprise_id}/matrix", response_model=list[MatrixRow])
def verified_matrix(
    enterprise_id: UUID,
    skill_id: UUID | None = None,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[MatrixRow]:
    check_enterprise(db, enterprise_id, user)
    stmt = (
        select(PersonSkillAssessment, Person, Skill, SkillScaleLevel)
        .join(Person, Person.id == PersonSkillAssessment.person_id)
        .join(Skill, Skill.id == PersonSkillAssessment.skill_id)
        .join(SkillScaleLevel, SkillScaleLevel.id == PersonSkillAssessment.level_id)
        .where(
            PersonSkillAssessment.enterprise_id == enterprise_id,
            PersonSkillAssessment.status == "approved",
            Person.archived_at.is_(None),
            Skill.is_active.is_(True),
        )
    )
    if skill_id is not None:
        stmt = stmt.where(PersonSkillAssessment.skill_id == skill_id)
    if user.role != "admin":
        permitted = allowed_unit_ids(db, user, enterprise_id)
        own_id = own_person_id(db, user)
        subquery = (
            select(EmploymentAssignment.id)
            .join(WorkforceResource, WorkforceResource.id == EmploymentAssignment.resource_id)
            .where(
                WorkforceResource.person_id == Person.id,
                WorkforceResource.is_active.is_(True),
                EmploymentAssignment.unit_id.in_(permitted),
                EmploymentAssignment.effective_from <= date.today(),
                or_(
                    EmploymentAssignment.effective_to.is_(None),
                    EmploymentAssignment.effective_to >= date.today(),
                ),
            )
        )
        if own_id is not None:
            stmt = stmt.where(or_(Person.id == own_id, exists(subquery)))
        else:
            stmt = stmt.where(exists(subquery))
    rows = db.execute(
        stmt.order_by(
            PersonSkillAssessment.reviewed_at.desc(),
            PersonSkillAssessment.id.desc(),
        ).limit(1000)
    ).all()
    result: list[MatrixRow] = []
    seen: set[tuple[UUID, UUID]] = set()
    for row, person, skill, level in rows:
        key = (row.person_id, row.skill_id)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            MatrixRow(
                person_id=person.id, employee_code=person.employee_code,
                full_name=f"{person.last_name} {person.first_name}",
                skill_id=skill.id, skill_code=skill.code, skill_name=skill.name,
                level_id=level.id, level_label=level.label,
                level_ordinal=level.ordinal, reviewed_at=row.reviewed_at,
            )
        )
        if len(result) >= 200:
            break
    return result


@router.get("/audit", response_model=list[AuditView])
def list_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CompetenceAuditEvent]:
    stmt = select(CompetenceAuditEvent).order_by(CompetenceAuditEvent.created_at.desc())
    if enterprise_id is not None:
        stmt = stmt.where(CompetenceAuditEvent.enterprise_id == enterprise_id)
    return list(db.scalars(stmt.limit(100)).all())
