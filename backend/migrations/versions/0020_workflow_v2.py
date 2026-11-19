"""Governed declarative technical service intake workflows.

Revision ID: 0020_workflow_v2
Revises: 0019_scoped_work_operations
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0020_workflow_v2"
down_revision: Union[str, None] = "0019_scoped_work_operations"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "workflow_definition_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("code", sa.String(40), nullable=False),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("document_json", postgresql.JSONB, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id")),
        sa.Column("published_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id")),
        sa.Column("effective_on", sa.Date),
        sa.UniqueConstraint("enterprise_id", "code", "version",
                            name="uq_workflow_tenant_code_version"),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_workflow_tenant_id"),
        sa.CheckConstraint("version > 0", name="ck_workflow_version_positive"),
        sa.CheckConstraint(
            "status IN ('draft', 'validated', 'approved', 'published')",
            name="ck_workflow_version_status",
        ),
    )
    op.create_index(
        "ix_workflow_effective", "workflow_definition_versions",
        ["enterprise_id", "code", "status", "effective_on"],
    )
    op.create_table(
        "workflow_service_cases",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("definition_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("values_json", postgresql.JSONB, nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_workflow_case_unit_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "definition_id"],
            ["workflow_definition_versions.enterprise_id", "workflow_definition_versions.id"],
            name="fk_workflow_case_definition_tenant",
        ),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_workflow_case_tenant_id"),
    )
    op.create_index(
        "ix_workflow_case_scope", "workflow_service_cases",
        ["enterprise_id", "unit_id", "created_at"],
    )
    op.create_table(
        "workflow_case_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("enterprise_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("enterprises.id"), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("from_state", sa.String(32)),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("transition_code", sa.String(32), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("user_accounts.id"), nullable=False),
        sa.Column("note", sa.String(400), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "case_id"],
            ["workflow_service_cases.enterprise_id", "workflow_service_cases.id"],
            name="fk_workflow_event_case_tenant",
        ),
    )
    op.create_index(
        "ix_workflow_case_event_history", "workflow_case_events",
        ["enterprise_id", "case_id", "created_at"],
    )


def downgrade() -> None:
    # Explicitly destructive in development: never downgrade production with
    # submitted requests without export, retention and change approval.
    op.drop_index("ix_workflow_case_event_history", table_name="workflow_case_events")
    op.drop_table("workflow_case_events")
    op.drop_index("ix_workflow_case_scope", table_name="workflow_service_cases")
    op.drop_table("workflow_service_cases")
    op.drop_index("ix_workflow_effective", table_name="workflow_definition_versions")
    op.drop_table("workflow_definition_versions")
