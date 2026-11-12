"""Organization management and secure, scoped read endpoints."""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids, can_read_enterprise
from app.organization.models import (
    Enterprise,
    OrganizationAuditEvent,
    OrganizationUnit,
    OrganizationUnitType,
    UserUnitScope,
)
from app.organization.schemas import (
    AuditEventView,
    EnterpriseCreate,
    EnterpriseView,
    ScopeGrantCreate,
    ScopeView,
    UnitCreate,
    UnitTypeCreate,
    UnitTypeView,
    UnitUpdate,
    UnitView,
)

router = APIRouter(prefix=f"{settings.api_v1_prefix}/org", tags=["organization"])


def flush_or_conflict(db: Session) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting organization data") from exc


def lock_enterprise(db: Session, enterprise_id: UUID) -> None:
    """Serialize structural writes within one enterprise, preventing concurrent cycles."""
    db.execute(select(Enterprise).where(Enterprise.id == enterprise_id).with_for_update())


def commit_or_conflict(db: Session) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Conflicting organization data") from exc


def audit(
    db: Session,
    actor: UserAccount,
    enterprise_id: UUID,
    action: str,
    subject_id: UUID,
    details: dict[str, object],
) -> None:
    db.add(
        OrganizationAuditEvent(
            actor_user_id=actor.id,
            enterprise_id=enterprise_id,
            action=action,
            subject_id=subject_id,
            details_json=json.dumps(details, ensure_ascii=False, default=str),
        )
    )


def enterprise_or_404(db: Session, enterprise_id: UUID) -> Enterprise:
    enterprise = db.get(Enterprise, enterprise_id)
    if enterprise is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return enterprise


def readable_enterprise(
    db: Session, user: UserAccount, enterprise_id: UUID
) -> Enterprise:
    enterprise = enterprise_or_404(db, enterprise_id)
    if not can_read_enterprise(db, user, enterprise_id):
        raise HTTPException(status_code=404, detail="Enterprise not found")
    return enterprise


def unit_or_404(db: Session, unit_id: UUID) -> OrganizationUnit:
    unit = db.get(OrganizationUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="Organization unit not found")
    return unit


def verify_type(db: Session, enterprise_id: UUID, type_id: UUID) -> None:
    unit_type = db.get(OrganizationUnitType, type_id)
    if unit_type is None or unit_type.enterprise_id != enterprise_id:
        raise HTTPException(status_code=422, detail="Invalid organization unit type")


def verify_parent(
    db: Session,
    enterprise_id: UUID,
    parent_id: UUID | None,
    self_id: UUID | None = None,
) -> None:
    if parent_id is None:
        return
    seen: set[UUID] = set()
    current_id: UUID | None = parent_id
    while current_id is not None:
        if current_id == self_id or current_id in seen:
            raise HTTPException(status_code=422, detail="Hierarchy cycle detected")
        seen.add(current_id)
        current = db.get(OrganizationUnit, current_id)
        if current is None or current.enterprise_id != enterprise_id:
            raise HTTPException(status_code=422, detail="Parent must belong to this enterprise")
        current_id = current.parent_id


def visible_unit(unit: OrganizationUnit, allowed: set[UUID]) -> UnitView:
    view = UnitView.model_validate(unit)
    if unit.parent_id is not None and unit.parent_id not in allowed:
        return view.model_copy(update={"parent_id": None})
    return view


