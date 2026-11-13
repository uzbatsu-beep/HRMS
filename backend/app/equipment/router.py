"""Scoped asset registry and independently approved digital permit-to-work record.

This is a human-recorded workflow; never implies PLC/interlock authorization.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.credentials.models import CredentialType
from app.database import get_db
from app.equipment import service
from app.equipment.models import (
    AssetCredentialRequirement, EquipmentAsset, EquipmentAuditEvent,
    WorkEquipmentLink, WorkPermit,
)
from app.equipment.schemas import (
    AssetCreate, AssetCredentialCreate, AssetStateChange, AssetView,
    EquipmentLinkCreate, PermitDraft, PermitReason, PermitView, SafetyPackage,
)
from app.identity.models import UserAccount
from app.identity.security import get_current_user, require_admin, require_csrf
from app.organization.access import allowed_unit_ids
from app.organization.models import Enterprise, OrganizationUnit
from app.work import service as work_service
from app.work.models import WorkOrder
from app.work.router import read_order, require_dispatcher

router = APIRouter(prefix=f"{settings.api_v1_prefix}/equipment", tags=["equipment"])
UTC = timezone.utc


def asset_scope(db: Session, user: UserAccount, asset: EquipmentAsset | None) -> EquipmentAsset:
    if asset is None or (
        user.role != "admin" and asset.unit_id not in allowed_unit_ids(
            db, user, asset.enterprise_id
        )
    ):
        raise HTTPException(status_code=404, detail="Equipment not found")
    return asset


def get_asset(db: Session, user: UserAccount, asset_id: UUID) -> EquipmentAsset:
    return asset_scope(db, user, db.get(EquipmentAsset, asset_id))


def asset_view(db: Session, item: EquipmentAsset) -> AssetView:
    ids = db.scalars(select(AssetCredentialRequirement.type_id).where(
        AssetCredentialRequirement.enterprise_id == item.enterprise_id,
        AssetCredentialRequirement.asset_id == item.id,
    ).order_by(AssetCredentialRequirement.type_id)).all()
    return AssetView(
        id=item.id, enterprise_id=item.enterprise_id, unit_id=item.unit_id,
        code=item.code, name=item.name, kind=item.kind,
        serial_number=item.serial_number, status=item.status,
        required_credential_type_ids=list(ids),
    )


def locked_order(db: Session, user: UserAccount, order_id: UUID) -> WorkOrder:
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    work_service.lock_enterprise(db, order.enterprise_id)
    db.refresh(order, with_for_update=True)
    if user.role != "admin" and order.unit_id not in allowed_unit_ids(
        db, user, order.enterprise_id
    ):
        raise HTTPException(status_code=404, detail="Work order not found")
    return order


def checked_order(db: Session, user: UserAccount, order_id: UUID) -> WorkOrder:
    return read_order(db, user, order_id)


def ensure_editable(order: WorkOrder, allow_hold: bool = False) -> None:
    allowed = {"open", "assigned", "on_hold"} if allow_hold else {"open", "assigned"}
    if order.status not in allowed:
        raise HTTPException(status_code=409, detail="Work permit cannot be changed in this state")


def permit_view(row: WorkPermit) -> PermitView:
    return PermitView.model_validate(row)


def require_permit(db: Session, order: WorkOrder, permit_id: UUID) -> WorkPermit:
    row = db.get(WorkPermit, permit_id)
    newest = service.latest_permit(db, order.id)
    if row is None or row.enterprise_id != order.enterprise_id or (
        row.work_order_id != order.id
    ) or newest is None or newest.id != row.id:
        raise HTTPException(status_code=404, detail="Current work permit not found")
    return row


def hold_active_work(
    db: Session, order: WorkOrder, actor: UserAccount, reason: str,
) -> None:
    if order.status == "in_progress":
        order.status = "on_hold"
        order.on_hold_at = datetime.now(UTC)
        order.hold_reason = reason[:400]
        work_service.audit(db, actor, order, "safety.equipment_hold", {
            "reason": reason,
        })


@router.get("/enterprises/{enterprise_id}/assets", response_model=list[AssetView])
def list_assets(
    enterprise_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AssetView]:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    permitted = allowed_unit_ids(db, user, enterprise_id)
    if user.role != "admin" and not permitted:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    statement = select(EquipmentAsset).where(EquipmentAsset.enterprise_id == enterprise_id)
    if user.role != "admin":
        statement = statement.where(EquipmentAsset.unit_id.in_(permitted))
    assets = db.scalars(statement.order_by(EquipmentAsset.code).limit(200)).all()
    return [asset_view(db, item) for item in assets]


@router.post(
    "/enterprises/{enterprise_id}/assets",
    status_code=status.HTTP_201_CREATED, response_model=AssetView,
    dependencies=[Depends(require_csrf)],
)
def create_asset(
    enterprise_id: UUID, payload: AssetCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssetView:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    unit = db.get(OrganizationUnit, payload.unit_id)
    if unit is None or unit.enterprise_id != enterprise_id:
        raise HTTPException(status_code=404, detail="Unit not found")
    work_service.lock_enterprise(db, enterprise_id)
    row = EquipmentAsset(
        enterprise_id=enterprise_id, unit_id=payload.unit_id,
        code=payload.code.strip().lower(), name=payload.name.strip(),
        kind=payload.kind, serial_number=payload.serial_number,
        status="active", created_by=admin.id,
    )
    db.add(row)
    work_service.flush_safe(db)
    service.audit(db, admin, enterprise_id, "asset.created", row.id, {
        "code": row.code, "unit_id": str(row.unit_id),
    })
    work_service.commit_safe(db)
    return asset_view(db, row)


@router.post(
    "/assets/{asset_id}/state", response_model=AssetView,
    dependencies=[Depends(require_csrf)],
)
def set_asset_state(
    asset_id: UUID, payload: AssetStateChange,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssetView:
    asset = get_asset(db, admin, asset_id)
    work_service.lock_enterprise(db, asset.enterprise_id)
    db.refresh(asset, with_for_update=True)
    if asset.status == payload.status:
        raise HTTPException(status_code=409, detail="Equipment already has this state")
    prior = asset.status
    asset.status = payload.status
    if asset.status == "out_of_service":
        links = db.scalars(select(WorkEquipmentLink).where(
            WorkEquipmentLink.enterprise_id == asset.enterprise_id,
            WorkEquipmentLink.asset_id == asset.id,
        )).all()
        for link in links:
            order = db.get(WorkOrder, link.work_order_id)
            if order is not None and order.status == "in_progress":
                hold_active_work(
                    db, order, admin,
                    "Asset was marked out of service; human safety review required",
                )
    service.audit(db, admin, asset.enterprise_id, "asset.state_changed", asset.id, {
        "old": prior, "new": payload.status, "reason": payload.reason,
    })
    work_service.commit_safe(db)
    return asset_view(db, asset)


@router.post(
    "/assets/{asset_id}/required-credentials",
    status_code=status.HTTP_201_CREATED, response_model=AssetView,
    dependencies=[Depends(require_csrf)],
)
def require_asset_credential(
    asset_id: UUID, payload: AssetCredentialCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssetView:
    asset = get_asset(db, admin, asset_id)
    work_service.lock_enterprise(db, asset.enterprise_id)
    kind = db.get(CredentialType, payload.type_id)
    if kind is None or kind.enterprise_id != asset.enterprise_id:
        raise HTTPException(status_code=422, detail="Credential type belongs to another tenant")
    prior = db.scalar(select(AssetCredentialRequirement).where(
        AssetCredentialRequirement.asset_id == asset.id,
        AssetCredentialRequirement.type_id == kind.id,
    ))
    if prior:
        raise HTTPException(status_code=409, detail="Requirement already exists")
    db.add(AssetCredentialRequirement(
        enterprise_id=asset.enterprise_id, asset_id=asset.id,
        type_id=kind.id, added_by=admin.id,
    ))
    # A stricter equipment requirement becomes active immediately, so already
    # executing work must enter a software hold pending human reauthorization.
    links = db.scalars(select(WorkEquipmentLink).where(
        WorkEquipmentLink.asset_id == asset.id,
        WorkEquipmentLink.enterprise_id == asset.enterprise_id,
    )).all()
    for link in links:
        order = db.get(WorkOrder, link.work_order_id)
        if order and order.status == "in_progress":
            hold_active_work(
                db, order, admin, "Equipment credential policy changed during work"
            )
    service.audit(db, admin, asset.enterprise_id, "asset.credential_required", asset.id, {
        "type_id": str(kind.id),
    })
    work_service.commit_safe(db)
    return asset_view(db, asset)


@router.post(
    "/orders/{order_id}/equipment",
    status_code=status.HTTP_201_CREATED,
    response_model=SafetyPackage, dependencies=[Depends(require_csrf)],
)
def link_equipment(
    order_id: UUID, payload: EquipmentLinkCreate,
    actor: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SafetyPackage:
    order = locked_order(db, actor, order_id)
    if order.status != "open" or service.link_for(db, order.id):
        raise HTTPException(
            status_code=409, detail="Equipment must be linked once, before staffing"
        )
    asset = get_asset(db, actor, payload.asset_id)
    if asset.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Equipment not found")
    if asset.status != "active":
        raise HTTPException(status_code=409, detail="Equipment is out of service")
    db.add(WorkEquipmentLink(
        enterprise_id=order.enterprise_id, work_order_id=order.id,
        asset_id=asset.id, linked_by=actor.id,
    ))
    service.audit(db, actor, order.enterprise_id, "work.equipment_linked", order.id, {
        "asset_id": str(asset.id),
    })
    work_service.commit_safe(db)
    return package_view(db, order, actor)


def package_view(db: Session, order: WorkOrder, user: UserAccount) -> SafetyPackage:
    link = service.link_for(db, order.id)
    asset = get_asset(db, user, link.asset_id) if link is not None else None
    permit = service.latest_permit(db, order.id)
    return SafetyPackage(
        work_order_id=order.id,
        asset=asset_view(db, asset) if asset else None,
        permit=permit_view(permit) if permit else None,
        equipment_blockers=service.equipment_problems(db, order),
    )


@router.get("/orders/{order_id}/safety-package", response_model=SafetyPackage)
def read_safety_package(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> SafetyPackage:
    order = checked_order(db, user, order_id)
    return package_view(db, order, user)


@router.post(
    "/orders/{order_id}/permit",
    response_model=PermitView, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def prepare_permit(
    order_id: UUID, payload: PermitDraft,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PermitView:
    order = locked_order(db, user, order_id)
    ensure_editable(order, allow_hold=True)
    if service.link_for(db, order.id) is None:
        raise HTTPException(status_code=409, detail="Work must be linked to equipment")
    prior = service.latest_permit(db, order.id)
    if prior is not None and prior.status != "revoked":
        raise HTTPException(status_code=409, detail="Current permit must be revoked first")
    row = WorkPermit(
        enterprise_id=order.enterprise_id, work_order_id=order.id,
        version=(prior.version + 1) if prior else 1, status="draft",
        hazards_reviewed=payload.hazards_reviewed,
        energy_isolation_attested=payload.energy_isolation_attested,
        area_access_attested=payload.area_access_attested,
        evidence_reference=payload.evidence_reference,
        prepared_by=user.id,
    )
    db.add(row)
    work_service.flush_safe(db)
    service.audit(db, user, order.enterprise_id, "permit.prepared", row.id, {
        "order_id": str(order.id), "version": row.version,
        "checklist": {
            "hazards_reviewed": row.hazards_reviewed,
            "energy_isolation_attested": row.energy_isolation_attested,
            "area_access_attested": row.area_access_attested,
        },
        "evidence_reference": row.evidence_reference,
    })
    work_service.commit_safe(db)
    return permit_view(row)


@router.post(
    "/orders/{order_id}/permit/{permit_id}/submit",
    response_model=PermitView, dependencies=[Depends(require_csrf)],
)
def submit_permit(
    order_id: UUID, permit_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PermitView:
    order = locked_order(db, user, order_id)
    ensure_editable(order, allow_hold=True)
    row = require_permit(db, order, permit_id)
    if row.status != "draft":
        raise HTTPException(status_code=409, detail="Only draft permits can be submitted")
    if not all((
        row.hazards_reviewed,
        row.energy_isolation_attested,
        row.area_access_attested,
        row.evidence_reference,
    )):
        raise HTTPException(status_code=409, detail="Checklist attestation is incomplete")
    row.status = "submitted"
    row.submitted_at = datetime.now(UTC)
    service.audit(db, user, order.enterprise_id, "permit.submitted", row.id, {
        "version": row.version,
    })
    work_service.commit_safe(db)
    return permit_view(row)


@router.post(
    "/orders/{order_id}/permit/{permit_id}/approve",
    response_model=PermitView, dependencies=[Depends(require_csrf)],
)
def approve_permit(
    order_id: UUID, permit_id: UUID,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PermitView:
    order = locked_order(db, admin, order_id)
    ensure_editable(order, allow_hold=True)
    row = require_permit(db, order, permit_id)
    if row.status != "submitted":
        raise HTTPException(status_code=409, detail="Permit must be submitted")
    if row.prepared_by == admin.id:
        raise HTTPException(status_code=403, detail="Independent approver required")
    if service.equipment_problems(db, order) != ["WORK_PERMIT_NOT_APPROVED"]:
        raise HTTPException(status_code=409, detail="Equipment must be active")
    row.status = "approved"
    row.approved_by = admin.id
    row.approved_at = datetime.now(UTC)
    service.audit(db, admin, order.enterprise_id, "permit.approved", row.id, {
        "version": row.version, "work_order_id": str(order.id),
    })
    work_service.commit_safe(db)
    return permit_view(row)


@router.post(
    "/orders/{order_id}/permit/{permit_id}/revoke",
    response_model=PermitView, dependencies=[Depends(require_csrf)],
)
def revoke_permit(
    order_id: UUID, permit_id: UUID, payload: PermitReason,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> PermitView:
    order = locked_order(db, admin, order_id)
    if order.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Terminal work has immutable permit history")
    row = require_permit(db, order, permit_id)
    if row.status == "revoked":
        raise HTTPException(status_code=409, detail="Permit already revoked")
    row.status = "revoked"
    row.revoked_by = admin.id
    row.revoked_at = datetime.now(UTC)
    row.revoke_reason = payload.reason
    hold_active_work(db, order, admin, "Work permit revoked; reauthorization required")
    service.audit(db, admin, order.enterprise_id, "permit.revoked", row.id, {
        "reason": payload.reason, "version": row.version,
    })
    work_service.commit_safe(db)
    return permit_view(row)


@router.get("/enterprises/{enterprise_id}/audit", response_model=list[dict])
def equipment_audit(
    enterprise_id: UUID,
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[dict]:
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    rows = db.scalars(select(EquipmentAuditEvent).where(
        EquipmentAuditEvent.enterprise_id == enterprise_id,
    ).order_by(EquipmentAuditEvent.created_at.desc()).limit(100)).all()
    return [
        {
            "id": str(row.id), "action": row.action,
            "actor_id": str(row.actor_id), "subject_id": str(row.subject_id),
            "details_json": row.details_json,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]
