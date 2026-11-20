"""Credential administration, independent verification and scoped eligibility checks."""

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.credentials.models import (
    CredentialAuditEvent, CredentialRequirement, CredentialType, PersonCredential,
)
from app.credentials.schemas import (
    AuditView, CredentialCreate, CredentialReview, CredentialRevoke,
    CredentialTypeCreate, CredentialTypeView, CredentialView, EligibilityResult,
    RequirementCreate, RequirementView,
)
from app.credentials.service import (
    audit, commit_safe, evaluate_activity, flush_safe, lock_enterprise,
)
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import can_read_enterprise
from app.organization.permissions import can, can_review_person
from app.organization.models import Enterprise, OrganizationUnit
from app.personnel.models import Person, WorkforceResource
from app.personnel.service import current_assignment, require_visible_person
from app.privacy.service import record_personal_data_read
from app.competence.models import UserPersonLink

router = APIRouter(prefix=f"{settings.api_v1_prefix}/credentials", tags=["credentials"])


def person_or_404(db: Session, person_id: UUID, user: UserAccount) -> Person:
    person = db.get(Person, person_id)
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if user.role != "admin":
        linked = db.scalar(
            select(UserPersonLink.person_id).where(UserPersonLink.user_id == user.id)
        )
        resource = db.scalar(
            select(WorkforceResource).where(WorkforceResource.person_id == person.id)
        )
        if (
            linked != person.id or person.archived_at is not None
            or resource is None or not resource.is_active
        ):
            return require_visible_person(db, user, person)
    return person


def enterprise_or_404(db: Session, enterprise_id: UUID, user: UserAccount) -> None:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    linked = db.scalar(
        select(Person.id).join(
            UserPersonLink, UserPersonLink.person_id == Person.id
        ).where(
            UserPersonLink.user_id == user.id,
            Person.enterprise_id == enterprise_id,
            Person.archived_at.is_(None),
        )
    )
    if not can_read_enterprise(db, user, enterprise_id) and linked is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")


def may_read_private_document(
    db: Session, user: UserAccount, person: Person,
) -> bool:
    """Explicit, exact-unit read grant; review rights do not imply document disclosure."""
    if user.role == "admin":
        return True
    resource = db.scalar(select(WorkforceResource).where(
        WorkforceResource.person_id == person.id,
        WorkforceResource.enterprise_id == person.enterprise_id,
        WorkforceResource.is_active.is_(True),
    ))
    if resource is None:
        return False
    assignment = current_assignment(db, resource.id)
    if assignment is None or assignment.enterprise_id != person.enterprise_id:
        return False
    unit = db.get(OrganizationUnit, assignment.unit_id)
    return bool(unit and can(
        db, user, unit, "credentials.record.read_sensitive",
    ))


def credential_for_reader(row: PersonCredential, private: bool) -> CredentialView:
    view = CredentialView.model_validate(row)
    if private:
        return view
    return view.model_copy(update={
        "document_reference": None, "issuer": None,
        "review_note": None, "revoke_reason": None,
        "submitted_by": None, "reviewed_by": None, "revoked_by": None,
    })


@router.get("/enterprises/{enterprise_id}/types", response_model=list[CredentialTypeView])
def list_types(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CredentialType]:
    enterprise_or_404(db, enterprise_id, user)
    return list(db.scalars(
        select(CredentialType)
        .where(CredentialType.enterprise_id == enterprise_id)
        .order_by(CredentialType.name)
    ).all())


