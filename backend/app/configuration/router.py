"""Config-first, governed non-safety person attributes.

Only published versions take effect. All state transitions are explicit,
audited and server-side, and publication needs a second administrator.
"""

from datetime import date, datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.configuration.models import ConfigurationAudit, ConfigVersion, PersonFieldRevision
from app.configuration.schemas import (
    ConfigCreate, ConfigDocument, ConfigView, CustomField, PersonFieldsInput,
    PersonFieldsView, PublishRequest,
)
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import can_read_enterprise
from app.organization.models import Enterprise
from app.personnel.models import Person
from app.personnel.service import require_visible_person

router = APIRouter(
    prefix=f"{settings.api_v1_prefix}/configuration", tags=["configuration"]
)
UTC = timezone.utc


def enterprise_or_404(db: Session, enterprise_id: UUID) -> Enterprise:
    record = db.get(Enterprise, enterprise_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return record


def read_version(db: Session, version_id: UUID) -> ConfigVersion:
    version = db.get(ConfigVersion, version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Configuration not found")
    return version


def view(version: ConfigVersion) -> ConfigView:
    return ConfigView(
        id=version.id, enterprise_id=version.enterprise_id,
        version=version.version, status=version.status,
        document=ConfigDocument.model_validate(version.fields_json),
        created_by=version.created_by, created_at=version.created_at,
        validated_at=version.validated_at,
        approved_by=version.approved_by, approved_at=version.approved_at,
        published_by=version.published_by, published_at=version.published_at,
        effective_on=version.effective_on,
    )


def audit(
    db: Session, user: UserAccount, enterprise_id: UUID,
    action: str, subject_id: UUID, details: dict,
) -> None:
    db.add(ConfigurationAudit(
        enterprise_id=enterprise_id, actor_id=user.id, action=action,
        subject_id=subject_id, details_json=details,
    ))


def commit(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Configuration conflict") from exc


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    db.execute(
        select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update()
    )


def active_version(
    db: Session, enterprise_id: UUID, on: date | None = None,
) -> ConfigVersion | None:
    on = on or datetime.now(UTC).date()
    return db.scalar(
        select(ConfigVersion).where(
            ConfigVersion.enterprise_id == enterprise_id,
            ConfigVersion.status == "published",
            ConfigVersion.effective_on <= on,
        ).order_by(
            ConfigVersion.effective_on.desc(), ConfigVersion.version.desc()
        ).limit(1)
    )


def visible_person(db: Session, user: UserAccount, person_id: UUID) -> Person:
    person = db.get(Person, person_id)
    return require_visible_person(db, user, person)


def validate_value(field: CustomField, value: object) -> str | int | bool | None:
    if value is None or (field.kind == "text" and value == ""):
        if field.required:
            raise HTTPException(status_code=422, detail=f"Required field: {field.code}")
        return None
    if field.kind == "text":
        if not isinstance(value, str) or len(value) > (field.max_length or 120):
            raise HTTPException(status_code=422, detail=f"Invalid text field: {field.code}")
        return value
    if field.kind == "integer":
        if type(value) is not int:
            raise HTTPException(status_code=422, detail=f"Invalid integer field: {field.code}")
        if field.min_value is not None and value < field.min_value:
            raise HTTPException(status_code=422, detail=f"Below minimum: {field.code}")
        if field.max_value is not None and value > field.max_value:
            raise HTTPException(status_code=422, detail=f"Above maximum: {field.code}")
        return value
    if field.kind == "boolean":
        if type(value) is not bool:
            raise HTTPException(status_code=422, detail=f"Invalid boolean field: {field.code}")
        return value
    if not isinstance(value, str) or value not in field.options:
        raise HTTPException(status_code=422, detail=f"Invalid choice field: {field.code}")
    return value


@router.get("/enterprises/{enterprise_id}/versions", response_model=list[ConfigView])
def list_versions(
    enterprise_id: UUID,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[ConfigView]:
    enterprise_or_404(db, enterprise_id)
    rows = db.scalars(select(ConfigVersion).where(
        ConfigVersion.enterprise_id == enterprise_id,
    ).order_by(ConfigVersion.version.desc()).limit(100)).all()
    return [view(row) for row in rows]


@router.get("/enterprises/{enterprise_id}/active", response_model=ConfigView | None)
def get_active(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView | None:
    enterprise_or_404(db, enterprise_id)
    if not can_read_enterprise(db, user, enterprise_id):
        raise HTTPException(status_code=404, detail="Enterprise not found")
    version = active_version(db, enterprise_id)
    return view(version) if version else None


@router.post(
    "/enterprises/{enterprise_id}/versions", status_code=status.HTTP_201_CREATED,
    response_model=ConfigView, dependencies=[Depends(require_csrf)],
)
def create_version(
    enterprise_id: UUID, payload: ConfigCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView:
    enterprise_or_404(db, enterprise_id)
    lock_enterprise(db, enterprise_id)
    number = db.scalar(select(func.max(ConfigVersion.version)).where(
        ConfigVersion.enterprise_id == enterprise_id,
    )) or 0
    row = ConfigVersion(
        enterprise_id=enterprise_id, version=number + 1,
        fields_json=payload.document.model_dump(mode="json"),
        status="draft", created_by=admin.id,
    )
    db.add(row)
    db.flush()
    audit(db, admin, enterprise_id, "configuration.created", row.id, {
        "version": row.version, "codes": [x.code for x in payload.document.fields],
    })
    commit(db)
    db.refresh(row)
    return view(row)


@router.put(
    "/versions/{version_id}", response_model=ConfigView,
    dependencies=[Depends(require_csrf)],
)
def edit_draft(
    version_id: UUID, payload: ConfigCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView:
    row = read_version(db, version_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft can be edited")
    row.fields_json = payload.document.model_dump(mode="json")
    audit(db, admin, row.enterprise_id, "configuration.edited", row.id, {
        "version": row.version, "codes": [x.code for x in payload.document.fields],
    })
    commit(db)
    db.refresh(row)
    return view(row)


@router.post(
    "/versions/{version_id}/validate", response_model=ConfigView,
    dependencies=[Depends(require_csrf)],
)
def validate_draft(
    version_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView:
    row = read_version(db, version_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft can be validated")
    ConfigDocument.model_validate(row.fields_json)
    row.status = "validated"
    row.validated_at = datetime.now(UTC)
    audit(db, admin, row.enterprise_id, "configuration.validated", row.id, {
        "version": row.version,
    })
    commit(db)
    db.refresh(row)
    return view(row)


@router.post(
    "/versions/{version_id}/approve", response_model=ConfigView,
    dependencies=[Depends(require_csrf)],
)
def approve_version(
    version_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView:
    row = read_version(db, version_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row)
    if row.status != "validated":
        raise HTTPException(status_code=409, detail="Configuration must be validated")
    if row.created_by == admin.id:
        raise HTTPException(status_code=403, detail="Independent administrator required")
    row.status = "approved"
    row.approved_by = admin.id
    row.approved_at = datetime.now(UTC)
    audit(db, admin, row.enterprise_id, "configuration.approved", row.id, {
        "version": row.version,
    })
    commit(db)
    db.refresh(row)
    return view(row)


@router.post(
    "/versions/{version_id}/publish", response_model=ConfigView,
    dependencies=[Depends(require_csrf)],
)
def publish_version(
    version_id: UUID, payload: PublishRequest,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> ConfigView:
    row = read_version(db, version_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row)
    if row.status != "approved" or row.approved_by is None:
        raise HTTPException(status_code=409, detail="Independent approval required")
    if payload.effective_on < datetime.now(UTC).date():
        raise HTTPException(status_code=422, detail="Backdated publication is forbidden")
    duplicate = db.scalar(select(ConfigVersion.id).where(
        ConfigVersion.enterprise_id == row.enterprise_id,
        ConfigVersion.status == "published",
        ConfigVersion.effective_on == payload.effective_on,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="Effective date already published")
    row.status = "published"
    row.effective_on = payload.effective_on
    row.published_at = datetime.now(UTC)
    row.published_by = admin.id
    audit(db, admin, row.enterprise_id, "configuration.published", row.id, {
        "version": row.version, "effective_on": str(payload.effective_on),
    })
    commit(db)
    db.refresh(row)
    return view(row)


@router.get("/persons/{person_id}/fields", response_model=PersonFieldsView)
def get_person_fields(
    person_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonFieldsView:
    person = visible_person(db, user, person_id)
    active = active_version(db, person.enterprise_id)
    if active is None:
        return PersonFieldsView(
            person_id=person.id, config_version=None, fields=[], values={},
        )
    document = ConfigDocument.model_validate(active.fields_json)
    revision = db.scalar(select(PersonFieldRevision).where(
        PersonFieldRevision.person_id == person.id,
        PersonFieldRevision.enterprise_id == person.enterprise_id,
    ).order_by(
        PersonFieldRevision.created_at.desc(), PersonFieldRevision.id.desc(),
    ).limit(1))
    values = revision.values_json if revision else {}
    result: dict[str, str | int | bool | None] = {}
    for field in document.fields:
        if field.code not in values:
            continue
        try:
            result[field.code] = validate_value(field, values[field.code])
        except HTTPException:
            # Previously valid values can become obsolete after a schema
            # revision; do not expose invalid or removed values.
            continue
    return PersonFieldsView(
        person_id=person.id, config_version=active.version,
        fields=document.fields, values=result,
    )


@router.put(
    "/persons/{person_id}/fields", response_model=PersonFieldsView,
    dependencies=[Depends(require_csrf)],
)
def set_person_fields(
    person_id: UUID, payload: PersonFieldsInput,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PersonFieldsView:
    person = visible_person(db, admin, person_id)
    if person.archived_at is not None:
        raise HTTPException(status_code=409, detail="Archived person cannot be changed")
    lock_enterprise(db, person.enterprise_id)
    active = active_version(db, person.enterprise_id)
    if active is None:
        raise HTTPException(status_code=409, detail="No effective published schema")
    document = ConfigDocument.model_validate(active.fields_json)
    specs = {field.code: field for field in document.fields}
    if extra := (set(payload.values) - set(specs)):
        raise HTTPException(status_code=422, detail=f"Unknown field: {sorted(extra)[0]}")
    checked = {
        field.code: validate_value(field, payload.values.get(field.code))
        for field in document.fields
    }
    # The total response is deliberately bounded. No arbitrary payload blobs.
    checked = {key: value for key, value in checked.items() if value is not None}
    revision = PersonFieldRevision(
        enterprise_id=person.enterprise_id, person_id=person.id,
        config_version_id=active.id, values_json=checked, changed_by=admin.id,
    )
    db.add(revision)
    db.flush()
    audit(db, admin, person.enterprise_id, "person.fields.updated", person.id, {
        "config_version": active.version, "changed_keys": sorted(checked),
        "revision_id": str(revision.id),
    })
    commit(db)
    return PersonFieldsView(
        person_id=person.id, config_version=active.version,
        fields=document.fields, values=checked,
    )


@router.get("/enterprises/{enterprise_id}/audit", response_model=list[dict])
def list_config_audit(
    enterprise_id: UUID,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict]:
    enterprise_or_404(db, enterprise_id)
    rows = db.scalars(select(ConfigurationAudit).where(
        ConfigurationAudit.enterprise_id == enterprise_id,
    ).order_by(ConfigurationAudit.created_at.desc()).limit(100)).all()
    # No saved personal field values in the audit record.
    return [
        {
            "id": str(row.id), "action": row.action, "subject_id": str(row.subject_id),
            "actor_id": str(row.actor_id),
            "created_at": row.created_at.isoformat(),
            "details": row.details_json,
        }
        for row in rows
    ]
