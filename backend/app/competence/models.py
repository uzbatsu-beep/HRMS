"""Configurable technical skills with versioned scales and auditable assessments."""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint,
    Integer, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SkillCategory(Base):
    __tablename__ = "skill_categories"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_skill_categories_tenant_id"),
        UniqueConstraint("enterprise_id", "code", name="uq_skill_categories_code"),
        ForeignKeyConstraint(
            ["enterprise_id", "parent_id"],
            ["skill_categories.enterprise_id", "skill_categories.id"],
            name="fk_skill_category_parent_same_tenant",
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_skill_category_self"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)


class SkillScale(Base):
    """A published, immutable version of a level scale."""

    __tablename__ = "skill_scales"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", name="uq_skill_scales_tenant_id"),
        UniqueConstraint("enterprise_id", "code", "version", name="uq_skill_scale_version"),
        CheckConstraint("version > 0", name="ck_skill_scale_version_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SkillScaleLevel(Base):
    __tablename__ = "skill_scale_levels"
    __table_args__ = (
        UniqueConstraint("scale_id", "id", name="uq_skill_scale_level_scale_id"),
        UniqueConstraint("scale_id", "ordinal", name="uq_skill_scale_level_ordinal"),
        CheckConstraint("ordinal >= 0", name="ck_skill_scale_ordinal"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scale_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("skill_scales.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class Skill(Base):
    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("enterprise_id", "id", "scale_id", name="uq_skill_tenant_id_scale"),
        UniqueConstraint("enterprise_id", "code", name="uq_skill_tenant_code"),
        ForeignKeyConstraint(
            ["enterprise_id", "category_id"],
            ["skill_categories.enterprise_id", "skill_categories.id"],
            name="fk_skill_category_same_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "scale_id"],
            ["skill_scales.enterprise_id", "skill_scales.id"],
            name="fk_skill_scale_same_tenant",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    category_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class UserPersonLink(Base):
    """Admin-verified binding; prevents impersonation in self-assessments."""

    __tablename__ = "user_person_links"
    __table_args__ = (UniqueConstraint("person_id", name="uq_link_person"),)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), primary_key=True
    )
    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("persons.id"), nullable=False
    )
    linked_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )


class PersonSkillAssessment(Base):
    __tablename__ = "person_skill_assessments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["enterprise_id", "person_id"], ["persons.enterprise_id", "persons.id"],
            name="fk_assessment_person_tenant",
        ),
        ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_assessment_skill_scale_tenant",
        ),
        ForeignKeyConstraint(
            ["scale_id", "level_id"], ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_assessment_level_scale",
        ),
        CheckConstraint("source IN ('self', 'expert')", name="ck_assessment_source"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_assessment_status"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    person_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scale_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    level_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    submitted_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id")
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)


class SkillEvidence(Base):
    """Metadata describing evidence; real attachment storage is deliberately deferred."""

    __tablename__ = "skill_evidence"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('observation', 'training', 'document', 'other')",
            name="ck_skill_evidence_kind",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assessment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("person_skill_assessments.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str | None] = mapped_column(String(250))


class CompetenceAuditEvent(Base):
    __tablename__ = "competence_audit_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    enterprise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("enterprises.id"), nullable=False
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("user_accounts.id"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
