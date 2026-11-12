"""Personnel credentials, immutable work requirements and audit events."""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Date, DateTime, ForeignKey,
    ForeignKeyConstraint, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class CredentialType(Base):
    __tablename__ = "credential_types"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_credential_type_tenant_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_credential_type_code"),
        CheckConstraint(
            "kind IN ('permit', 'certificate', 'qualification', 'training')",
            name="ck_credential_type_kind",
        ),
        CheckConstraint(
            "NOT is_safety_critical OR requires_expiry", name="ck_safety_requires_expiry"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(180), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    is_safety_critical: Mapped[bool] = mapped_column(Boolean, nullable=False)
    requires_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False)


class PersonCredential(Base):
    __tablename__ = "person_credentials"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "person_id"], ["persons.enterprise_id", "persons.id"],
            name="fk_credential_person_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_credential_type_tenant",
        ),
        CheckConstraint(
            "status IN ('pending', 'verified', 'rejected', 'revoked')",
            name="ck_person_credential_status",
        ),
        CheckConstraint(
            "expires_on IS NULL OR expires_on >= valid_from",
            name="ck_person_credential_validity",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_reference: Mapped[str] = mapped_column(String(180), nullable=False)
    issuer: Mapped[str] = mapped_column(String(180), nullable=False)
    issued_on: Mapped[date] = mapped_column(Date, nullable=False)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    expires_on: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoke_reason: Mapped[str | None] = mapped_column(Text)


class CredentialRequirement(Base):
    """An append-only mandatory requirement for a type of work."""

    __tablename__ = "credential_requirements"
    __table_args__ = (
        UniqueConstraint(
            "enterprise_id", "activity_code", "type_id",
            name="uq_credential_activity_requirement",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["credential_types.enterprise_id", "credential_types.id"],
            name="fk_requirement_type_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    activity_code: Mapped[str] = mapped_column(String(64), nullable=False)
    type_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)


class CredentialAuditEvent(Base):
    __tablename__ = "credential_audit_events"

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
