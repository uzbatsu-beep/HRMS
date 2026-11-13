"""Assets, scoped equipment requirements and human-attested work permit history.

These records are software safeguards, not certified plant safety controls.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class EquipmentAsset(Base):
    __tablename__ = "equipment_assets"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_asset_tenant_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_asset_code"),
        ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_asset_unit_tenant",
        ),
        CheckConstraint(
            "kind IN ('machine', 'robot', 'production_line', 'other')",
            name="ck_asset_kind",
        ),
        CheckConstraint(
            "status IN ('active', 'out_of_service')", name="ck_asset_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetCredentialRequirement(Base):
    """Append-only; existing historical permits are never silently weakened."""

    __tablename__ = "asset_credential_requirements"
    __table_args__ = (
        UniqueConstraint(
            "asset_id", "type_id", name="uq_asset_credential_requirement"
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_asset_requirement_asset_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "type_id"], ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_asset_requirement_type_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AssetSkillRequirement(Base):
    """Append-only mandatory skill threshold for every person working on an asset."""

    __tablename__ = "asset_skill_requirements"
    __table_args__ = (
        UniqueConstraint("asset_id", "skill_id", name="uq_asset_required_skill"),
        ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_asset_skill_asset_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_asset_skill_tenant_scale",
        ),
        ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_asset_skill_min_level_scale",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    min_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    added_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkEquipmentLink(Base):
    """One immutable target asset per work order in the v1 safety workflow."""

    __tablename__ = "work_equipment_links"
    __table_args__ = (
        UniqueConstraint("work_order_id", name="uq_work_equipment_single_target"),
        UniqueConstraint("enterprise_id", "work_order_id", name="uq_work_equipment_tenant_order"),
        ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_work_equipment_order_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_work_equipment_asset_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    asset_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    linked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class WorkPermit(Base):
    """Human attestation and independent review, never a physical interlock."""

    __tablename__ = "work_permits"
    __table_args__ = (
        UniqueConstraint("work_order_id", "version", name="uq_work_permit_version"),
        ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_equipment_links.enterprise_id", "work_equipment_links.work_order_id"],
            name="fk_work_permit_order_equipment_tenant",
        ),
        CheckConstraint("version > 0", name="ck_work_permit_version"),
        CheckConstraint(
            "status IN ('draft', 'submitted', 'approved', 'revoked')",
            name="ck_work_permit_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    hazards_reviewed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    energy_isolation_attested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    area_access_attested: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    evidence_reference: Mapped[str | None] = mapped_column(String(200))
    prepared_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(String(400))


class EquipmentAuditEvent(Base):
    __tablename__ = "equipment_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
