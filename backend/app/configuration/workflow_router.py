"""Governed, typed, non-safety service-request workflows.

This API never changes WorkOrder, WorkPermit or the authorization/qualification gates.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.configuration.router import (
    audit, commit, enterprise_or_404, lock_enterprise,
)
from app.configuration.workflow_models import (
    WorkflowCaseEvent, WorkflowDefinitionVersion, WorkflowServiceCase,
)
from app.configuration.workflow_schemas import (
    WorkflowCaseCreate, WorkflowCaseEventView, WorkflowCaseView,
    WorkflowDefinitionCreate, WorkflowDocument, WorkflowMove, WorkflowPublish,
    WorkflowVersionView,
)
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids, can_read_enterprise
from app.organization.models import OrganizationUnit

router = APIRouter(
    prefix=f"{settings.api_v1_prefix}/configuration", tags=["workflow configuration"],
)


def view_version(row: WorkflowDefinitionVersion) -> WorkflowVersionView:
    return WorkflowVersionView(
        id=row.id, enterprise_id=row.enterprise_id, code=row.code,
        title=row.title, version=row.version, status=row.status,
        document=WorkflowDocument.model_validate(row.document_json),
        created_by=row.created_by, created_at=row.created_at,
        approved_by=row.approved_by, published_by=row.published_by,
        effective_on=row.effective_on,
    )


def get_version(db: Session, version_id: UUID) -> WorkflowDefinitionVersion:
    row = db.get(WorkflowDefinitionVersion, version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    return row


def active_versions(db: Session, enterprise_id: UUID) -> list[WorkflowDefinitionVersion]:
    today = datetime.now(timezone.utc).date()
    versions = db.scalars(
        select(WorkflowDefinitionVersion).where(
            WorkflowDefinitionVersion.enterprise_id == enterprise_id,
            WorkflowDefinitionVersion.status == "published",
            WorkflowDefinitionVersion.effective_on <= today,
        ).order_by(
            WorkflowDefinitionVersion.code,
            WorkflowDefinitionVersion.effective_on.desc(),
            WorkflowDefinitionVersion.version.desc(),
        )
    ).all()
    unique: dict[str, WorkflowDefinitionVersion] = {}
    for row in versions:
        unique.setdefault(row.code, row)
    return list(unique.values())


def require_unit(
    db: Session, user: UserAccount, enterprise_id: UUID, unit_id: UUID,
) -> OrganizationUnit:
    unit = db.get(OrganizationUnit, unit_id)
    if unit is None or unit.enterprise_id != enterprise_id:
        raise HTTPException(status_code=404, detail="Service request not found")
    if user.role != "admin" and unit_id not in allowed_unit_ids(db, user, enterprise_id):
        raise HTTPException(status_code=404, detail="Service request not found")
    return unit


def visible_case(db: Session, user: UserAccount, case_id: UUID) -> WorkflowServiceCase:
    case = db.get(WorkflowServiceCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Service request not found")
    require_unit(db, user, case.enterprise_id, case.unit_id)
    return case


def view_case(db: Session, row: WorkflowServiceCase) -> WorkflowCaseView:
    version = db.get(WorkflowDefinitionVersion, row.definition_id)
    if version is None:
        raise HTTPException(status_code=409, detail="Workflow definition missing")
    return WorkflowCaseView(
        id=row.id, enterprise_id=row.enterprise_id, unit_id=row.unit_id,
        workflow_code=version.code, workflow_version=version.version,
        title=row.title, state=row.state, values=row.values_json,
        created_by=row.created_by, created_at=row.created_at, updated_at=row.updated_at,
    )


@router.get(
    "/enterprises/{enterprise_id}/workflow-versions",
    response_model=list[WorkflowVersionView],
)
def list_workflow_versions(
    enterprise_id: UUID,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkflowVersionView]:
    enterprise_or_404(db, enterprise_id)
    rows = db.scalars(select(WorkflowDefinitionVersion).where(
        WorkflowDefinitionVersion.enterprise_id == enterprise_id,
    ).order_by(
        WorkflowDefinitionVersion.created_at.desc(),
        WorkflowDefinitionVersion.version.desc(),
    ).limit(100)).all()
    return [view_version(row) for row in rows]


@router.get(
    "/enterprises/{enterprise_id}/workflows/active",
    response_model=list[WorkflowVersionView],
)
def get_active_workflows(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkflowVersionView]:
    enterprise_or_404(db, enterprise_id)
    if not can_read_enterprise(db, user, enterprise_id):
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return [view_version(row) for row in active_versions(db, enterprise_id)]


@router.post(
    "/enterprises/{enterprise_id}/workflow-versions",
    status_code=status.HTTP_201_CREATED,
    response_model=WorkflowVersionView,
    dependencies=[Depends(require_csrf)],
)
def create_workflow_version(
    enterprise_id: UUID, payload: WorkflowDefinitionCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    enterprise_or_404(db, enterprise_id)
    lock_enterprise(db, enterprise_id)
    latest = db.scalar(select(func.max(WorkflowDefinitionVersion.version)).where(
        WorkflowDefinitionVersion.enterprise_id == enterprise_id,
        WorkflowDefinitionVersion.code == payload.code,
    )) or 0
    version = WorkflowDefinitionVersion(
        enterprise_id=enterprise_id, code=payload.code, title=payload.title,
        version=latest + 1, document_json=payload.document.model_dump(mode="json"),
        status="draft", created_by=admin.id,
    )
    db.add(version)
    db.flush()
    audit(db, admin, enterprise_id, "workflow.created", version.id, {
        "code": version.code, "version": version.version,
    })
    commit(db)
    db.refresh(version)
    return view_version(version)


@router.put(
    "/workflow-versions/{version_id}", response_model=WorkflowVersionView,
    dependencies=[Depends(require_csrf)],
)
def edit_workflow_version(
    version_id: UUID, payload: WorkflowDefinitionCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    version = get_version(db, version_id)
    lock_enterprise(db, version.enterprise_id)
    db.refresh(version)
    if version.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft can be edited")
    if payload.code != version.code:
        raise HTTPException(status_code=409, detail="Workflow code is immutable")
    version.title = payload.title
    version.document_json = payload.document.model_dump(mode="json")
    audit(db, admin, version.enterprise_id, "workflow.edited", version.id, {
        "code": version.code, "version": version.version,
    })
    commit(db)
    db.refresh(version)
    return view_version(version)


def locked_workflow_version(db: Session, version_id: UUID) -> WorkflowDefinitionVersion:
    row = get_version(db, version_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row, with_for_update=True)
    return row


@router.post(
    "/workflow-versions/{version_id}/validate", response_model=WorkflowVersionView,
    dependencies=[Depends(require_csrf)],
)
def validate_workflow_version(
    version_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    row = locked_workflow_version(db, version_id)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft can be validated")
    WorkflowDocument.model_validate(row.document_json)
    row.status = "validated"
    audit(db, admin, row.enterprise_id, "workflow.validated", row.id, {})
    commit(db)
    db.refresh(row)
    return view_version(row)


@router.post(
    "/workflow-versions/{version_id}/approve", response_model=WorkflowVersionView,
    dependencies=[Depends(require_csrf)],
)
def approve_workflow_version(
    version_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    row = locked_workflow_version(db, version_id)
    if row.status != "validated":
        raise HTTPException(status_code=409, detail="Workflow must be validated")
    if row.created_by == admin.id:
        raise HTTPException(status_code=403, detail="Independent administrator required")
    row.status = "approved"
    row.approved_by = admin.id
    audit(db, admin, row.enterprise_id, "workflow.approved", row.id, {})
    commit(db)
    db.refresh(row)
    return view_version(row)


@router.post(
    "/workflow-versions/{version_id}/publish", response_model=WorkflowVersionView,
    dependencies=[Depends(require_csrf)],
)
def publish_workflow_version(
    version_id: UUID, payload: WorkflowPublish,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    row = locked_workflow_version(db, version_id)
    if row.status != "approved" or row.approved_by is None:
        raise HTTPException(status_code=409, detail="Independent approval required")
    if payload.effective_on < datetime.now(timezone.utc).date():
        raise HTTPException(status_code=422, detail="Backdated publication forbidden")
    duplicate = db.scalar(select(WorkflowDefinitionVersion.id).where(
        WorkflowDefinitionVersion.enterprise_id == row.enterprise_id,
        WorkflowDefinitionVersion.code == row.code,
        WorkflowDefinitionVersion.status == "published",
        WorkflowDefinitionVersion.effective_on == payload.effective_on,
    ))
    if duplicate:
        raise HTTPException(status_code=409, detail="Effective date already published")
    row.status = "published"
    row.published_by = admin.id
    row.effective_on = payload.effective_on
    audit(db, admin, row.enterprise_id, "workflow.published", row.id, {
        "code": row.code, "version": row.version,
        "effective_on": str(row.effective_on),
    })
    commit(db)
    db.refresh(row)
    return view_version(row)


def validate_form(document: WorkflowDocument, values: dict) -> dict:
    from app.configuration.router import validate_value as check_field

    fields = {field.code: field for field in document.fields}
    unknown = set(values) - set(fields)
    if unknown:
        raise HTTPException(status_code=422, detail="Unknown form field")
    result = {}
    for field in document.fields:
        value = check_field(field, values.get(field.code))
        if value is not None:
            result[field.code] = value
    return result


@router.post(
    "/enterprises/{enterprise_id}/service-requests",
    response_model=WorkflowCaseView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_service_case(
    enterprise_id: UUID, payload: WorkflowCaseCreate,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowCaseView:
    enterprise_or_404(db, enterprise_id)
    lock_enterprise(db, enterprise_id)
    require_unit(db, user, enterprise_id, payload.unit_id)
    version = next(
        (row for row in active_versions(db, enterprise_id)
         if row.code == payload.workflow_code), None,
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Published workflow not found")
    document = WorkflowDocument.model_validate(version.document_json)
    values = validate_form(document, payload.values)
    row = WorkflowServiceCase(
        enterprise_id=enterprise_id, unit_id=payload.unit_id,
        definition_id=version.id, title=payload.title.strip(),
        state=document.initial_state, values_json=values, created_by=user.id,
    )
    db.add(row)
    db.flush()
    db.add(WorkflowCaseEvent(
        enterprise_id=enterprise_id, case_id=row.id, from_state=None,
        to_state=row.state, transition_code="created", actor_id=user.id, note="",
        created_at=datetime.now(timezone.utc),
    ))
    audit(db, user, enterprise_id, "workflow.case_created", row.id, {
        "template": version.code, "version": version.version,
        "unit_id": str(row.unit_id), "fields": sorted(values),
    })
    commit(db)
    db.refresh(row)
    return view_case(db, row)


@router.get(
    "/enterprises/{enterprise_id}/service-requests",
    response_model=list[WorkflowCaseView],
)
def list_service_cases(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkflowCaseView]:
    enterprise_or_404(db, enterprise_id)
    statement = select(WorkflowServiceCase).where(
        WorkflowServiceCase.enterprise_id == enterprise_id
    )
    if user.role != "admin":
        units = allowed_unit_ids(db, user, enterprise_id)
        if not units:
            raise HTTPException(status_code=404, detail="Enterprise not found")
        statement = statement.where(WorkflowServiceCase.unit_id.in_(units))
    rows = db.scalars(statement.order_by(
        WorkflowServiceCase.created_at.desc(), WorkflowServiceCase.id.desc(),
    ).limit(100)).all()
    return [view_case(db, item) for item in rows]


@router.get("/service-requests/{case_id}", response_model=WorkflowCaseView)
def get_service_case(
    case_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowCaseView:
    return view_case(db, visible_case(db, user, case_id))


@router.get(
    "/service-requests/{case_id}/definition", response_model=WorkflowVersionView,
)
def get_case_definition(
    case_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowVersionView:
    row = visible_case(db, user, case_id)
    version = db.get(WorkflowDefinitionVersion, row.definition_id)
    if version is None:
        raise HTTPException(status_code=404, detail="Workflow definition not found")
    return view_version(version)


@router.get(
    "/service-requests/{case_id}/history", response_model=list[WorkflowCaseEventView],
)
def get_case_history(
    case_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[WorkflowCaseEventView]:
    row = visible_case(db, user, case_id)
    events = db.scalars(select(WorkflowCaseEvent).where(
        WorkflowCaseEvent.case_id == row.id,
        WorkflowCaseEvent.enterprise_id == row.enterprise_id,
    ).order_by(
        WorkflowCaseEvent.created_at, WorkflowCaseEvent.id,
    )).all()
    return [
        WorkflowCaseEventView(
            id=e.id, from_state=e.from_state, to_state=e.to_state,
            transition_code=e.transition_code, actor_id=e.actor_id,
            note=e.note, created_at=e.created_at,
        ) for e in events
    ]


@router.post(
    "/service-requests/{case_id}/transitions", response_model=WorkflowCaseView,
    dependencies=[Depends(require_csrf)],
)
def move_service_case(
    case_id: UUID, payload: WorkflowMove,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> WorkflowCaseView:
    row = visible_case(db, user, case_id)
    lock_enterprise(db, row.enterprise_id)
    db.refresh(row, with_for_update=True)
    require_unit(db, user, row.enterprise_id, row.unit_id)
    if row.state != payload.expected_state:
        raise HTTPException(status_code=409, detail="Stale service request state")
    version = db.get(WorkflowDefinitionVersion, row.definition_id)
    if version is None or version.status != "published":
        raise HTTPException(status_code=409, detail="Workflow definition unavailable")
    document = WorkflowDocument.model_validate(version.document_json)
    transition = next((
        t for t in document.transitions
        if t.code == payload.transition_code and t.from_state == row.state
    ), None)
    if transition is None:
        raise HTTPException(status_code=409, detail="Transition not allowed in current state")
    if transition.actor == "creator" and row.created_by != user.id:
        raise HTTPException(status_code=403, detail="Only request creator may transition")
    if transition.actor == "manager" and user.role not in {"manager", "admin"}:
        raise HTTPException(status_code=403, detail="Manager role required")
    if transition.actor == "admin" and user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator role required")
    if transition.independent_review and user.id == row.created_by:
        raise HTTPException(status_code=403, detail="Independent reviewer required")
    if transition.independent_review and len(payload.note.strip()) < 10:
        raise HTTPException(status_code=422, detail="Independent review requires a reason")
    before = row.state
    row.state = transition.to_state
    db.add(WorkflowCaseEvent(
        enterprise_id=row.enterprise_id, case_id=row.id,
        from_state=before, to_state=row.state,
        transition_code=transition.code, actor_id=user.id,
        note=payload.note.strip(), created_at=datetime.now(timezone.utc),
    ))
    audit(db, user, row.enterprise_id, "workflow.case_transitioned", row.id, {
        "transition": transition.code, "from": before, "to": row.state,
        "version": version.version,
    })
    commit(db)
    db.refresh(row)
    return view_case(db, row)
