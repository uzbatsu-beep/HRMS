"""Weekly resource shifts, company calendar holidays and scheduled holds.

Revision ID: 0007_availability
Revises: 0006_credentials
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_availability"
down_revision: Union[str, None] = "0006_credentials"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shift_rules",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("local_start", sa.Time(timezone=False), nullable=False),
        sa.Column("local_end", sa.Time(timezone=False), nullable=False),
        sa.Column("time_zone", sa.String(80), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=False),
        sa.Column("valid_to", sa.Date()),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_shift_rule_resource_tenant",
        ),
        sa.CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_shift_rule_weekday"),
        sa.CheckConstraint(
            "valid_to IS NULL OR valid_to >= valid_from", name="ck_shift_rule_validity"
        ),
    )
    op.create_index("ix_shift_rules_resource", "shift_rules", ["resource_id"])
    op.create_table(
        "calendar_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.Column("time_zone", sa.String(80), nullable=False),
        sa.Column("label", sa.String(180), nullable=False),
        sa.UniqueConstraint(
            "enterprise_id", "local_date", "time_zone",
            name="uq_calendar_closure_tenant_local_day",
        ),
    )
    op.create_table(
        "absence_periods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.String(24), nullable=False),
        sa.Column("note", sa.String(400)),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_absence_resource_tenant",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_absence_dates"),
        sa.CheckConstraint(
            "category IN ('leave', 'training', 'unavailable')",
            name="ck_absence_category",
        ),
    )
    op.create_index("ix_absence_resource", "absence_periods", ["resource_id"])
    op.create_table(
        "work_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("external_reference", sa.String(100)),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "resource_id"],
            ["workforce_resources.enterprise_id", "workforce_resources.id"],
            name="fk_reservation_resource_tenant",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_reservation_dates"),
        sa.UniqueConstraint(
            "enterprise_id", "external_reference", name="uq_reservation_external_ref"
        ),
    )
    op.create_index("ix_reservations_resource", "work_reservations", ["resource_id"])
    op.create_table(
        "scheduling_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column(
            "actor_user_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
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
    op.drop_table("scheduling_audit_events")
    op.drop_index("ix_reservations_resource", table_name="work_reservations")
    op.drop_table("work_reservations")
    op.drop_index("ix_absence_resource", table_name="absence_periods")
    op.drop_table("absence_periods")
    op.drop_table("calendar_closures")
    op.drop_index("ix_shift_rules_resource", table_name="shift_rules")
    op.drop_table("shift_rules")
