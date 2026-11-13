"""Versioned, governed non-safety personnel metadata.

JSONB only holds configuration/attribute snapshots. Core workforce, authorization,
credentials and work states remain typed relational domain records.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint, Date, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, JSON, String, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

DOCUMENT = JSON().with_variant(JSONB(), "postgresql")


class ConfigVersion(Base):
    __tablename__ = "config_versions"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_config_version_tenant_id"),
        UniqueConstraint("enterprise_id", "version", name="uq_config_version_number"),
        CheckConstraint("version > 0", name="ck_config_version_positive"),
        CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'published')",
            name="ck_config_version_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    fields_json: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    effective_on: Mapped[date | None] = mapped_column(Date)


class PersonFieldRevision(Base):
    """Immutable field value snapshot. Never overwrite earlier revisions."""

    __tablename__ = "person_field_revisions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "person_id"], ["persons.enterprise_id", "persons.id"],
            name="fk_person_field_person_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "config_version_id"],
            ["config_versions.enterprise_id", "config_versions.id"],
            name="fk_person_field_version_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    config_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    values_json: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    changed_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ConfigurationAudit(Base):
    __tablename__ = "configuration_audit"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    details_json: Mapped[dict] = mapped_column(DOCUMENT, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
