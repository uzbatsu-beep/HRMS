"""Competence catalog, immutable scale versions and reviewable evidence.

Revision ID: 0005_competence
Revises: 0004_personnel
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_competence"
down_revision: Union[str, None] = "0004_personnel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "skill_categories",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True)),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_skill_categories_tenant_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_skill_categories_code"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "parent_id"],
            ["skill_categories.enterprise_id", "skill_categories.id"],
            name="fk_skill_category_parent_same_tenant",
        ),
        sa.CheckConstraint("parent_id IS NULL OR parent_id <> id", name="ck_skill_category_self"),
    )
    op.create_table(
        "skill_scales",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_skill_scales_tenant_id"),
        sa.UniqueConstraint(
            "enterprise_id", "code", "version", name="uq_skill_scale_version"
        ),
        sa.CheckConstraint("version > 0", name="ck_skill_scale_version_positive"),
    )
    op.create_table(
        "skill_scale_levels",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "scale_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("skill_scales.id"), nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(100), nullable=False),
        sa.Column("description", sa.Text()),
        sa.UniqueConstraint("scale_id", "id", name="uq_skill_scale_level_scale_id"),
        sa.UniqueConstraint("scale_id", "ordinal", name="uq_skill_scale_level_ordinal"),
        sa.CheckConstraint("ordinal >= 0", name="ck_skill_scale_ordinal"),
    )
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint(
            "enterprise_id", "id", "scale_id", name="uq_skill_tenant_id_scale"
        ),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_skill_tenant_code"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "category_id"],
            ["skill_categories.enterprise_id", "skill_categories.id"],
            name="fk_skill_category_same_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "scale_id"],
            ["skill_scales.enterprise_id", "skill_scales.id"],
            name="fk_skill_scale_same_tenant",
        ),
    )
    op.create_table(
        "user_person_links",
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), primary_key=True,
        ),
        sa.Column(
            "person_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id"), nullable=False,
        ),
        sa.Column(
            "linked_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.UniqueConstraint("person_id", name="uq_link_person"),
    )
    op.create_table(
        "person_skill_assessments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "submitted_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "reviewed_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("reviewed_at", sa.DateTime(timezone=True)),
        sa.Column("review_note", sa.Text()),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"], name="fk_assessment_person_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_assessment_skill_scale_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["scale_id", "level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_assessment_level_scale",
        ),
        sa.CheckConstraint(
            "source IN ('self', 'expert')", name="ck_assessment_source"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected')", name="ck_assessment_status"
        ),
    )
    op.create_index(
        "ix_assessment_person_skill",
        "person_skill_assessments", ["person_id", "skill_id", "submitted_at"],
    )
    op.create_table(
        "skill_evidence",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "assessment_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("person_skill_assessments.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("reference", sa.String(250)),
        sa.CheckConstraint(
            "kind IN ('observation', 'training', 'document', 'other')",
            name="ck_skill_evidence_kind",
        ),
    )
    op.create_table(
        "competence_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("competence_audit_events")
    op.drop_table("skill_evidence")
    op.drop_index("ix_assessment_person_skill", table_name="person_skill_assessments")
    op.drop_table("person_skill_assessments")
    op.drop_table("user_person_links")
    op.drop_table("skills")
    op.drop_table("skill_scale_levels")
    op.drop_table("skill_scales")
    op.drop_table("skill_categories")