@router.post(
    "/enterprises/{enterprise_id}/types",
    response_model=CredentialTypeView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_type(
    enterprise_id: UUID, payload: CredentialTypeCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CredentialType:
    enterprise_or_404(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Type name cannot be blank")
    record = CredentialType(
        enterprise_id=enterprise_id, code=payload.code.lower(), name=name,
        kind=payload.kind, requires_expiry=payload.requires_expiry,
        is_safety_critical=payload.is_safety_critical,
    )
    db.add(record)
    flush_safe(db)
    audit(db, admin, enterprise_id, "type.created", record.id, {
        "code": record.code, "safety": record.is_safety_critical,
        "requires_expiry": record.requires_expiry,
    })
    commit_safe(db)
    db.refresh(record)
    return record


@router.get(
    "/enterprises/{enterprise_id}/requirements",
    response_model=list[RequirementView],
)
def list_requirements(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CredentialRequirement]:
    enterprise_or_404(db, enterprise_id, user)
    return list(db.scalars(
        select(CredentialRequirement)
        .where(CredentialRequirement.enterprise_id == enterprise_id)
        .order_by(CredentialRequirement.activity_code)
    ).all())


@router.post(
    "/enterprises/{enterprise_id}/requirements",
    response_model=RequirementView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_requirement(
    enterprise_id: UUID, payload: RequirementCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CredentialRequirement:
    enterprise_or_404(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    kind = db.get(CredentialType, payload.type_id)
    if kind is None or kind.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Credential type belongs to another enterprise")
    record = CredentialRequirement(
        enterprise_id=enterprise_id,
        activity_code=payload.activity_code.lower(),
        type_id=kind.id,
    )
    db.add(record)
    flush_safe(db)
    audit(db, admin, enterprise_id, "requirement.created", record.id, {
        "activity_code": record.activity_code, "type_id": kind.id,
    })
    commit_safe(db)
    db.refresh(record)
    return record


@router.get("/persons/{person_id}", response_model=list[CredentialView])
def list_person_credentials(
    person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[CredentialView]:
    person = person_or_404(db, person_id, user)
    rows = list(db.scalars(
        select(PersonCredential)
        .where(PersonCredential.person_id == person_id)
        .order_by(PersonCredential.submitted_at.desc())
        .limit(100)
    ).all())
    private = may_read_private_document(db, user, person)
    views = [credential_for_reader(row, private) for row in rows]
    record_personal_data_read(
        db, user, person.enterprise_id, "credentials.list", person_id=person.id,
        count=len(views),
    )
    return views


@router.post(
    "/enterprises/{enterprise_id}/records",
    response_model=CredentialView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def submit_record(
    enterprise_id: UUID, payload: CredentialCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonCredential:
    enterprise_or_404(db, enterprise_id, admin)
    lock_enterprise(db, enterprise_id)
    person = db.get(Person, payload.person_id)
    kind = db.get(CredentialType, payload.type_id)
    if person is None or person.enterprise_id != enterprise_id or person.archived_at is not None:
        raise HTTPException(status_code=422, detail="Person is missing or inactive")
    resource = db.scalar(
        select(WorkforceResource)
        .where(WorkforceResource.person_id == person.id)
    )
    if resource is None or not resource.is_active:
        raise HTTPException(status_code=422, detail="Resource is inactive")
    if kind is None or kind.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Credential type is from another enterprise")
    if kind.requires_expiry and payload.expires_on is None:
        raise HTTPException(status_code=422, detail="Expiration is mandatory for this type")
    if payload.issued_on > date.today():
        raise HTTPException(status_code=422, detail="Issuance date cannot be in the future")
    reference = payload.document_reference.strip()
    issuer = payload.issuer.strip()
    if not reference or not issuer:
        raise HTTPException(status_code=422, detail="Document reference and issuer are required")
    record = PersonCredential(
        enterprise_id=enterprise_id, person_id=person.id, type_id=kind.id,
        document_reference=reference, issuer=issuer, issued_on=payload.issued_on,
        valid_from=payload.valid_from, expires_on=payload.expires_on,
        submitted_by=admin.id, status="pending",
    )
    db.add(record)
    flush_safe(db)
    audit(db, admin, enterprise_id, "credential.submitted", record.id, {
        "person_id": person.id, "type_id": kind.id,
        "expires_on": record.expires_on, "status": record.status,
    })
    commit_safe(db)
    db.refresh(record)
    return record


@router.post(
    "/records/{record_id}/review",
    response_model=CredentialView,
    dependencies=[Depends(require_csrf)],
)
def review_record(
    record_id: UUID, payload: CredentialReview,
    reviewer: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CredentialView:
    record = db.get(PersonCredential, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    # Serialize with personnel transfers and re-check current scope after locking.
    lock_enterprise(db, record.enterprise_id)
    db.refresh(record, with_for_update=True)
    person = db.get(Person, record.person_id)
    if person is None:
        raise HTTPException(status_code=409, detail="Person no longer exists")
    db.refresh(person)
    if person.archived_at is not None:
        raise HTTPException(status_code=409, detail="Person is archived")
    if not can_review_person(db, reviewer, person, "credentials.record.review"):
        raise HTTPException(status_code=403, detail="Credential review permission required")
    resource = db.scalar(
        select(WorkforceResource).where(WorkforceResource.person_id == person.id)
    )
    if resource is None:
        raise HTTPException(status_code=409, detail="Resource no longer exists")
    db.refresh(resource)
    if not resource.is_active:
        raise HTTPException(status_code=409, detail="Resource is inactive")
    require_visible_person(db, reviewer, person)
    if record.submitted_by == reviewer.id:
        raise HTTPException(status_code=403, detail="Submitter cannot review their record")
    linked = db.scalar(
        select(UserPersonLink.person_id)
        .where(UserPersonLink.user_id == reviewer.id)
    )
    if linked == person.id:
        raise HTTPException(status_code=403, detail="Own credential cannot be approved")
    if record.status != "pending":
        raise HTTPException(status_code=409, detail="Credential has already been reviewed")
    if payload.decision == "verified":
        kind = db.get(CredentialType, record.type_id)
        if kind is None or (kind.requires_expiry and record.expires_on is None):
            raise HTTPException(status_code=409, detail="Document validity data is incomplete")
        if record.expires_on is not None and record.expires_on < date.today():
            raise HTTPException(status_code=409, detail="Expired document cannot be verified")
    record.status = payload.decision
    record.reviewed_by = reviewer.id
    record.reviewed_at = datetime.now(timezone.utc)
    record.review_note = payload.note.strip()
    audit(db, reviewer, record.enterprise_id, "credential.reviewed", record.id, {
        "person_id": person.id, "decision": record.status,
    })
    commit_safe(db)
    db.refresh(record)
    return credential_for_reader(record, may_read_private_document(db, reviewer, person))


@router.post(
    "/records/{record_id}/revoke",
    response_model=CredentialView,
    dependencies=[Depends(require_csrf)],
)
def revoke_record(
    record_id: UUID, payload: CredentialRevoke,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonCredential:
    record = db.get(PersonCredential, record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Credential not found")
    lock_enterprise(db, record.enterprise_id)
    db.refresh(record, with_for_update=True)
    if record.status != "verified":
        raise HTTPException(status_code=409, detail="Only verified credentials can be revoked")
    record.status = "revoked"
    record.revoked_by = admin.id
    record.revoked_at = datetime.now(timezone.utc)
    record.revoke_reason = payload.reason.strip()
    audit(db, admin, record.enterprise_id, "credential.revoked", record.id, {
        "person_id": record.person_id, "status": record.status,
    })
    commit_safe(db)
    db.refresh(record)
    return record


@router.get(
    "/persons/{person_id}/eligibility/{activity_code}",
    response_model=EligibilityResult,
)
def check_eligibility(
    person_id: UUID, activity_code: str,
    on: date | None = None,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> EligibilityResult:
    if not activity_code or len(activity_code) > 64 or not all(
        char.isascii() and (char.isalnum() or char in "_.-") for char in activity_code
    ):
        raise HTTPException(status_code=422, detail="Invalid activity code")
    person = person_or_404(db, person_id, user)
    result = evaluate_activity(db, person, activity_code.lower(), on)
    record_personal_data_read(
        db, user, person.enterprise_id, "credentials.eligibility", person_id=person.id,
        count=1,
    )
    return result


@router.get("/audit", response_model=list[AuditView])
def list_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AuditView]:
    stmt = select(CredentialAuditEvent).order_by(
        CredentialAuditEvent.created_at.desc()
    )
    if enterprise_id is not None:
        stmt = stmt.where(CredentialAuditEvent.enterprise_id == enterprise_id)
    rows = db.scalars(stmt.limit(100)).all()
    # Legacy revocation audit entries could contain free-text reasons.
    return [
        AuditView.model_validate(row).model_copy(update={"details_json": "{}"})
        if row.action == "credential.revoked"
        else AuditView.model_validate(row)
        for row in rows
    ]
