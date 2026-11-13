"""Equipment downtime windows, append-only planning/cancellation history.

Revision ID: 0013_asset_downtime
Revises: 0012_asset_skill_gates
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013_asset_downtime"
down_revision: Union[str, None] = "0012_asset_skill_gates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_downtime_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "enterprise_id", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("enterprises.id"), nullable=False,
        ),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(400), nullable=False),
        sa.Column(
            "created_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"), nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.Column(
            "cancelled_by", postgresql.UUID(as_uuid=True),
            sa.ForeignKey("user_accounts.id"),
        ),
        sa.Column("cancel_reason", sa.String(400)),
        sa.UniqueConstraint("enterprise_id", "id", name="uq_downtime_tenant_id"),
        sa.ForeignKeyConstraint(
            ["enterprise_id", "asset_id"],
            ["equipment_assets.enterprise_id", "equipment_assets.id"],
            name="fk_downtime_asset_tenant",
        ),
        sa.CheckConstraint("ends_at > starts_at", name="ck_downtime_interval"),
    )
    op.create_index(
        "ix_downtime_asset_range",
        "asset_downtime_windows",
        ["enterprise_id", "asset_id", "starts_at", "ends_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_downtime_asset_range", table_name="asset_downtime_windows")
    op.drop_table("asset_downtime_windows")
