"""Scoped asset registry and independently approved digital permit-to-work record.

This is a human-recorded workflow; never implies PLC/interlock authorization.
"""

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.availability.service import as_utc
from app.config import settings
from app.competence.models import Skill, SkillScaleLevel
from app.credentials.models import CredentialType
from app.database import get_db
from app.equipment import audit_explorer, readiness, service
from app.equipment.models import (
    AssetCredentialRequirement, AssetDowntimeWindow, AssetSkillRequirement,
    EquipmentAsset, EquipmentAuditEvent,
    WorkEquipmentLink, WorkPermit,
)
from app.equipment.schemas import (
    AssetCreate, AssetCredentialCreate, AssetSkillCreate, AssetSkillView,
    DowntimeCreate, DowntimeCancel, DowntimeView,
    AssetStateChange, AssetView, EquipmentReadiness, LinkedWorkReadiness,
    EquipmentLinkCreate, PermitDraft, PermitReason, PermitView, SafetyPackage,
    CrewReadinessSnapshot, EquipmentAuditPage,
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
    skill_requirements = db.scalars(select(AssetSkillRequirement).where(
        AssetSkillRequirement.enterprise_id == item.enterprise_id,
        AssetSkillRequirement.asset_id == item.id,
    ).order_by(AssetSkillRequirement.skill_id)).all()
    skills: list[AssetSkillView] = []
    for requirement in skill_requirements:
        skill = db.get(Skill, requirement.skill_id)
        minimum = db.get(SkillScaleLevel, requirement.min_level_id)
        skills.append(AssetSkillView(
            id=requirement.id, skill_id=requirement.skill_id,
            skill_code=skill.code if skill else "missing",
            skill_name=skill.name if skill else "Missing or archived skill",
            min_level_id=requirement.min_level_id,
            min_ordinal=minimum.ordinal if minimum else -1,
        ))
    return AssetView(
        id=item.id, enterprise_id=item.enterprise_id, unit_id=item.unit_id,
        code=item.code, name=item.name, kind=item.kind,
        serial_number=item.serial_number, status=item.status,
        required_credential_type_ids=list(ids), required_skills=skills,
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
    "/assets/{asset_id}/required-skills",
    status_code=status.HTTP_201_CREATED, response_model=AssetView,
    dependencies=[Depends(require_csrf)],
)
def require_asset_skill(
    asset_id: UUID, payload: AssetSkillCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> AssetView:
    asset = get_asset(db, admin, asset_id)
    work_service.lock_enterprise(db, asset.enterprise_id)
    skill = db.get(Skill, payload.skill_id)
    threshold = db.get(SkillScaleLevel, payload.min_level_id)
    if (
        skill is None or not skill.is_active or skill.enterprise_id != asset.enterprise_id
        or threshold is None or threshold.scale_id != skill.scale_id
    ):
        raise HTTPException(status_code=422, detail="Foreign, inactive or mismatched skill")
    existing = db.scalar(select(AssetSkillRequirement).where(
        AssetSkillRequirement.asset_id == asset.id,
        AssetSkillRequirement.skill_id == skill.id,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Asset skill already required")
    db.add(AssetSkillRequirement(
        enterprise_id=asset.enterprise_id, asset_id=asset.id,
        skill_id=skill.id, scale_id=skill.scale_id,
        min_level_id=threshold.id, added_by=admin.id,
    ))
    # Stricter requirements cannot silently leave an active task running.
    links = db.scalars(select(WorkEquipmentLink).where(
        WorkEquipmentLink.enterprise_id == asset.enterprise_id,
        WorkEquipmentLink.asset_id == asset.id,
    )).all()
    for link in links:
        order = db.get(WorkOrder, link.work_order_id)
        if order is not None and order.status == "in_progress":
            hold_active_work(
                db, order, admin, "Equipment skill policy changed during work"
            )
    service.audit(db, admin, asset.enterprise_id, "asset.skill_required", asset.id, {
        "skill_id": str(skill.id), "min_level_id": str(threshold.id),
        "min_ordinal": threshold.ordinal,
    })
    work_service.commit_safe(db)
    return asset_view(db, asset)


@router.get("/assets/{asset_id}/downtime", response_model=list[DowntimeView])
def list_asset_downtime(
    asset_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> list[AssetDowntimeWindow]:
    asset = get_asset(db, user, asset_id)
    return list(db.scalars(select(AssetDowntimeWindow).where(
        AssetDowntimeWindow.enterprise_id == asset.enterprise_id,
        AssetDowntimeWindow.asset_id == asset.id,
    ).order_by(
        AssetDowntimeWindow.starts_at.desc(), AssetDowntimeWindow.id.desc(),
    ).limit(100)).all())


@router.post(
    "/assets/{asset_id}/downtime", response_model=DowntimeView,
    status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_csrf)],
)
def schedule_asset_downtime(
    asset_id: UUID, payload: DowntimeCreate,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> DowntimeView:
    asset = get_asset(db, admin, asset_id)
    work_service.lock_enterprise(db, asset.enterprise_id)
    start, end = as_utc(payload.starts_at), as_utc(payload.ends_at)
    if end <= datetime.now(UTC):
        raise HTTPException(status_code=422, detail="Downtime must end in the future")
    if service.conflicting_downtime(db, asset.enterprise_id, asset.id, start, end):
        raise HTTPException(status_code=409, detail="Equipment downtime interval overlaps")
    row = AssetDowntimeWindow(
        enterprise_id=asset.enterprise_id, asset_id=asset.id,
        starts_at=start, ends_at=end, reason=payload.reason, created_by=admin.id,
    )
    db.add(row)
    work_service.flush_safe(db)
    links = db.scalars(select(WorkEquipmentLink).where(
        WorkEquipmentLink.enterprise_id == asset.enterprise_id,
        WorkEquipmentLink.asset_id == asset.id,
    )).all()
    for link in links:
        order = db.get(WorkOrder, link.work_order_id)
        if (
            order is not None and order.status == "in_progress"
            and as_utc(order.starts_at) < end
            and as_utc(order.ends_at) > start
        ):
            hold_active_work(
                db, order, admin,
                "Scheduled equipment downtime overlaps the work interval",
            )
    service.audit(db, admin, asset.enterprise_id, "asset.downtime_scheduled", row.id, {
        "asset_id": str(asset.id), "starts_at": start.isoformat(),
        "ends_at": end.isoformat(), "reason": row.reason,
    })
    work_service.commit_safe(db)
    return DowntimeView.model_validate(row)


@router.post(
    "/assets/{asset_id}/downtime/{window_id}/cancel",
    response_model=DowntimeView, dependencies=[Depends(require_csrf)],
)
def cancel_asset_downtime(
    asset_id: UUID, window_id: UUID, payload: DowntimeCancel,
    admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> DowntimeView:
    asset = get_asset(db, admin, asset_id)
    work_service.lock_enterprise(db, asset.enterprise_id)
    window = db.get(AssetDowntimeWindow, window_id)
    if (
        window is None or window.enterprise_id != asset.enterprise_id
        or window.asset_id != asset.id
    ):
        raise HTTPException(status_code=404, detail="Downtime window not found")
    if window.cancelled_at is not None:
        raise HTTPException(status_code=409, detail="Downtime already cancelled")
    if as_utc(window.ends_at) <= datetime.now(UTC):
        raise HTTPException(status_code=409, detail="Expired downtime cannot be cancelled")
    window.cancelled_at = datetime.now(UTC)
    window.cancelled_by = admin.id
    window.cancel_reason = payload.reason
    service.audit(db, admin, asset.enterprise_id, "asset.downtime_cancelled", window.id, {
        "asset_id": str(asset.id), "reason": payload.reason,
    })
    # Never auto-resume a work order after cancelling a maintenance interval.
    work_service.commit_safe(db)
    return DowntimeView.model_validate(window)



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


@router.get(
    "/orders/{order_id}/crew-readiness", response_model=CrewReadinessSnapshot,
)
def read_crew_readiness(
    order_id: UUID,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> CrewReadinessSnapshot:
    """On-demand read-only crew snapshot. Never issues work authorization.

    Access requires dispatch role and visibility of BOTH the work-order unit
    and linked equipment unit. No personal identifiers are returned.
    """
    require_dispatcher(user)
    order = read_order(db, user, order_id)
    link = service.link_for(db, order.id)
    if link is None or link.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Equipment-linked work not found")
    asset = get_asset(db, user, link.asset_id)
    if asset.enterprise_id != order.enterprise_id:
        raise HTTPException(status_code=404, detail="Equipment-linked work not found")
    return readiness.snapshot(db, order)


@router.get(
    "/enterprises/{enterprise_id}/readiness", response_model=EquipmentReadiness,
)
def equipment_readiness(
    enterprise_id: UUID, unit_id: UUID | None = None,
    user: UserAccount = Depends(get_current_user),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> EquipmentReadiness:
    """Current permit/asset software blockers only, not personal safety clearance."""
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    permitted = allowed_unit_ids(db, user, enterprise_id)
    if user.role != "admin" and not permitted:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    if unit_id is not None and unit_id not in permitted:
        raise HTTPException(status_code=404, detail="Unit not found")
    scope = {unit_id} if unit_id is not None else permitted
    rows = db.execute(
        select(WorkOrder, WorkEquipmentLink, EquipmentAsset)
        .join(WorkEquipmentLink, WorkEquipmentLink.work_order_id == WorkOrder.id)
        .join(EquipmentAsset, EquipmentAsset.id == WorkEquipmentLink.asset_id)
        .where(
            WorkOrder.enterprise_id == enterprise_id,
            WorkOrder.unit_id.in_(scope),
            EquipmentAsset.enterprise_id == enterprise_id,
            EquipmentAsset.unit_id.in_(permitted),
            WorkOrder.status.in_(("open", "assigned", "in_progress", "on_hold")),
        )
        .order_by(WorkOrder.created_at.desc(), WorkOrder.id.desc())
        .limit(200)
    ).all()
    items: list[LinkedWorkReadiness] = []
    for work, link, asset in rows:
        permit = service.latest_permit(db, work.id)
        reasons = service.equipment_problems(db, work)
        items.append(LinkedWorkReadiness(
            work_order_id=work.id, work_code=work.code,
            title=work.title, unit_id=work.unit_id,
            asset_id=link.asset_id, asset_code=asset.code,
            status=work.status, permit_version=permit.version if permit else None,
            permit_status=permit.status if permit else None,
            software_blockers=reasons,
            crew_eligibility_checked=False,
        ))
    return EquipmentReadiness(
        enterprise_id=enterprise_id, unit_id=unit_id,
        total=len(items),
        blocked=sum(bool(item.software_blockers) for item in items),
        on_hold=sum(item.status == "on_hold" for item in items),
        items=items,
    )


@router.get(
    "/enterprises/{enterprise_id}/audit/explorer",
    response_model=EquipmentAuditPage,
)
def explore_equipment_audit(
    enterprise_id: UUID,
    limit: int = Query(default=20, ge=1, le=50),  # noqa: B008
    action: str | None = Query(default=None, min_length=3, max_length=64),  # noqa: B008
    subject_id: UUID | None = None,
    actor_id: UUID | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: str | None = Query(default=None, max_length=180),  # noqa: B008
    _admin: UserAccount = Depends(require_admin),  # noqa: B008
    db: Session = Depends(get_db),  # noqa: B008
) -> EquipmentAuditPage:
    """Bounded keyset view of redacted metadata, not a compliance certificate."""
    if db.get(Enterprise, enterprise_id) is None:
        raise HTTPException(status_code=404, detail="Enterprise not found")
    # RFC3339 timestamps must be timezone aware to prevent ambiguous bounds.
    if any(value is not None and value.tzinfo is None for value in (since, until)):
        raise HTTPException(status_code=422, detail="Timezone required for audit bounds")
    try:
        return audit_explorer.read_page(
            db, enterprise_id, limit, action=action,
            subject_id=subject_id, actor_id=actor_id,
            since=since, until=until, cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
