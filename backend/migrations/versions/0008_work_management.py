"""Work orders, immutable skill requirements, staffing links and audit.

Revision ID: 0008_work_management
Revises: 0007_availability
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_work_management"
down_revision: Union[str, None] = "0007_availability"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "work_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("unit_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("activity_code", sa.String(64), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_work_order_tenant_id"),
        sa.UniqueConstraint("enterprise_id", "code", name="uq_work_order_code"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "unit_id"],
            ["organization_units.enterprise_id", "organization_units.id"],
            name="fk_work_unit_tenant",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_work_order_interval"),
        sa.CheckConstraint(
            "status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')",
            name="ck_work_order_status",
        ),
    )
    op.create_index(
        "ix_work_enterprise_unit_status",
        "work_orders", ["enterprise_id", "unit_id", "status"],
    )
    op.create_table(
        "work_skill_requirements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scale_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_level_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.UniqueConstraint("work_order_id", "skill_id", name="uq_work_required_skill"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_work_skill_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "skill_id", "scale_id"],
            ["skills.enterprise_id", "skills.id", "skills.scale_id"],
            name="fk_work_skill_tenant_scale",
        ),
        sa.ForeignKeyConstraint(
            ["scale_id", "min_level_id"],
            ["skill_scale_levels.scale_id", "skill_scale_levels.id"],
            name="fk_work_min_level_scale",
        ),
    )
    op.create_table(
        "work_order_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("work_order_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "reservation_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_reservations.id"), nullable=False,
        ),
        sa.Column(
            "assigned_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "assigned_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.UniqueConstraint("work_order_id", name="uq_work_order_one_assignee"),
        sa.UniqueConstraint("reservation_id", name="uq_work_order_reservation"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_assignment_work_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_work_assignment_person_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_work_assignment_resource_tenant",
        ),
    )
    op.create_index("ix_work_assigned_person", "work_order_assignments", ["person_id"])
    op.create_table(
        "work_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "work_order_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("work_orders.id"), nullable=False,
        ),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("work_audit_events")
    op.drop_index("ix_work_assigned_person", table_name="work_order_assignments")
    op.drop_table("work_order_assignments")
    op.drop_table("work_skill_requirements")
    op.drop_index("ix_work_enterprise_unit_status", table_name="work_orders")
    op.drop_table("work_orders")
