"""Personnel, workforce and dated organization links.

Revision ID: 0004_personnel
Revises: 0003_organization_scope
Create Date: 2026-11-12
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_personnel"
down_revision: Union[str, None] = "0003_organization_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("employee_code", sa.String(64), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("middle_name", sa.String(100), nullable=True),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_persons_enterprise_id"),
        sa.UniqueConstraint(
            "enterprise_id", "employee_code", name="uq_persons_enterprise_code"
        ),
    )
    op.create_table(
        "workforce_resources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_workforce_resource_person_same_enterprise",
        ),
        sa.UniqueConstraint(
            "enterprise_id", "id", name="uq_workforce_resources_enterprise_id"
        ),
        sa.UniqueConstraint("person_id", name="uq_workforce_resources_person"),
        sa.CheckConstraint(
            "kind IN ('employee', 'contractor')", name="ck_workforce_resource_kind"
        ),
    )
    op.create_table(
        "employment_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position_title", sa.String(160), nullable=True),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_employment_resource_same_enterprise",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_employment_unit_same_enterprise",
        ),
        sa.UniqueConstraint(
            "enterprise_id", "id", name="uq_employment_assignments_enterprise_id"
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_employment_assignment_dates",
        ),
    )
    op.create_index(
        "ix_employment_assignments_resource", "employment_assignments", ["resource_id"]
    )
    op.create_index(
        "ix_employment_assignments_unit", "employment_assignments", ["unit_id"]
    )
    op.create_table(
        "team_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_team_resource_same_enterprise",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_team_unit_same_enterprise",
        ),
        sa.CheckConstraint(
            "effective_to IS NULL OR effective_to >= effective_from",
            name="ck_team_membership_dates",
        ),
    )
    op.create_index("ix_team_memberships_resource", "team_memberships", ["resource_id"])
    op.create_table(
        "personnel_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "person_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("persons.id"), nullable=False,
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )
    op.create_index(
        "ix_personnel_audit_person", "personnel_audit_events", ["person_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_personnel_audit_person", table_name="personnel_audit_events")
    op.drop_table("personnel_audit_events")
    op.drop_index("ix_team_memberships_resource", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_index("ix_employment_assignments_unit", table_name="employment_assignments")
    op.drop_index("ix_employment_assignments_resource", table_name="employment_assignments")
    op.drop_table("employment_assignments")
    op.drop_table("workforce_resources")
    op.drop_table("persons")
