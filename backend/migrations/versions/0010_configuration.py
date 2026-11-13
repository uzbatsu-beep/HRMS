"""Governed configuration and immutable personnel attribute snapshots.

Revision ID: 0010_configuration
Revises: 0009_work_execution
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_configuration"
down_revision: Union[str, None] = "0009_work_execution"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "config_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("fields_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "approved_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column(
            "published_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("effective_on", sa.Date),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_config_version_tenant_id"),
        sa.UniqueConstraint("enterprise_id", "version", name="uq_config_version_number"),
        sa.CheckConstraint("version > 0", name="ck_config_version_positive"),
        sa.CheckConstraint(
            "status IN ('draft','validated','approved','published')",
            name="ck_config_version_status",
        ),
    )
    op.create_index(
        "ix_config_enterprise_effective",
        "config_versions", ["enterprise_id", "status", "effective_on"],
    )
    op.create_table(
        "person_field_revisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("values_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "changed_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"], ["persons.enterprise_id", "persons.id"],
            name="fk_person_field_person_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "config_version_id"],
            ["config_versions.enterprise_id", "config_versions.id"],
            name="fk_person_field_version_tenant",
        ),
    )
    op.create_index(
        "ix_person_field_history", "person_field_revisions",
        ["enterprise_id", "person_id", "created_at"],
    )
    op.create_table(
        "configuration_audit",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "actor_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details_json", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_configuration_audit_enterprise",
        "configuration_audit", ["enterprise_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_configuration_audit_enterprise", table_name="configuration_audit")
    op.drop_table("configuration_audit")
    op.drop_index("ix_person_field_history", table_name="person_field_revisions")
    op.drop_table("person_field_revisions")
    op.drop_index("ix_config_enterprise_effective", table_name="config_versions")
    op.drop_table("config_versions")
