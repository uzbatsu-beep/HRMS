"""Crew staffing, work priority, and manual safety-hold state.

Revision ID: 0009_work_execution
Revises: 0008_work_management
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_work_execution"
down_revision: Union[str, None] = "0008_work_management"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "work_orders",
        sa.Column(
            "priority", sa.String(16), server_default="normal", nullable=False,
        ),
    )
    op.add_column("work_orders", sa.Column("on_hold_at", sa.DateTime(timezone=True)))
    op.add_column("work_orders", sa.Column("hold_reason", sa.String(400)))
    op.add_column(
        "work_orders", sa.Column("last_safety_check_at", sa.DateTime(timezone=True))
    )
    op.create_check_constraint(
        "ck_work_order_priority", "work_orders",
        "priority IN ('routine', 'normal', 'urgent', 'critical')",
    )
    op.drop_constraint("ck_work_order_status", "work_orders", type_="check")
    op.create_check_constraint(
        "ck_work_order_status", "work_orders",
        "status IN ('open', 'assigned', 'in_progress', 'on_hold', 'completed', 'cancelled')",
    )
    op.create_table(
        "work_crew_members",
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
        sa.Column("role", sa.String(24), nullable=False),
        sa.Column(
            "joined_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "joined_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("removed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("work_order_id", "person_id", name="uq_work_crew_person"),
        sa.UniqueConstraint("reservation_id", name="uq_work_crew_reservation"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "work_order_id"],
            ["work_orders.enterprise_id", "work_orders.id"],
            name="fk_work_crew_order_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "person_id"],
            ["persons.enterprise_id", "persons.id"],
            name="fk_work_crew_person_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_work_crew_resource_tenant",
        ),
        sa.CheckConstraint(
            "role IN ('specialist', 'assistant', 'observer')",
            name="ck_work_crew_role",
        ),
    )
    op.create_index(
        "ix_work_crew_order_active",
        "work_crew_members", ["work_order_id", "removed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_work_crew_order_active", table_name="work_crew_members")
    op.drop_table("work_crew_members")
    # A rollback cannot represent on_hold in the previous status constraint.
    op.execute(
        "UPDATE work_orders SET status = 'in_progress' WHERE status = 'on_hold'"
    )
    op.drop_constraint("ck_work_order_status", "work_orders", type_="check")
    op.create_check_constraint(
        "ck_work_order_status", "work_orders",
        "status IN ('open', 'assigned', 'in_progress', 'completed', 'cancelled')",
    )
    op.drop_constraint("ck_work_order_priority", "work_orders", type_="check")
    op.drop_column("work_orders", "last_safety_check_at")
    op.drop_column("work_orders", "hold_reason")
    op.drop_column("work_orders", "on_hold_at")
    op.drop_column("work_orders", "priority")
