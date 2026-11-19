"""Isolated declarative service-request workflows and immutable state events.

Never substitute for WorkOrder, WorkPermit, credentials or access control.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.configuration.models import DOCUMENT
from app.database import Base


class WorkflowDefinitionVersion(Base):
    __tablename__ = "workflow_definition_versions"
    __table_args__ = (
        UniqueConstraint(
            "enterprise_id", "code", "version", name="uq_workflow_tenant_code_version"
        ),
        UniqueConstraint("enterprise_id", "id", name="uq_workflow_tenant_id"),
        CheckConstraint("version > 0", name="ck_workflow_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'published')",
            name="ck_workflow_version_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    document_json: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    effective_on: Mapped[date | None] = mapped_column(Date)


class WorkflowServiceCase(Base):
    """Informational intake record, not a safety permit or executable job."""

    __tablename__ = "workflow_service_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_workflow_case_unit_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "definition_id"],
            ["workflow_definition_versions.enterprise_id", "workflow_definition_versions.id"],
            name="fk_workflow_case_definition_tenant",
        ),
        UniqueConstraint("enterprise_id", "id", name="uq_workflow_case_tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    unit_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    definition_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    values_json: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class WorkflowCaseEvent(Base):
    __tablename__ = "workflow_case_events"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "case_id"],
            ["workflow_service_cases.enterprise_id", "workflow_service_cases.id"],
            name="fk_workflow_event_case_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    from_state: Mapped[str | None] = mapped_column(String(32))
    to_state: Mapped[str] = mapped_column(String(32), nullable=False)
    transition_code: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    note: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
