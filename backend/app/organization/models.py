"""Organization hierarchy, configurable unit types, grants and change audit."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Enterprise(Base):
    __tablename__ = "enterprises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class OrganizationUnitType(Base):
    __tablename__ = "organization_unit_types"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_org_unit_types_enterprise_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_org_unit_types_enterprise_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class OrganizationUnit(Base):
    __tablename__ = "organization_units"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_org_units_enterprise_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_org_units_enterprise_code"),
        ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["organization_unit_types.enterprise_id", "organization_unit_types.id"],
            name="fk_org_unit_type_same_enterprise",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "parent_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_org_unit_parent_same_enterprise",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_org_unit_not_own_parent"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class UserUnitScope(Base):
    """An explicit allow grant. Non-admin users have no access without a grant."""

    __tablename__ = "user_unit_scopes"
    __table_args__ = (
        UniqueConstraint("user_id", "unit_id", name="uq_user_unit_scopes_user_unit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organization_units.id"), nullable=False
    )
    include_descendants: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class OrganizationAuditEvent(Base):
    """Append-only event records for administrative organization changes."""

    __tablename__ = "organization_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
