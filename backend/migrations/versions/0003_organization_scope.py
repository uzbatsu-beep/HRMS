"""Introduce configurable organization hierarchy and user-specific unit scopes.

Revision ID: 0003_organization_scope
Revises: 0002_identity_accounts
Create Date: 2026-11-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_organization_scope"
down_revision: Union[str, None] = "0002_identity_accounts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "enterprises",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_table(
        "organization_unit_types",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_org_unit_types_enterprise_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_org_unit_types_enterprise_code"),
    )
    op.create_table(
        "organization_units",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("type_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_org_units_enterprise_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_org_units_enterprise_code"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "type_id"],
            ["organization_unit_types.enterprise_id", "organization_unit_types.id"],
            name="fk_org_unit_type_same_enterprise",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "parent_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_org_unit_parent_same_enterprise",
        ),
        sa.CheckConstraint(
            "parent_id IS NULL OR parent_id <> id", name="ck_org_unit_not_own_parent"
        ),
    )
    op.create_table(
        "user_unit_scopes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "unit_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organization_units.id"), nullable=False,
        ),
        sa.Column("include_descendants", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("user_id", "unit_id", name="uq_user_unit_scopes_user_unit"),
    )
    op.create_table(
        "organization_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("subject_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("organization_audit_events")
    op.drop_table("user_unit_scopes")
    op.drop_table("organization_units")
    op.drop_table("organization_unit_types")
    op.drop_table("enterprises")
