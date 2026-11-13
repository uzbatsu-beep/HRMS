"""Immutable work requirements, one-assignee jobs and auditable lifecycle."""

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_work_order_tenant_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_work_order_code"),
        ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_work_unit_tenant",
        ),
        CheckConstraint("ends_at > starts_at", name="ck_work_order_interval"),
        CheckConstraint(
            "status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_order_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    activity_code: Mapped[str] = mapped_column(String(64), nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkSkillRequirement(Base):
    __tablename__ = "work_skill_requirements"
    __table_args__ = (
        UniqueConstraint("work_order_id", "skill_id", name="uq_work_required_skill"),
        ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_work_skill_order_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_work_skill_tenant_scale",
        ),
        ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_work_min_level_scale",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    min_level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class WorkOrderAssignment(Base):
    """A job has at most one staffing decision in this first vertical slice."""

    __tablename__ = "work_order_assignments"
    __table_args__ = (
        UniqueConstraint("work_order_id", name="uq_work_order_one_assignee"),
        UniqueConstraint("reservation_id", name="uq_work_order_reservation"),
        ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_assignment_work_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_work_assignment_person_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_work_assignment_resource_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    reservation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_reservations.id"), nullable=False
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkAuditEvent(Base):
    __tablename__ = "work_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    work_order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("work_orders.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