@router.get("/enterprises", response_model=list[EnterpriseView])
def list_enterprises(
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[Enterprise]:
    enterprises = list(db.scalars(select(Enterprise).order_by(Enterprise.name)).all())
    if user.role == "admin":
        return enterprises
    return [
        enterprise
        for enterprise in enterprises
        if can_read_enterprise(db, user, enterprise.id)
    ]


@router.post(
    "/enterprises",
    response_model=EnterpriseView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_enterprise(
    payload: EnterpriseCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> Enterprise:
    enterprise = Enterprise(code=payload.code.lower(), name=payload.name.strip())
    db.add(enterprise)
    flush_or_conflict(db)
    audit(db, admin, enterprise.id, "enterprise.created", enterprise.id, {"code": enterprise.code})
    commit_or_conflict(db)
    db.refresh(enterprise)
    return enterprise


@router.get("/enterprises/{enterprise_id}/types", response_model=list[UnitTypeView])
def list_unit_types(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[OrganizationUnitType]:
    readable_enterprise(db, user, enterprise_id)
    return list(
        db.scalars(
            select(OrganizationUnitType)
            .where(OrganizationUnitType.enterprise_id == enterprise_id)
            .order_by(OrganizationUnitType.name)
        ).all()
    )


@router.post(
    "/enterprises/{enterprise_id}/types",
    response_model=UnitTypeView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_unit_type(
    enterprise_id: UUID,
    payload: UnitTypeCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OrganizationUnitType:
    enterprise_or_404(db, enterprise_id)
    unit_type = OrganizationUnitType(
        enterprise_id=enterprise_id, code=payload.code.lower(), name=payload.name.strip()
    )
    db.add(unit_type)
    flush_or_conflict(db)
    audit(
        db, admin, enterprise_id, "unit_type.created", unit_type.id,
        {"code": unit_type.code, "name": unit_type.name},
    )
    commit_or_conflict(db)
    db.refresh(unit_type)
    return unit_type


@router.get("/enterprises/{enterprise_id}/units", response_model=list[UnitView])
def list_units(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[UnitView]:
    readable_enterprise(db, user, enterprise_id)
    allowed = allowed_unit_ids(db, user, enterprise_id)
    units = db.scalars(
        select(OrganizationUnit)
        .where(OrganizationUnit.enterprise_id == enterprise_id)
        .order_by(OrganizationUnit.name)
    ).all()
    return [visible_unit(unit, allowed) for unit in units if unit.id in allowed]


@router.post(
    "/enterprises/{enterprise_id}/units",
    response_model=UnitView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def create_unit(
    enterprise_id: UUID,
    payload: UnitCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OrganizationUnit:
    enterprise_or_404(db, enterprise_id)
    lock_enterprise(db, enterprise_id)
    verify_type(db, enterprise_id, payload.type_id)
    verify_parent(db, enterprise_id, payload.parent_id)
    unit = OrganizationUnit(
        enterprise_id=enterprise_id,
        code=payload.code.lower(),
        name=payload.name.strip(),
        type_id=payload.type_id,
        parent_id=payload.parent_id,
    )
    db.add(unit)
    flush_or_conflict(db)
    audit(
        db, admin, enterprise_id, "unit.created", unit.id,
        {"code": unit.code, "parent_id": unit.parent_id, "type_id": unit.type_id},
    )
    commit_or_conflict(db)
    db.refresh(unit)
    return unit


@router.get("/units/{unit_id}", response_model=UnitView)
def get_unit(
    unit_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UnitView:
    unit = unit_or_404(db, unit_id)
    allowed = allowed_unit_ids(db, user, unit.enterprise_id)
    if unit.id not in allowed:
        raise HTTPException(status_code=404, detail="Organization unit not found")
    return visible_unit(unit, allowed)


@router.patch(
    "/units/{unit_id}",
    response_model=UnitView,
    dependencies=[Depends(require_csrf)],
)
def update_unit(
    unit_id: UUID,
    payload: UnitUpdate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> OrganizationUnit:
    unit = unit_or_404(db, unit_id)
    lock_enterprise(db, unit.enterprise_id)
    updates = payload.model_fields_set
    if not updates:
        raise HTTPException(status_code=422, detail="No changes provided")
    if "name" in updates:
        if payload.name is None or not payload.name.strip():
            raise HTTPException(status_code=422, detail="Name must not be empty")
        unit.name = payload.name.strip()
    if "type_id" in updates:
        if payload.type_id is None:
            raise HTTPException(status_code=422, detail="Type must not be null")
        verify_type(db, unit.enterprise_id, payload.type_id)
        unit.type_id = payload.type_id
    if "parent_id" in updates:
        verify_parent(db, unit.enterprise_id, payload.parent_id, self_id=unit.id)
        unit.parent_id = payload.parent_id
    audit(
        db, admin, unit.enterprise_id, "unit.updated", unit.id,
        {"changes": payload.model_dump(exclude_unset=True, mode="json")},
    )
    commit_or_conflict(db)
    db.refresh(unit)
    return unit


@router.get("/scopes", response_model=list[ScopeView])
def list_scopes(
    user_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[UserUnitScope]:
    query = select(UserUnitScope).order_by(UserUnitScope.id)
    if user_id is not None:
        query = query.where(UserUnitScope.user_id == user_id)
    return list(db.scalars(query).all())


@router.post(
    "/scopes",
    response_model=ScopeView,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def grant_scope(
    payload: ScopeGrantCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> UserUnitScope:
    account = db.get(UserAccount, payload.user_id)
    unit = db.get(OrganizationUnit, payload.unit_id)
    if account is None or not account.is_active:
        raise HTTPException(status_code=422, detail="User not found or inactive")
    if unit is None:
        raise HTTPException(status_code=422, detail="Organization unit not found")
    if account.role == "admin":
        raise HTTPException(status_code=422, detail="Admin already has global access")
    grant = UserUnitScope(
        user_id=payload.user_id,
        unit_id=payload.unit_id,
        include_descendants=payload.include_descendants,
    )
    db.add(grant)
    flush_or_conflict(db)
    audit(
        db, admin, unit.enterprise_id, "scope.granted", grant.id,
        {
            "user_id": grant.user_id, "unit_id": grant.unit_id,
            "include_descendants": grant.include_descendants,
        },
    )
    commit_or_conflict(db)
    db.refresh(grant)
    return grant


@router.delete(
    "/scopes/{scope_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_csrf)],
)
def revoke_scope(
    scope_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> None:
    grant = db.get(UserUnitScope, scope_id)
    if grant is None:
        raise HTTPException(status_code=404, detail="Scope not found")
    unit = unit_or_404(db, grant.unit_id)
    audit(
        db, admin, unit.enterprise_id, "scope.revoked", grant.id,
        {"user_id": grant.user_id, "unit_id": grant.unit_id},
    )
    db.delete(grant)
    commit_or_conflict(db)


@router.get("/audit", response_model=list[AuditEventView])
def list_audit(
    enterprise_id: UUID | None = None,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[OrganizationAuditEvent]:
    query = select(OrganizationAuditEvent).order_by(OrganizationAuditEvent.created_at.desc())
    if enterprise_id is not None:
        query = query.where(OrganizationAuditEvent.enterprise_id == enterprise_id)
    return list(db.scalars(query.limit(100)).all())
